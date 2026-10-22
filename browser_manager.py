import os
from playwright.async_api import async_playwright
from anti_detection import get_random_user_agent

class BrowserManager:
    def __init__(self, config):
        self.config = config
        self.playwright = None
        self.browser = None
        self.context = None
        
    async def start(self, headless=None):
        self.playwright = await async_playwright().start()
        if headless is None:
            headless = self.config.get('browser.headless', False)
        
        # Launch with stealth: --disable-blink-features=AutomationControlled
        args = [
            '--disable-blink-features=AutomationControlled',
            '--disable-infobars',
            '--start-maximized'
        ]
        
        self.browser = await self.playwright.chromium.launch(
            headless=headless,
            args=args
        )
        
    async def create_page(self, storage_state=None, headless=None):
        if not self.browser:
            await self.start(headless=headless)
            
        viewport = self.config.get('browser.viewport', {'width': 1280, 'height': 900})
        locale = self.config.get('browser.locale', 'en-US')
        timezone = self.config.get('browser.timezone', 'America/New_York')
        user_agent = get_random_user_agent()
        
        context_args = {
            'viewport': viewport,
            'locale': locale,
            'timezone_id': timezone,
            'user_agent': user_agent
        }
        if storage_state and os.path.isfile(storage_state):
            context_args['storage_state'] = storage_state
            
        self.context = await self.browser.new_context(**context_args)
        
        page = await self.context.new_page()
        if self.config.get('anti_detection.use_stealth', True):
            await self.inject_stealth(page)
            
        return page
        
    async def inject_stealth(self, page):
        stealth_js = """
        // Override navigator.webdriver
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });

        // Mock window.chrome
        window.chrome = {
            runtime: {}
        };

        // Mock plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3]
        });

        // Mock languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
        """
        await page.add_init_script(stealth_js)
        
    async def close(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
