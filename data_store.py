import csv
import json
import os
from datetime import datetime

class DataStore:
    def __init__(self, filepath, format='csv', append=True):
        self.filepath = filepath
        self.format = format
        self.append = append
        self.seen_urls = set()
        self.seen_names = set()
        self.seen_websites = set()
        self.seen_emails = set()
        self.fieldnames = ['business_name', 'business_email', 'phone', 'website', 'address', 'search_query', 'scraped_at', 'email_sent_at']
        
        # Load existing records for de-duplication if appending
        if self.append:
            self._load_existing_leads()
            
        self._init_file()
        
    def _load_existing_leads(self):
        """Loads existing business names and websites from the CSV/JSON output to prevent duplication."""
        if not os.path.isfile(self.filepath) or os.path.getsize(self.filepath) == 0:
            return
            
        if self.format == 'csv':
            try:
                with open(self.filepath, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        name = row.get('business_name')
                        if name:
                            self.seen_names.add(name.strip().lower())
                        web = row.get('website')
                        if web:
                            web_clean = web.strip().lower()
                            if web_clean and web_clean not in ('', 'http://', 'https://'):
                                self.seen_websites.add(web_clean)
                        email = row.get('business_email')
                        if email:
                            self.seen_emails.add(email.strip().lower())
            except Exception as e:
                print(f"Warning: Could not load existing CSV leads for deduplication: {e}")
        elif self.format == 'json':
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                         for row in data:
                             name = row.get('business_name')
                             if name:
                                 self.seen_names.add(name.strip().lower())
                             web = row.get('website')
                             if web:
                                 web_clean = web.strip().lower()
                                 if web_clean and web_clean not in ('', 'http://', 'https://'):
                                     self.seen_websites.add(web_clean)
                             email = row.get('business_email')
                             if email:
                                 self.seen_emails.add(email.strip().lower())
            except Exception as e:
                print(f"Warning: Could not load existing JSON leads for deduplication: {e}")

    def _init_file(self):
        """Initializes the output file. Writes the CSV header if the file does not exist or has size 0."""
        mode = 'a' if self.append else 'w'
        if self.format == 'csv':
            # File is populated only if it exists and has content (size > 0)
            file_exists = os.path.isfile(self.filepath) and os.path.getsize(self.filepath) > 0
            with open(self.filepath, mode, newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames)
                if not file_exists or not self.append:
                    writer.writeheader()
        elif self.format == 'json':
            file_exists = os.path.isfile(self.filepath) and os.path.getsize(self.filepath) > 0
            if not file_exists or not self.append:
                with open(self.filepath, 'w', encoding='utf-8') as f:
                    json.dump([], f)
                    
    def write(self, results):
        for res in results:
            self.append_result(res)
            
    def append_result(self, result):
        """Appends a new business lead to the database if it is not a duplicate."""
        if 'source_url' in result and self.has_url(result['source_url']):
            return False
            
        name = result.get('business_name')
        website = result.get('website')
        if self.has_business(name, website):
            return False
            
        result['scraped_at'] = datetime.now().isoformat()
        
        if self.format == 'csv':
            with open(self.filepath, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames)
                filtered_result = {k: v for k, v in result.items() if k in self.fieldnames}
                writer.writerow(filtered_result)
        elif self.format == 'json':
            data = []
            if os.path.isfile(self.filepath) and os.path.getsize(self.filepath) > 0:
                try:
                    with open(self.filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    data = []
            data.append(result)
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                
        # Register in our session caches to prevent duplicate insertion
        if 'source_url' in result:
            self.seen_urls.add(result['source_url'])
        if name:
            self.seen_names.add(name.strip().lower())
        if website:
            web_clean = website.strip().lower()
            if web_clean and web_clean not in ('', 'http://', 'https://'):
                self.seen_websites.add(web_clean)
        email = result.get('business_email')
        if email:
            self.seen_emails.add(email.strip().lower())
        return True

    def has_url(self, url):
        return url in self.seen_urls

    def has_business(self, name, website=None):
        """Checks if the business name or website has already been scraped/stored."""
        if name:
            if name.strip().lower() in self.seen_names:
                return True
        if website:
            web_lower = website.strip().lower()
            if web_lower and web_lower not in ('', 'http://', 'https://'):
                if web_lower in self.seen_websites:
                    return True
        return False
