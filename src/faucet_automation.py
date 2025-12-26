"""Faucet automation logic for Gensyn Testnet."""

import asyncio
from typing import Tuple
from patchright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from src.utils import setup_logging


logger = setup_logging("FaucetAutomation")


class FaucetAutomation:
    """Handles faucet claim automation."""
    
    # Selectors
    WALLET_INPUT = "input#wallet-address"
    SEND_BUTTON = "button:has-text('Send 0.1 ETH')"
    SUCCESS_MESSAGE = "text='Transaction successful'"
    SUCCESS_CONTAINER = "text='Your 0.1 ETH has been successfully sent!'"
    ERROR_MESSAGE = "p.text-red-600"
    
    def __init__(self, config: dict):
        """
        Initialize faucet automation.
        
        Args:
            config: Configuration dict with automation settings
        """
        self.config = config
        automation_config = config.get("automation", {})
        
        self.faucet_url = config.get("faucet_url", "https://www.alchemy.com/faucets/gensyn-testnet")
        self.page_load_timeout = automation_config.get("page_load_timeout", 30000)
        self.action_delay = automation_config.get("action_delay", 2000)
        self.retry_count = automation_config.get("retry_count", 3)
    
    async def _wait_for_page_load(self, page: Page):
        """Wait for page to fully load."""
        try:
            await page.wait_for_load_state("networkidle", timeout=self.page_load_timeout)
        except PlaywrightTimeoutError:
            logger.warning("Page load timeout, continuing anyway...")
    
    async def _clear_and_type(self, page: Page, selector: str, text: str):
        """Clear input field and type text with human-like delay."""
        element = page.locator(selector)
        await element.click()
        await element.fill("")  # Clear existing content
        await asyncio.sleep(0.3)
        await element.type(text, delay=50)  # Human-like typing
    
    async def _check_for_error(self, page: Page) -> Tuple[bool, str]:
        """
        Check if there's an error message on the page.
        
        Returns:
            (has_error: bool, error_message: str)
        """
        try:
            error_element = page.locator(self.ERROR_MESSAGE)
            
            # Wait briefly for error to appear
            await asyncio.sleep(1)
            
            if await error_element.count() > 0:
                error_text = await error_element.first.text_content()
                return True, error_text.strip() if error_text else "Unknown error"
            
            return False, ""
        except Exception as e:
            logger.warning(f"Error checking for errors: {e}")
            return False, ""
    
    async def _check_for_success(self, page: Page) -> bool:
        """
        Check if success message is displayed.
        
        Returns:
            True if success message found
        """
        try:
            # Try multiple success indicators
            success_locators = [
                page.locator(self.SUCCESS_MESSAGE),
                page.locator(self.SUCCESS_CONTAINER),
                page.locator("text='Your 0.1 ETH has been successfully sent!'"),
            ]
            
            for locator in success_locators:
                if await locator.count() > 0:
                    return True
            
            return False
        except Exception as e:
            logger.warning(f"Error checking for success: {e}")
            return False
    
    async def claim_faucet(self, page: Page, wallet_address: str) -> Tuple[bool, str]:
        """
        Perform faucet claim for a wallet address.
        
        Args:
            page: Playwright page object
            wallet_address: Wallet address to claim for
            
        Returns:
            (success: bool, message: str)
        """
        attempt = 0
        last_error = ""
        
        while attempt < self.retry_count:
            attempt += 1
            logger.info(f"Claim attempt {attempt}/{self.retry_count} for {wallet_address[:10]}...")
            
            try:
                # Navigate to faucet page
                logger.info(f"Navigating to faucet: {self.faucet_url}")
                await page.goto(self.faucet_url, wait_until="domcontentloaded")
                await self._wait_for_page_load(page)
                
                # Wait for wallet input to be visible
                logger.info("Waiting for wallet input field...")
                wallet_input = page.locator(self.WALLET_INPUT)
                await wallet_input.wait_for(state="visible", timeout=15000)
                
                # Delay before interaction
                await asyncio.sleep(self.action_delay / 1000)
                
                # Enter wallet address
                logger.info(f"Entering wallet address: {wallet_address}")
                await self._clear_and_type(page, self.WALLET_INPUT, wallet_address)
                
                # Wait a bit after typing
                await asyncio.sleep(1)
                
                # Check for errors after entering address
                has_error, error_msg = await self._check_for_error(page)
                if has_error:
                    logger.warning(f"Error after entering address: {error_msg}")
                    last_error = error_msg
                    
                    # If rate limit, no point retrying
                    if "rate limit" in error_msg.lower() or "24 hour" in error_msg.lower():
                        logger.info("Rate limit detected, skipping retries")
                        return False, error_msg
                    
                    continue
                
                # Wait for send button and click
                logger.info("Looking for Send button...")
                send_button = page.locator(self.SEND_BUTTON)
                await send_button.wait_for(state="visible", timeout=10000)
                
                # Small delay before clicking
                await asyncio.sleep(0.5)
                
                logger.info("Clicking Send 0.1 ETH button...")
                await send_button.click()
                
                # Wait for result (success or error)
                logger.info("Waiting for result...")
                await asyncio.sleep(5)  # Give time for transaction
                
                # Check for success first
                if await self._check_for_success(page):
                    logger.info("✅ Faucet claim successful!")
                    return True, "OK"
                
                # Check for error
                has_error, error_msg = await self._check_for_error(page)
                if has_error:
                    logger.warning(f"Error after clicking send: {error_msg}")
                    last_error = error_msg
                    
                    # If rate limit or CAPTCHA, handle specially
                    if "rate limit" in error_msg.lower() or "24 hour" in error_msg.lower():
                        return False, error_msg
                    
                    if "captcha" in error_msg.lower():
                        logger.info("CAPTCHA error, will retry...")
                        # Reload page and retry
                        await page.reload()
                        await asyncio.sleep(2)
                        continue
                    
                    # Other errors - retry
                    continue
                
                # No success and no error - weird state
                logger.warning("Unknown state - no success or error message")
                last_error = "Unknown state after clicking send"
                
                # Maybe success message takes longer?
                await asyncio.sleep(5)
                if await self._check_for_success(page):
                    logger.info("✅ Faucet claim successful (delayed)!")
                    return True, "OK"
                
            except PlaywrightTimeoutError as e:
                logger.warning(f"Timeout error on attempt {attempt}: {e}")
                last_error = f"Timeout: {str(e)}"
            except Exception as e:
                logger.error(f"Error on attempt {attempt}: {e}")
                last_error = str(e)
            
            # Wait before retry
            if attempt < self.retry_count:
                logger.info(f"Waiting before retry...")
                await asyncio.sleep(3)
        
        # All retries exhausted
        logger.error(f"❌ All {self.retry_count} attempts failed. Last error: {last_error}")
        return False, last_error if last_error else "Max retries exceeded"
