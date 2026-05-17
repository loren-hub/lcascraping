import asyncio
from utils import url_encode, is_captcha_detected
from anti_detection import human_scroll, delay_after_action, random_delay
from website_extractor import WebsiteExtractor

class SearchFlow:
    def __init__(self, page, config, data_store):
        self.page = page
        self.config = config
        self.data_store = data_store
        self.extractor = WebsiteExtractor()
        
    async def navigate_to_search(self, query):
        """Builds the Maps search URL and navigates the browser there."""
        url = f"https://www.google.com/maps/search/{url_encode(query)}"
        await self.page.goto(url)
        await self.handle_consent() # Handle cookies/consent if it appears
        await self.check_captcha()
        await random_delay(self.config)
        
    async def handle_consent(self):
        """Clicks 'Reject all' or 'Accept' on the Google consent page if it appears."""
        # Sometimes the page redirects to consent.google.com
        if "consent.google.com" in self.page.url:
            print("Consent page detected. Attempting to click 'Reject all'...")
            try:
                # Comma-separated list of common 'Reject all' selectors
                selector = 'button[aria-label="Rechazar todo"], button[aria-label="Reject all"], button[jsname="tWT92d"], form[action*="consent.google.com/save"] button'
                
                # Wait for any of these buttons to become visible
                button = self.page.locator(selector).first
                await button.wait_for(state="visible", timeout=5000)
                await button.click()
                print("Clicked 'Reject all'. Waiting for redirect back to Maps...")
                
                # networkidle can be flaky, so wait for the URL to change back to Maps
                try:
                    await self.page.wait_for_url("**/maps/search/**", timeout=10000)
                except Exception:
                    await asyncio.sleep(3) # Fallback sleep
            except Exception as e:
                print(f"Failed to click consent button: {e}")

    async def check_captcha(self):
        """Simple check for Google's 'unusual traffic' block."""
        if "consent.google.com" in self.page.url:
            return # Don't check for captcha on the consent page
            
        html = await self.page.content()
        if is_captcha_detected(html):
            print("CAPTCHA detected! Waiting 30s for manual resolution or timeout...")
            await asyncio.sleep(30)
            
    async def scroll_to_load_more(self, max_steps):
        """
        Scrolls the results list multiple times to load more items.
        It stops early if no new items appear after two consecutive scrolls.
        """
        # Hover over the results feed to ensure scroll events are captured
        try:
            await self.page.hover('a.hfpxzc')
            await delay_after_action(self.page, self.config)
        except Exception:
            pass
            
        previous_count = 0
        stable_count = 0
        
        for i in range(max_steps):
            # Tell the browser to scroll down inside the results list
            await human_scroll(self.page, 1, self.config, container_selector='div[role="feed"]')
            
            # Count how many results are currently visible
            count = await self.page.locator('a.hfpxzc').count()
            if count == previous_count:
                stable_count += 1
            else:
                stable_count = 0
                previous_count = count
                
            # If the count hasn't changed in two scrolls, we've probably reached the end
            if stable_count >= 2:
                print("No more new results loading.")
                break
                
    async def get_business_links(self):
        """Gathers all unique business links from the current result list."""
        locators = await self.page.locator('a.hfpxzc').all()
        links = []
        for loc in locators:
            try:
                name = await loc.get_attribute('aria-label')
                href = await loc.get_attribute('href')
                # Only add if it's a new link we haven't seen in this session
                if href and not self.data_store.has_url(href):
                    links.append({'name': name, 'href': href, 'locator': loc})
            except Exception:
                continue
        return links
        
    async def click_and_extract_business(self, business, query):
        """Clicks an individual result, waits for the side panel, and parses its data."""
        print(f"Extracting: {business['name']}")
        try:
            # Click the result to open the detailed side-panel
            await business['locator'].scroll_into_view_if_needed()
            await business['locator'].click()
            await delay_after_action(self.page, self.config)
            
            # Wait a few seconds for the details (phone, website, etc.) to appear
            try:
                await self.page.wait_for_selector('h1', timeout=5000)
            except Exception:
                pass
                
            await asyncio.sleep(2) # Buffer for loading animations
            
            # Extract the raw HTML of the side-panel and pass it to our extractor
            html = await self.page.evaluate('() => document.body.innerHTML')
            result = self.extractor.extract(html, business['name'])
            
            # Add metadata for tracking
            result['source_url'] = business['href']
            result['search_query'] = query
            result['business_email'] = ''
            
            # Save the result immediately to the CSV/JSON file
            self.data_store.append_result(result)
            
        except Exception as e:
            print(f"Error processing {business['name']}: {e}")
            
    async def process_search_query(self, query):
        """Orchestrates the full flow for a single search query."""
        print(f"Starting search for: {query}")
        await self.navigate_to_search(query)
        
        # Pull limits from our config
        max_scrolls = self.config.get('search.scroll_steps_limit', 10)
        max_results = self.config.get('search.max_results_per_query', 20)
        
        # Step 1: Load the list
        await self.scroll_to_load_more(max_scrolls)
        
        # Step 2: Identify the targets
        businesses = await self.get_business_links()
        
        print(f"Found {len(businesses)} businesses to process")
        # Step 3: Trim to our requested limit
        businesses = businesses[:max_results]
        
        # Step 4: Extract each business
        for business in businesses:
            await self.click_and_extract_business(business, query)
