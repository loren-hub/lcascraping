#!/usr/bin/env python3
"""
LCA Scraping: Lead Data Sanitizer
This script runs a sanitization process over the results CSV file to:
1. Strip null bytes, control characters, and normalize whitespaces.
2. Filter out corporate franchise networks and chain domains using configuration blocklists.
3. Deduplicate leads by name, website domain, and email address to avoid redundant rows.
"""

import argparse
import csv
import logging
import os
import sys
from urllib.parse import urlparse
from config import Config
from utils import setup_logging

def clean_text(val):
    """
    Cleans character sequences, null bytes, double spaces, and strips whitespace.
    Preserves valid European letters and Spanish accented characters.
    """
    if not val:
        return ""
    val = str(val)
    # Remove null bytes
    val = val.replace('\x00', '')
    
    # Remove non-printable control characters (0-31, 127, and Latin-1 control 128-159)
    # but keep standard formatting whitespace like tabs and newlines
    cleaned = []
    for ch in val:
        code = ord(ch)
        if ch in ('\n', '\r', '\t') or (32 <= code <= 126) or (code > 159):
            cleaned.append(ch)
    val = "".join(cleaned)
    
    # Normalize double spaces to a single space
    val = " ".join(val.split())
    return val.strip()

def is_franchise(name, website, name_blocklist, domain_blocklist):
    """
    Scans the name and website domain against franchise/chain blocklists.
    """
    name_lower = (name or '').lower()
    for kw in name_blocklist:
        if kw and kw in name_lower:
            return True
            
    if website:
        try:
            domain = urlparse(website).netloc.lower()
            for blocked in domain_blocklist:
                if blocked and blocked in domain:
                    return True
        except Exception:
            pass
            
    return False

def sanitize_file(input_filepath, output_filepath=None):
    """
    Reads the target CSV, filters duplicates & franchises, cleans text, and saves it.
    """
    logger = logging.getLogger(__name__)
    
    if not output_filepath:
        output_filepath = input_filepath
        
    if not os.path.isfile(input_filepath) or os.path.getsize(input_filepath) == 0:
        logger.error(f"Target file '{input_filepath}' does not exist or is empty. Skipping sanitization.")
        return False
        
    # Load configuration rules and blocklists
    config = Config()
    name_blocklist = [kw.lower() for kw in config.get('filtering.franchise_blocklist', [])]
    domain_blocklist = [d.lower() for d in config.get('filtering.domain_blocklist', [])]
    
    BASE_FIELDNAMES = ['business_name', 'business_email', 'phone', 'website', 'address', 'search_query', 'scraped_at', 'email_sent_at']
    rows = []
    fieldnames = list(BASE_FIELDNAMES)
    
    try:
        with open(input_filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                fieldnames = list(reader.fieldnames)
                for b in BASE_FIELDNAMES:
                    if b not in fieldnames:
                        fieldnames.append(b)

            for row in reader:
                # Skip duplicate headers if they accidentally got written
                if row.get('business_name') == 'business_name':
                    continue
                rows.append(dict(row))
    except Exception as e:
        logger.error(f"Failed to read CSV '{input_filepath}': {e}", exc_info=True)
        return False
        
    original_count = len(rows)
    logger.info(f"Loaded {original_count} rows from '{input_filepath}' for sanitization.")
    
    sanitized_rows = []
    seen_names = set()
    seen_websites = set()
    seen_emails = set()
    
    dropped_duplicates = 0
    dropped_franchises = 0
    cleaned_chars = 0
    
    for row in rows:
        # 1. Clean odd characters from every cell preserving all columns
        cleaned_row = {}
        had_char_change = False
        for k in fieldnames:
            orig = row.get(k, '')
            cleaned = clean_text(orig)
            if cleaned != orig:
                had_char_change = True
            cleaned_row[k] = cleaned
            
        if had_char_change:
            cleaned_chars += 1
            
        name = cleaned_row.get('business_name', '')
        email = cleaned_row.get('business_email', '')
        website = cleaned_row.get('website', '')
        
        # 2. Franchise Filter
        if is_franchise(name, website, name_blocklist, domain_blocklist):
            dropped_franchises += 1
            logger.info(f"Pruned franchise: '{name}'")
            continue
            
        # 3. Deduplication (By Name, Website domain, or Email address)
        name_key = name.lower()
        if name_key and name_key in seen_names:
            dropped_duplicates += 1
            logger.info(f"Pruned duplicate business name: '{name}'")
            continue
            
        web_key = website.lower()
        if web_key and web_key not in ('', 'http://', 'https://'):
            if web_key in seen_websites:
                dropped_duplicates += 1
                logger.info(f"Pruned duplicate website: '{website}' for business '{name}'")
                continue
                
        email_key = email.lower()
        if email_key:
            if email_key in seen_emails:
                dropped_duplicates += 1
                logger.info(f"Pruned duplicate email: '{email}' for business '{name}'")
                continue
                
        # Register values to seen sets
        if name_key:
            seen_names.add(name_key)
        if web_key and web_key not in ('', 'http://', 'https://'):
            seen_websites.add(web_key)
        if email_key:
            seen_emails.add(email_key)
            
        sanitized_rows.append(cleaned_row)
        
    logger.info("Sanitization metrics:")
    logger.info(f"  - Initial leads count: {original_count}")
    logger.info(f"  - Records cleaned of odd characters: {cleaned_chars}")
    logger.info(f"  - Duplicates pruned: {dropped_duplicates}")
    logger.info(f"  - Franchises pruned: {dropped_franchises}")
    logger.info(f"  - Final clean leads: {len(sanitized_rows)}")
    
    # Save clean data back to CSV atomically
    temp_filepath = f"{output_filepath}.tmp"
    try:
        with open(temp_filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            writer.writerows(sanitized_rows)
        os.replace(temp_filepath, output_filepath)
        logger.info(f"Sanitized results successfully written to '{output_filepath}'")
        return True
    except Exception as e:
        logger.error(f"Failed to write sanitized CSV '{output_filepath}': {e}", exc_info=True)
        if os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except OSError:
                pass
        return False

def main():
    """
    CLI execution wrapper.
    """
    setup_logging()
    
    parser = argparse.ArgumentParser(description='Sanitize leads CSV files')
    parser.add_argument('--input', help='Target file to read (defaults to results.csv)')
    parser.add_argument('--output', help='File to write (defaults to overwrite input)')
    args = parser.parse_args()
    
    config = Config()
    input_file = args.input or config.get('output.filename', 'results.csv')
    output_file = args.output or input_file
    
    success = sanitize_file(input_file, output_file)
    if not success:
        sys.exit(1)

if __name__ == '__main__':
    main()
