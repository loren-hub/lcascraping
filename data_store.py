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
        self.fieldnames = ['business_name', 'business_email', 'phone', 'website', 'address', 'search_query', 'scraped_at']
        
        self._init_file()
        
    def _init_file(self):
        mode = 'a' if self.append else 'w'
        if self.format == 'csv':
            file_exists = os.path.isfile(self.filepath)
            with open(self.filepath, mode, newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames)
                if not file_exists or not self.append:
                    writer.writeheader()
        elif self.format == 'json':
            if not os.path.isfile(self.filepath) or not self.append:
                with open(self.filepath, 'w', encoding='utf-8') as f:
                    json.dump([], f)
                    
    def write(self, results):
        for res in results:
            self.append_result(res)
            
    def append_result(self, result):
        if 'source_url' in result and self.has_url(result['source_url']):
            return False
            
        result['scraped_at'] = datetime.now().isoformat()
        
        if self.format == 'csv':
            with open(self.filepath, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames)
                filtered_result = {k: v for k, v in result.items() if k in self.fieldnames}
                writer.writerow(filtered_result)
        elif self.format == 'json':
            data = []
            if os.path.isfile(self.filepath):
                try:
                    with open(self.filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    data = []
            data.append(result)
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                
        if 'source_url' in result:
            self.seen_urls.add(result['source_url'])
        return True

    def has_url(self, url):
        return url in self.seen_urls
