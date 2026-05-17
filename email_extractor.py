import csv
import re
import asyncio
from urllib.parse import urljoin
from playwright.async_api import async_playwright
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Regex to find standard email patterns
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

# Exclude common image/file extensions that might accidentally match the regex
EXCLUDED_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.css', '.js')

def extract_emails_from_html(html):
    """Scans raw HTML for email addresses and cleans them."""
    emails = set()
    for match in EMAIL_REGEX.finditer(html):
        email = match.group(0).lower()
        if not email.endswith(EXCLUDED_EXTS) and not email.startswith('sentry'):
            emails.add(email)
    return list(emails)

async def find_contact_link(page):
    """Finds a link that likely leads to a contact page."""
    # Common contact keywords in Spanish and English
    keywords = ['contacto', 'contact', 'info', 'about', 'nosotros', 'encuéntranos']
    
    try:
        locators = await page.locator('a[href]').all()
        for loc in locators:
            try:
                href = await loc.get_attribute('href')
                text = await loc.inner_text()
                if href and any(kw in href.lower() or kw in text.lower() for kw in keywords):
                    # Ignore mailto links here, as they are handled separately
                    if not href.startswith('mailto:'):
                        return href
            except Exception:
                continue
    except Exception:
        pass
    return None

async def get_email_for_website(context, url):
    """Visits a website and its contact page to find exactly one email."""
    if not url or not url.startswith('http'):
        return None
        
    page = await context.new_page()
    email_found = None
    
    try:
        # Step 1: Check the homepage
        logging.info(f"Visiting {url}")
        await page.goto(url, wait_until='domcontentloaded', timeout=15000)
        await asyncio.sleep(2) # Give it a moment to render JS text
        
        html = await page.content()
        emails = extract_emails_from_html(html)
        
        # Step 2: Also check mailto links specifically
        locators = await page.locator('a[href^="mailto:"]').all()
        for loc in locators:
            try:
                href = await loc.get_attribute('href')
                if href:
                    email = href.replace('mailto:', '').split('?')[0].strip()
                    if EMAIL_REGEX.match(email):
                        emails.append(email.lower())
            except Exception:
                continue
                
        if emails:
            # Return the first valid email to ensure we only get ONE per website
            email_found = emails[0]
            
        # Step 3: If no email found on homepage, navigate to the contact page
        if not email_found:
            contact_href = await find_contact_link(page)
            if contact_href:
                contact_url = urljoin(url, contact_href)
                logging.info(f"No email on homepage. Checking contact page: {contact_url}")
                await page.goto(contact_url, wait_until='domcontentloaded', timeout=15000)
                await asyncio.sleep(2)
                
                html = await page.content()
                emails = extract_emails_from_html(html)
                if emails:
                    email_found = emails[0]
                    
    except Exception as e:
        logging.warning(f"Error extracting from {url}: {e}")
    finally:
        await page.close()
        
    return email_found

async def main():
    input_file = 'results.csv'
    output_file = 'results_with_emails.csv'
    
    rows = []
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            expected_fieldnames = ['business_name', 'phone', 'website', 'address', 'source_url', 'search_query', 'scraped_at']
            reader = csv.DictReader(f, fieldnames=expected_fieldnames)
            
            for row in reader:
                # Skip header if it exists
                if row.get('business_name') == 'business_name':
                    continue
                rows.append(row)
                
            fieldnames = expected_fieldnames + ['email']
    except FileNotFoundError:
        logging.error(f"Could not find {input_file}. Please run the scraper first.")
        return

    logging.info(f"Found {len(rows)} businesses to process.")
    
    async with async_playwright() as p:
        # Launch headlessly to make it quiet and fast
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # Block unnecessary resources (images, fonts, media) to speed up loading
        await context.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font", "stylesheet"] else route.continue_())

        for i, row in enumerate(rows):
            website = row.get('website', '')
            if website:
                logging.info(f"[{i+1}/{len(rows)}] Processing: {row.get('business_name')}")
                email = await get_email_for_website(context, website)
                row['email'] = email if email else ''
                if email:
                    logging.info(f"--> Found email: {email}")
                else:
                    logging.info("--> No email found.")
            else:
                row['email'] = ''
                
        await browser.close()
        
    # Write the new data out to a separate CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        
    logging.info(f"Done! Saved results with emails to {output_file}")

if __name__ == '__main__':
    asyncio.run(main())
