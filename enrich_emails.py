#!/usr/bin/env python3
"""
LCA Scraping: Stage 2 Deep Email enrichment crawler
This script executes the website crawler to find contact emails for the leads
previously saved in results.csv.
"""

import argparse
import asyncio
import logging
import sys
from config import Config
from email_extractor import run_email_enrichment
from utils import setup_logging

async def run_email_extraction(output=None):
    """
    Orchestrates the Stage 2 email extraction flow.
    Loads configurations and calls the website crawl process.
    """
    logger = logging.getLogger(__name__)
    
    # Load configuration
    config = Config()
    
    # Determine which file to process
    filepath = output or config.get('output.filename', 'results.csv')
    
    logger.info(f"Starting Stage 2: Email Enrichment on leads file '{filepath}'")
    await run_email_enrichment(filepath)
    logger.info("Stage 2 (Email Enrichment) completed.")

def main():
    """
    Entry point for CLI execution.
    Example usage: python3 enrich_emails.py --output results.csv
    """
    setup_logging()
    
    parser = argparse.ArgumentParser(description='Stage 2: Deep Website Email Extractor')
    parser.add_argument('--output', help='Path to the lead file (CSV) containing businesses to crawl')
    args = parser.parse_args()
    
    try:
        asyncio.run(run_email_extraction(output=args.output))
    except KeyboardInterrupt:
        print("\nProcess interrupted by user. Exiting safely.")
        sys.exit(0)

if __name__ == '__main__':
    main()
