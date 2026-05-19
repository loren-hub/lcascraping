import argparse
import asyncio
import logging
from config import Config
from browser_manager import BrowserManager
from data_store import DataStore
from search_flow import SearchFlow
from utils import setup_logging

async def run_scraper(args):
    """
    Main orchestration function. It:
    1. Loads the base configuration from config.yaml
    2. Overrides it with any command-line arguments you provide
    3. Initializes the browser and data storage
    4. Loops through each query to start the scraping process
    """
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Load settings from config.yaml
    config = Config()
    
    # --- APPLY COMMAND-LINE OVERRIDES ---
    # These will take priority over what's written in config.yaml
    if args.queries:
        config.settings['search']['queries'] = args.queries
    if args.output:
        config.settings['output']['filename'] = args.output
    if args.format:
        config.settings['output']['format'] = args.format
    if args.headless is not None:
        config.settings['browser']['headless'] = args.headless
    if args.max_results:
        config.settings['search']['max_results_per_query'] = args.max_results
    if args.scroll_steps:
        config.settings['search']['scroll_steps_limit'] = args.scroll_steps
        
    # Check if we should only run the email stage
    if args.email_only:
        from email_sender import run_email_outreach
        print("Skipping Stage 1 & Stage 2 as --email-only is set.")
        await run_email_outreach(config.get('output.filename', 'results.csv'), config, dry_run=args.dry_run)
        return
        
    # Setup where and how the data will be saved
    data_store = DataStore(
        filepath=config.get('output.filename', 'results.csv'),
        format=config.get('output.format', 'csv')
    )
    
    # Start the browser (Chrome)
    browser_manager = BrowserManager(config)
    page = await browser_manager.create_page()
    
    # Initialize the scraping flow
    flow = SearchFlow(page, config, data_store)
    
    # Run the search for every query in the list
    queries = config.get('search.queries', [])
    for query in queries:
        try:
            await flow.process_search_query(query)
        except Exception as e:
            logger.error(f"Error processing query '{query}': {e}")
        
    # Clean up and close browser
    await browser_manager.close()
    print("Stage 1 (Google Maps Extraction) completed.")
    
    # Run Stage 2: Email enrichment
    from email_extractor import run_email_enrichment
    await run_email_enrichment(config.get('output.filename', 'results.csv'))
    print("Stage 2 completed.")
    
    # Run Stage 3: Email outreach
    if args.send_emails or config.get('email_outreach.enabled', False):
        from email_sender import run_email_outreach
        await run_email_outreach(config.get('output.filename', 'results.csv'), config, dry_run=args.dry_run)
        print("Stage 3 completed.")
        
    print("Pipeline finished successfully.")

def main():
    """
    Entry point that parses command-line flags.
    Example usage: python3 main.py --queries "Pizza in London" --max-results 5
    """
    parser = argparse.ArgumentParser(description='Google Maps Web Scraper')
    
    # --- COMMAND LINE ARGUMENTS ---
    parser.add_argument('--queries', nargs='+', help='Override the search queries')
    parser.add_argument('--output', help='Override the output filename')
    parser.add_argument('--format', choices=['csv', 'json'], help='Override the output format')
    
    # Headless mode toggle
    parser.add_argument('--headless', action='store_true', help='Run without a browser window')
    parser.add_argument('--no-headless', action='store_false', dest='headless', help='Run with a browser window')
    parser.set_defaults(headless=None)
    
    parser.add_argument('--max-results', type=int, help='Override max results per query')
    parser.add_argument('--scroll-steps', type=int, help='Override max scroll steps')
    
    # Email Outreach arguments
    parser.add_argument('--send-emails', action='store_true', help='Enable sending emails (Stage 3)')
    parser.add_argument('--email-only', action='store_true', help='Run ONLY the email sending stage (Skip Stage 1 & 2)')
    parser.add_argument('--dry-run', action='store_true', help='Run email stage without actually sending')
    
    args = parser.parse_args()
    
    # Start the asynchronous event loop
    asyncio.run(run_scraper(args))

if __name__ == '__main__':
    main()
