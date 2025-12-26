"""AdsPower Local API wrapper for browser profile management."""

import aiohttp
import asyncio
from typing import Optional
from src.utils import setup_logging


logger = setup_logging("AdsPowerAPI")


class AdsPowerAPI:
    """Wrapper for AdsPower Local API."""
    
    def __init__(self, api_url: str = "http://local.adspower.net:50325"):
        """
        Initialize AdsPower API client.
        
        Args:
            api_url: Base URL for AdsPower Local API
        """
        self.api_url = api_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def _request(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """
        Make GET request to AdsPower API.
        
        Args:
            endpoint: API endpoint (e.g., '/api/v1/browser/start')
            params: Query parameters
            
        Returns:
            JSON response as dict
            
        Raises:
            Exception: If request fails or API returns error
        """
        session = await self._get_session()
        url = f"{self.api_url}{endpoint}"
        
        try:
            async with session.get(url, params=params, timeout=30) as response:
                data = await response.json()
                
                if data.get("code") != 0:
                    error_msg = data.get("msg", "Unknown error")
                    raise Exception(f"AdsPower API error: {error_msg}")
                
                return data
        except aiohttp.ClientError as e:
            raise Exception(f"Connection error to AdsPower: {e}")
        except asyncio.TimeoutError:
            raise Exception("AdsPower API request timed out")
    
    async def start_browser(self, serial_number: str, headless: bool = False) -> dict:
        """
        Start browser profile by serial number.
        
        Args:
            serial_number: Profile serial number
            headless: Run browser in headless mode
            
        Returns:
            Dict with 'ws' (WebSocket URL) and 'selenium' (debug address)
        """
        logger.info(f"Starting browser for profile: {serial_number}")
        
        params = {
            "serial_number": serial_number,
            "open_tabs": 1,
        }
        
        if headless:
            params["headless"] = 1
        
        response = await self._request("/api/v1/browser/start", params)
        
        data = response.get("data", {})
        ws_url = data.get("ws", {}).get("puppeteer", "")
        selenium_url = data.get("ws", {}).get("selenium", "")
        
        if not ws_url:
            raise Exception("Failed to get WebSocket URL from AdsPower")
        
        logger.info(f"Browser started. WebSocket: {ws_url[:50]}...")
        
        return {
            "ws": ws_url,
            "selenium": selenium_url,
            "debug_port": data.get("debug_port", "")
        }
    
    async def stop_browser(self, serial_number: str) -> bool:
        """
        Stop browser profile by serial number.
        
        Args:
            serial_number: Profile serial number
            
        Returns:
            True if stopped successfully
        """
        logger.info(f"Stopping browser for profile: {serial_number}")
        
        try:
            await self._request("/api/v1/browser/stop", {"serial_number": serial_number})
            logger.info(f"Browser stopped for profile: {serial_number}")
            return True
        except Exception as e:
            logger.warning(f"Error stopping browser: {e}")
            return False
    
    async def check_browser(self, serial_number: str) -> bool:
        """
        Check if browser is active for profile.
        
        Args:
            serial_number: Profile serial number
            
        Returns:
            True if browser is active
        """
        try:
            response = await self._request("/api/v1/browser/active", {"serial_number": serial_number})
            data = response.get("data", {})
            return data.get("status") == "Active"
        except Exception:
            return False
    
    async def get_profile_by_serial(self, serial_number: str) -> Optional[dict]:
        """
        Get profile info by serial number.
        
        Args:
            serial_number: Profile serial number
            
        Returns:
            Profile data or None if not found
        """
        try:
            response = await self._request("/api/v1/user/list", {"serial_number": serial_number})
            profiles = response.get("data", {}).get("list", [])
            
            if profiles:
                return profiles[0]
            return None
        except Exception as e:
            logger.error(f"Error getting profile: {e}")
            return None
