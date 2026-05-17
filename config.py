import yaml
import os

class Config:
    def __init__(self, config_path='config.yaml'):
        with open(config_path, 'r') as f:
            self.settings = yaml.safe_load(f)
            
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
