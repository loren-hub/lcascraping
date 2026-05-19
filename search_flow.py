import asyncio
from urllib.parse import urlparse
from utils import url_encode, is_captcha_detected
from anti_detection import human_scroll, delay_after_action, random_delay
from website_extractor import WebsiteExtractor

class SearchFlow:
    def __init__(self, page, config, data_store):
        self.page = page
        self.config = config
        self.data_store = data_store
        self.extractor = WebsiteExtractor()
        
        # Load franchise/chain blocklists from config
        self._name_blocklist = [kw.lower() for kw in self.config.get('filtering.franchise_blocklist', [])]
        self._domain_blocklist = [d.lower() for d in self.config.get('filtering.domain_blocklist', [])]
        
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

    def _is_franchise(self, name, href=''):
        """Returns True if the business matches the franchise/chain blocklist."""
        # Check if filtering is disabled in config.yaml
        if not self.config.get('filtering.enabled', True):
            return False

        name_lower = (name or '').lower()
        for kw in self._name_blocklist:
            if kw in name_lower:
                return True
        # Also check if the website domain is blocklisted
        if href:
            try:
                domain = urlparse(href).netloc.lower()
                for blocked in self._domain_blocklist:
                    if blocked in domain:
                        return True
            except Exception:
                pass
        return False

    async def _collect_visible_businesses(self, collected, skipped_franchises, max_results):
        """
        Scrapes name + href from all currently visible business links in the DOM.
        Adds new ones to `collected` (an ordered dict keyed by href to deduplicate).
        Skips franchises/chains based on the blocklist.
        Returns True if we have reached max_results.
        """
        locators = await self.page.locator('a.hfpxzc').all()
        for loc in locators:
            if len(collected) >= max_results:
                return True
            try:
                href = await loc.get_attribute('href')
                name = await loc.get_attribute('aria-label')
                if href and href not in collected and href not in skipped_franchises and not self.data_store.has_url(href):
                    if self._is_franchise(name):
                        skipped_franchises.add(href)
                        print(f"  ⊘ Skipping franchise: {name}")
                        continue
                    collected[href] = name
            except Exception:
                continue
        return len(collected) >= max_results

    async def scroll_and_collect(self, max_steps, max_results):
        """
        Scrolls the results list and collects business data incrementally.
        
        Google Maps uses virtual scrolling — only ~10-20 items are rendered in the
        DOM at any time. Previous items are removed as you scroll down. So we must
        capture each item's name and href while it is still visible, rather than
        trying to collect everything after scrolling is complete.
        
        Returns a list of dicts with 'name' and 'href' keys.
        """
        # Ordered dict: href -> name (preserves insertion order, deduplicates)
        collected = {}
        skipped_franchises = set()

        # Hover over the results feed to ensure scroll events are captured
        try:
            await self.page.hover('a.hfpxzc')
            await delay_after_action(self.page, self.config)
        except Exception:
            pass

        # Collect whatever is visible before we start scrolling
        await self._collect_visible_businesses(collected, skipped_franchises, max_results)

        previous_total = len(collected)
        stable_count = 0
        
        for i in range(max_steps):
            if len(collected) >= max_results:
                break

            # Tell the browser to scroll down inside the results list
            await human_scroll(self.page, 1, self.config, container_selector='div[role="feed"]')
            
            # Collect newly visible businesses
            await self._collect_visible_businesses(collected, skipped_franchises, max_results)

            if len(collected) == previous_total:
                stable_count += 1
            else:
                stable_count = 0
                previous_total = len(collected)
                
            # If the count hasn't changed in 3 scrolls, we've probably reached the end
            if stable_count >= 3:
                print("No more new results loading.")
                break

        # Convert to a list of dicts
        return [{'name': name, 'href': href} for href, name in collected.items()]

    async def extract_business_by_url(self, business, query):
        """
        Navigates directly to the business's Maps URL to open its detail panel,
        then extracts data. This avoids relying on stale locator references that
        may have been removed from the DOM by virtual scrolling.
        """
        print(f"Extracting: {business['name']}")
        try:
            await self.page.goto(business['href'], wait_until='domcontentloaded')
            await delay_after_action(self.page, self.config)
            
            # Wait for the details (phone, website, etc.) to appear
            try:
                await self.page.wait_for_selector('h1', timeout=5000)
            except Exception:
                pass
            
            # Configurable buffer for loading animations
            load_buffer = self.config.get('delays.page_load_buffer', 1.0)
            await asyncio.sleep(load_buffer)
            
            # Handle consent if it pops up again
            await self.handle_consent()
            
            # Extract the raw HTML of the page and pass it to our extractor
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
        
        # Step 1: Scroll and collect business links incrementally
        businesses = await self.scroll_and_collect(max_scrolls, max_results)
        
        print(f"Found {len(businesses)} businesses to process")

        # Step 2: Trim to our requested limit (safety net)
        businesses = businesses[:max_results]
        
        # Step 3: Extract each business by navigating to its URL directly
        for business in businesses:
            await self.extract_business_by_url(business, query)
