import logging
import urllib.parse
from functools import wraps
import time

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

def retry(retries=3, delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == retries - 1:
                        raise e
                    time.sleep(delay)
        return wrapper
    return decorator

def url_encode(query):
    return urllib.parse.quote_plus(query)

def is_captcha_detected(html_content):
    html_lower = html_content.lower()
    return (
        "unusual traffic" in html_lower or 
        "g-recaptcha" in html_lower or 
        "prove you're not a robot" in html_lower or
        "demuestra que no eres un robot" in html_lower
    )
