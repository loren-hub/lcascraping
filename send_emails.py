#!/usr/bin/env python3
"""
LCA Scraping: Stage 3 Email Outreach CLI
This script runs the automated email outreach process independently.
It reads scraped and enriched business leads from a CSV/JSON file,
matches search queries to corresponding email templates, and sends
personalized emails using the Resend API.
"""

import argparse
import asyncio
import logging
import sys
from config import Config
from email_sender import run_email_outreach

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

async def main_async():
    setup_logging()
    
    # Parse CLI flags
    parser = argparse.ArgumentParser(description='LCA Scraping: Standalone Email Outreach CLI')
    parser.add_argument(
        '--output', 
        help='Path to the lead file (CSV) containing enriched business contacts'
    )
    parser.add_argument(
        '--dry-run', 
        action='store_true', 
        help='Simulate template loading and matching without sending real emails or writing to file'
    )
    args = parser.parse_args()
    
    # Load configuration
    config = Config()
    
    # Determine lead filepath
    # CLI argument has highest priority, otherwise falls back to config.yaml value, then 'results.csv'
    filepath = args.output or config.get('output.filename', 'results.csv')
    
    # Dispatch email outreach
    await run_email_outreach(filepath, config, dry_run=args.dry_run)

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nProcess interrupted by user. Exiting safely.")
        sys.exit(0)

if __name__ == '__main__':
    main()
