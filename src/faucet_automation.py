"""Faucet automation logic for Gensyn Testnet."""

import asyncio
import re
from datetime import datetime, timedelta
from typing import Tuple, Optional
from patchright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from src.utils import setup_logging, format_date


logger = setup_logging("FaucetAutomation")


class FaucetAutomation:
    """Handles faucet claim automation."""
    
    # Selectors
    WALLET_INPUT = "input#wallet-address"
    SEND_BUTTON = "button:has-text('Send 0.1 ETH')"
    COOLDOWN_BUTTON = "button:has-text('Come back in')"
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
    
    async def _check_for_cooldown(self, page: Page) -> Tuple[bool, Optional[str]]:
        """
        Check if there's a cooldown timer on the page.
        Parses 'Come back in Xh Ym Zs' and calculates last work time.
        
        Returns:
            (has_cooldown: bool, calculated_date_work: str or None)
        """
        try:
            cooldown_button = page.locator(self.COOLDOWN_BUTTON)
            
            if await cooldown_button.count() > 0:
                button_text = await cooldown_button.first.text_content()
                logger.info(f"Cooldown detected: {button_text}")
                
                if button_text:
                    # Parse "Come back in 23h 11m 49s" format
                    # Extract hours, minutes, seconds
                    hours = 0
                    minutes = 0
                    seconds = 0
                    
                    h_match = re.search(r'(\d+)h', button_text)
                    m_match = re.search(r'(\d+)m', button_text)
                    s_match = re.search(r'(\d+)s', button_text)
                    
                    if h_match:
                        hours = int(h_match.group(1))
                    if m_match:
                        minutes = int(m_match.group(1))
                    if s_match:
                        seconds = int(s_match.group(1))
                    
                    # Calculate remaining cooldown
                    remaining = timedelta(hours=hours, minutes=minutes, seconds=seconds)
                    
                    # Cooldown is 24 hours, so last work was (24h - remaining) ago
                    cooldown_total = timedelta(hours=24)
                    time_since_last_work = cooldown_total - remaining
                    
                    # Calculate last work datetime
                    last_work_time = datetime.now() - time_since_last_work
                    last_work_str = format_date(last_work_time)
                    
                    logger.info(f"Calculated last work time: {last_work_str}")
                    return True, last_work_str
                
                return True, None
            
            return False, None
        except Exception as e:
            logger.warning(f"Error checking for cooldown: {e}")
            return False, None
    
    def _parse_rate_limit_date(self, error_msg: str) -> Optional[str]:
        """
        Parse rate limit error message to extract datetime.
        Example: 'Try again after 2025-12-27T10:16:22.424Z'
        
        Returns:
            Calculated date_work string in local time or None
        """
        try:
            # Find ISO datetime in the message (UTC time, indicated by Z)
            match = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', error_msg)
            if match:
                date_str = match.group(1)
                # Parse the datetime as UTC
                retry_after_utc = datetime.fromisoformat(date_str)
                
                # Convert UTC to local time
                # Get local timezone offset
                from datetime import timezone
                local_offset = datetime.now().astimezone().utcoffset()
                retry_after_local = retry_after_utc + local_offset
                
                # Last work was 24 hours before retry_after
                last_work_time = retry_after_local - timedelta(hours=24)
                result = format_date(last_work_time)
                
                logger.info(f"Parsed rate limit: retry_after_utc={date_str}, last_work_local={result}")
                return result
        except Exception as e:
            logger.warning(f"Error parsing rate limit date: {e}")
        
        return None

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
                
                # Check for cooldown timer FIRST (visible before entering wallet)
                await asyncio.sleep(1)  # Give time for button to render
                has_cooldown, calculated_date = await self._check_for_cooldown(page)
                if has_cooldown:
                    if calculated_date:
                        logger.info(f"⏰ Cooldown active, calculated last work: {calculated_date}")
                        return False, f"COOLDOWN:{calculated_date}"
                    else:
                        return False, "COOLDOWN:unknown"
                
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
                    
                    # If rate limit, parse date and return as COOLDOWN
                    if "rate limit" in error_msg.lower() or "24 hour" in error_msg.lower():
                        logger.info("Rate limit detected, parsing date...")
                        calculated_date = self._parse_rate_limit_date(error_msg)
                        if calculated_date:
                            return False, f"COOLDOWN:{calculated_date}"
                        return False, "COOLDOWN:unknown"
                    
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
                    
                    # If rate limit, parse date and return as COOLDOWN
                    if "rate limit" in error_msg.lower() or "24 hour" in error_msg.lower():
                        logger.info("Rate limit detected after send, parsing date...")
                        calculated_date = self._parse_rate_limit_date(error_msg)
                        if calculated_date:
                            return False, f"COOLDOWN:{calculated_date}"
                        return False, "COOLDOWN:unknown"
                    
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
