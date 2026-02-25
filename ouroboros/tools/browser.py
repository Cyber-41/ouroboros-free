from typing import Dict, Any, Optional, List
import asyncio
from playwright.async_api import async_playwright, Browser, Page
import base64
import logging

logger = logging.getLogger(__name__)

class BrowserAutomation:
    # ... [existing code] ...

    async def perform_action(self, action: str, selector: Optional[str] = None, value: Optional[str] = None, timeout: int = 5000) -> Dict[str, Any]:        
        '''Improved action handling with dark mode support'''
        try:
            if action == 'dark_mode':
                await self.page.emulate_media(color_scheme='dark')
                return {'status': 'success', 'message': 'Dark mode activated'}
            
            # ... [existing action handlers] ...
            
        except Exception as e:
            logger.exception("Browser action failed")
            return {'status': 'error', 'message': str(e)}