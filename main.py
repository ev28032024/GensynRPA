"""Main orchestrator for Gensyn Faucet Automation."""

import asyncio
import yaml
from pathlib import Path
from patchright.async_api import async_playwright

from src.adspower_api import AdsPowerAPI
from src.sheets_manager import SheetsManager
from src.faucet_automation import FaucetAutomation
from src.utils import setup_logging


logger = setup_logging("GensynRPA")


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    config_file = Path(config_path)
    
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_file, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    logger.info(f"Configuration loaded from {config_path}")
    return config


async def process_profile(
    adspower: AdsPowerAPI,
    faucet: FaucetAutomation,
    sheets: SheetsManager,
    profile: dict,
    playwright_instance
) -> bool:
    """
    Process a single profile.
    
    Args:
        adspower: AdsPower API instance
        faucet: Faucet automation instance
        sheets: Sheets manager instance
        profile: Profile data from spreadsheet
        playwright_instance: Patchright playwright instance
        
    Returns:
        True if successful
    """
    serial_number = profile["profile_number"]
    wallet_address = profile["address"]
    row = profile["row"]
    current_count = profile["kol_vo_zapros"]
    
    logger.info(f"=" * 60)
    logger.info(f"Processing profile: {serial_number}")
    logger.info(f"Wallet: {wallet_address}")
    logger.info(f"=" * 60)
    
    browser = None
    context = None
    page = None
    
    try:
        # Start browser via AdsPower
        browser_info = await adspower.start_browser(serial_number)
        ws_url = browser_info["ws"]
        
        # Connect to browser via CDP
        logger.info("Connecting to browser via CDP...")
        browser = await playwright_instance.chromium.connect_over_cdp(ws_url)
        
        # Get existing context or create new one
        contexts = browser.contexts
        if contexts:
            context = contexts[0]
        else:
            context = await browser.new_context()
        
        # Get existing page or create new one
        pages = context.pages
        if pages:
            page = pages[0]
        else:
            page = await context.new_page()
        
        # Perform faucet claim
        success, message = await faucet.claim_faucet(page, wallet_address)
        
        # Update spreadsheet
        sheets.update_profile_result(
            row=row,
            success=success,
            status_message=message,
            current_count=current_count
        )
        
        return success
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error processing profile {serial_number}: {error_msg}")
        
        # Update spreadsheet with error
        sheets.update_profile_result(
            row=row,
            success=False,
            status_message=f"Error: {error_msg[:100]}",
            current_count=current_count
        )
        
        return False
        
    finally:
        # Close page if we created it
        try:
            if page:
                await page.close()
        except Exception:
            pass
        
        # Disconnect browser
        try:
            if browser:
                await browser.close()
        except Exception:
            pass
        
        # Stop AdsPower browser
        await adspower.stop_browser(serial_number)
        
        # Small delay between profiles
        await asyncio.sleep(2)


async def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("🚀 Gensyn Faucet Automation Started")
    logger.info("=" * 60)
    
    # Load configuration
    config = load_config()
    
    # Initialize components
    adspower = AdsPowerAPI(config.get("adspower", {}).get("api_url", "http://local.adspower.net:50325"))
    sheets = SheetsManager(config)
    faucet = FaucetAutomation(config)
    
    # Update yes/no status based on current time
    logger.info("Updating cooldown status for all profiles...")
    sheets.update_yes_no_column()
    
    # Get profiles to process
    profiles = sheets.get_profiles_to_process()
    
    if not profiles:
        logger.info("No profiles ready for processing. All on cooldown.")
        return
    
    logger.info(f"Found {len(profiles)} profiles to process")
    
    # Statistics
    total = len(profiles)
    success_count = 0
    error_count = 0
    
    # Start Playwright
    async with async_playwright() as playwright:
        for i, profile in enumerate(profiles, 1):
            logger.info(f"\n[{i}/{total}] Processing...")
            
            try:
                success = await process_profile(
                    adspower=adspower,
                    faucet=faucet,
                    sheets=sheets,
                    profile=profile,
                    playwright_instance=playwright
                )
                
                if success:
                    success_count += 1
                else:
                    error_count += 1
                    
            except KeyboardInterrupt:
                logger.info("\nInterrupted by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                error_count += 1
    
    # Close AdsPower session
    await adspower.close()
    
    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("📊 SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total profiles: {total}")
    logger.info(f"✅ Successful: {success_count}")
    logger.info(f"❌ Failed: {error_count}")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
