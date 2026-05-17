import re
import json
from bs4 import BeautifulSoup
from urllib.parse import urlparse

class WebsiteExtractor:
    @staticmethod
    def extract(html, business_name):
        soup = BeautifulSoup(html, 'html.parser')
        
        result = {
            'business_name': business_name,
            'website': None,
            'phone': None,
            'address': None
        }

        # 1. Parse JSON-LD structured data
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    if 'url' in data and not result['website']:
                        result['website'] = data['url']
                    if 'telephone' in data and not result['phone']:
                        result['phone'] = data['telephone']
                    if 'address' in data and not result['address']:
                        if isinstance(data['address'], str):
                            result['address'] = data['address']
                        elif isinstance(data['address'], dict):
                            parts = []
                            for k in ['streetAddress', 'addressLocality', 'addressRegion', 'postalCode', 'addressCountry']:
                                if k in data['address']:
                                    parts.append(data['address'][k])
                            result['address'] = ', '.join(parts)
            except Exception:
                pass

        # Google Maps Specific Extractors
        if not result['website']:
            # Typically a link with data-item-id="authority"
            authority_link = soup.select_one('a[data-item-id="authority"]')
            if authority_link and authority_link.has_attr('href'):
                result['website'] = authority_link['href']

        if not result['phone']:
            phone_btn = soup.select_one('button[data-item-id^="phone:tel:"]')
            if phone_btn and phone_btn.has_attr('data-item-id'):
                result['phone'] = phone_btn['data-item-id'].replace('phone:tel:', '')

        if not result['address']:
            address_btn = soup.select_one('button[data-item-id="address"]')
            if address_btn:
                # the address is usually inside a div inside the button
                text = address_btn.get_text(separator=" ", strip=True)
                # Text usually looks like an icon, then the address. We just take the whole text.
                if text:
                    result['address'] = text

        # 2. General fallback for website
        if not result['website']:
            for a in soup.find_all('a', href=True):
                href = a['href']
                # Ignore internal google links
                if 'google.com' not in href and href.startswith('http'):
                    # Ignore common social media or irrelevant links if possible
                    if 'facebook.com' not in href and 'instagram.com' not in href:
                         result['website'] = href
                         break

        # 3. Regex fallback for email (even though task asks for website, maybe useful, or just stick to requirements)
        # requirement is phone, website, address.
        
        return result

if __name__ == '__main__':
    print("\nℹ️  LCA Scraping: website_extractor.py")
    print("=" * 55)
    print("This file is a utility library containing the WebsiteExtractor class.")
    print("It is used internally by main.py to extract business details (name, website,")
    print("phone, address) from the raw HTML of Google Maps detail panels.")
    print("\n🚀 TO RUN THE CRAWLER PIPELINE:")
    print("-" * 55)
    print("The pipeline has been merged! Simply run the main script to extract")
    print("Google Maps leads and immediately crawl their websites for emails.")
    print("👉  python3 main.py")
    print("=" * 55)
    print("\n")

