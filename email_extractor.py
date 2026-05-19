import csv
import re
import asyncio
import yaml
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Regex to find standard email patterns
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

# Exclude common image/file extensions that might accidentally match the regex
EXCLUDED_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.css', '.js')


def _load_config():
    """Loads config.yaml and merges blocklist.yaml if it exists."""
    import os
    config = {}
    try:
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        pass

    try:
        if os.path.exists('blocklist.yaml'):
            with open('blocklist.yaml', 'r') as f:
                blocklist = yaml.safe_load(f) or {}
                if isinstance(blocklist, dict):
                    if 'filtering' not in config:
                        config['filtering'] = {}
                    for k, v in blocklist.items():
                        config['filtering'][k] = v
    except Exception:
        pass
    return config


def _get_fake_email_patterns(config):
    """Returns a list of lowercase patterns that identify fake/placeholder emails."""
    defaults = [
        'tu@email', 'your@email', 'info@example', 'test@test',
        'email@email', 'correo@correo', '@sentry', '@wixpress',
        '@example.com', 'noreply@', 'no-reply@', 'donotreply@'
    ]
    patterns = config.get('sanitization', {}).get('fake_email_patterns', defaults)
    return [p.lower() for p in patterns]


def _get_domain_blocklist(config):
    """Returns domains to skip during email extraction (franchises)."""
    if not config.get('filtering', {}).get('enabled', True):
        return []
    return [d.lower() for d in config.get('filtering', {}).get('domain_blocklist', [])]


def _is_fake_email(email, fake_patterns):
    """Returns True if the email matches any fake/placeholder pattern."""
    email_lower = email.lower()
    for pattern in fake_patterns:
        if pattern in email_lower:
            return True
    return False


def _is_blocked_website(url, domain_blocklist):
    """Returns True if the website domain is in the blocklist."""
    try:
        domain = urlparse(url).netloc.lower()
        for blocked in domain_blocklist:
            if blocked in domain:
                return True
    except Exception:
        pass
    return False


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

async def get_email_for_website(context, url, render_wait=1.0, fake_patterns=None):
    """Visits a website and its contact page to find exactly one valid email."""
    if not url or not url.startswith('http'):
        return None
        
    if fake_patterns is None:
        fake_patterns = []
        
    page = await context.new_page()
    email_found = None
    
    try:
        # Step 1: Check the homepage
        logging.info(f"Visiting {url}")
        await page.goto(url, wait_until='domcontentloaded', timeout=15000)
        await asyncio.sleep(render_wait) # Configurable JS render wait
        
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
                
        # Filter out fake emails before picking one
        emails = [e for e in emails if not _is_fake_email(e, fake_patterns)]
                
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
                await asyncio.sleep(render_wait)
                
                html = await page.content()
                emails = extract_emails_from_html(html)
                emails = [e for e in emails if not _is_fake_email(e, fake_patterns)]
                if emails:
                    email_found = emails[0]
                    
    except Exception as e:
        logging.warning(f"Error extracting from {url}: {e}")
    finally:
        await page.close()
        
    return email_found

async def run_email_enrichment(filepath):
    config = _load_config()
    fake_patterns = _get_fake_email_patterns(config)
    domain_blocklist = _get_domain_blocklist(config)
    remove_empty = config.get('sanitization', {}).get('remove_rows_without_email', True)
    render_wait = config.get('delays', {}).get('email_page_render_wait', 1.0)

    rows = []
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            # New fieldnames match exactly what is in data_store.py
            expected_fieldnames = ['business_name', 'business_email', 'phone', 'website', 'address', 'search_query', 'scraped_at', 'email_sent_at']
            reader = csv.DictReader(f, fieldnames=expected_fieldnames)
            
            for row in reader:
                # Skip header if it exists
                if row.get('business_name') == 'business_name':
                    continue
                rows.append(row)
                
            fieldnames = expected_fieldnames
    except FileNotFoundError:
        logging.error(f"Could not find {filepath}. Please ensure Stage 1 ran successfully.")
        return

    logging.info(f"Starting Stage 2: Deep Website Email Crawling for {len(rows)} businesses.")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        await context.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font", "stylesheet"] else route.continue_())

        for i, row in enumerate(rows):
            website = row.get('website', '')
            
            # Skip franchise/chain websites
            if website and _is_blocked_website(website, domain_blocklist):
                logging.info(f"[{i+1}/{len(rows)}] Skipping franchise website: {row.get('business_name')}")
                row['business_email'] = ''
                continue
            
            # If the email is already found, or website is empty, skip
            if website and not row.get('business_email'):
                logging.info(f"[{i+1}/{len(rows)}] Processing: {row.get('business_name')}")
                email = await get_email_for_website(context, website, render_wait, fake_patterns)
                row['business_email'] = email if email else ''
                if email:
                    logging.info(f"--> Found email: {email}")
                else:
                    logging.info("--> No email found.")
            elif not website:
                row['business_email'] = ''
                
        await browser.close()
    
    # --- SANITIZATION PASS ---
    # Re-check all emails against fake patterns (catches pre-existing data too)
    for row in rows:
        email = row.get('business_email', '')
        if email and _is_fake_email(email, fake_patterns):
            logging.info(f"Sanitized fake email '{email}' for {row.get('business_name')}")
            row['business_email'] = ''
    
    # Remove rows without a valid email if configured
    if remove_empty:
        original_count = len(rows)
        rows = [row for row in rows if row.get('business_email')]
        removed = original_count - len(rows)
        if removed > 0:
            logging.info(f"Removed {removed} rows with no valid email ({len(rows)} remaining).")
        
    # Write the enriched data back to the same CSV file
    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        
    logging.info(f"Done! Pipeline fully completed. Enriched results saved to {filepath}")

