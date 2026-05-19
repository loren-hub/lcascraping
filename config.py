import yaml
import os
from dotenv import load_dotenv

class Config:
    def __init__(self, config_path='config.yaml', blocklist_path='blocklist.yaml'):
        load_dotenv()
        with open(config_path, 'r') as f:
            self.settings = yaml.safe_load(f)
            
        # Dynamically load blocklists if the blocklist file exists
        if os.path.exists(blocklist_path):
            try:
                with open(blocklist_path, 'r') as f:
                    blocklist_data = yaml.safe_load(f)
                    if isinstance(blocklist_data, dict):
                        if 'filtering' not in self.settings:
                            self.settings['filtering'] = {}
                        # Merge blocklist properties into the filtering dictionary
                        for k, v in blocklist_data.items():
                            self.settings['filtering'][k] = v
            except Exception as e:
                print(f"Warning: Could not load blocklist from {blocklist_path}: {e}")
            
        # Optional env var overrides
        if os.getenv('MAX_RESULTS'):
            self.settings['search']['max_results_per_query'] = int(os.getenv('MAX_RESULTS'))
        if os.getenv('HEADLESS'):
            self.settings['browser']['headless'] = os.getenv('HEADLESS').lower() == 'true'

    def get(self, key, default=None):
        keys = key.split('.')
        val = self.settings
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val
