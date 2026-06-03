#!/usr/bin/env python3
"""
LCA Scraping: Stage 1 Google Maps Lead Extractor
This script executes the Google Maps scraping pipeline independently.
It searches for businesses, extracts details (name, phone, website, address),
and appends them to a CSV/JSON file.
"""

import argparse
import asyncio
import logging
import sys
from config import Config
from browser_manager import BrowserManager
from data_store import DataStore
from search_flow import SearchFlow
from utils import setup_logging

async def run_lead_scraping(queries=None, output=None, file_format=None, headless=None, max_results=None, scroll_steps=None):
    """
    Orchestrates the Stage 1 Google Maps scraping flow.
    Loads configurations, applies optional command line overrides, launches
    the stealth browser, and appends extracted businesses to data persistence.
    """
    logger = logging.getLogger(__name__)
    
    # Load settings from config.yaml
    config = Config()
    
    # Apply overrides if provided
    if queries:
        config.settings['search']['queries'] = queries
    if output:
        config.settings['output']['filename'] = output
    if file_format:
        config.settings['output']['format'] = file_format
    if headless is not None:
        config.settings['browser']['headless'] = headless
    if max_results is not None:
        config.settings['search']['max_results_per_query'] = max_results
    if scroll_steps is not None:
        config.settings['search']['scroll_steps_limit'] = scroll_steps
        
    filepath = config.get('output.filename', 'results.csv')
    fmt = config.get('output.format', 'csv')
    
    # Setup data store (always using append mode)
    data_store = DataStore(
        filepath=filepath,
        format=fmt,
        append=True
    )
    
    logger.info(f"Starting Stage 1: Google Maps Extraction. Output: {filepath} ({fmt})")
    
    # Start the browser (Chrome) using stealth anti-detection setup
    browser_manager = BrowserManager(config)
    page = await browser_manager.create_page()
    
    # Initialize the scraping flow
    flow = SearchFlow(page, config, data_store)
    
    # Run the search for every query in the configuration or overrides
    search_queries = config.get('search.queries', [])
    logger.info(f"Processing queries: {search_queries}")
    
    for query in search_queries:
        try:
            logger.info(f"Scraping query: '{query}'")
            await flow.process_search_query(query)
        except Exception as e:
            logger.error(f"Error processing query '{query}': {e}", exc_info=True)
        
    # Clean up and close the browser
    await browser_manager.close()
    logger.info("Stage 1 (Google Maps Extraction) completed.")

def main():
    """
    Entry point for CLI execution.
    Example usage: python3 scrape_leads.py --queries "dentista en madrid" --max-results 5
    """
    setup_logging()
    
    parser = argparse.ArgumentParser(description='Stage 1: Google Maps Lead Extraper')
    
    # CLI Overrides
    parser.add_argument('--queries', nargs='+', help='Override the search queries')
    parser.add_argument('--output', help='Override the output filename')
    parser.add_argument('--format', choices=['csv', 'json'], help='Override the output format')
    
    # Headless mode toggle
    parser.add_argument('--headless', action='store_true', help='Run without a browser window')
    parser.add_argument('--no-headless', action='store_false', dest='headless', help='Run with a browser window')
    parser.set_defaults(headless=None)
    
    parser.add_argument('--max-results', type=int, help='Override max results per query')
    parser.add_argument('--scroll-steps', type=int, help='Override max scroll steps')
    
    args = parser.parse_args()
    
    try:
        asyncio.run(run_lead_scraping(
            queries=args.queries,
            output=args.output,
            file_format=args.format,
            headless=args.headless,
            max_results=args.max_results,
            scroll_steps=args.scroll_steps
        ))
    except KeyboardInterrupt:
        print("\nProcess interrupted by user. Exiting safely.")
        sys.exit(0)

if __name__ == '__main__':
    main()
