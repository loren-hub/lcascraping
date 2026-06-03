import argparse
import asyncio
import logging
import sys
from utils import setup_logging
from config import Config
from scrape_leads import run_lead_scraping
from enrich_emails import run_email_extraction
from sanitize_results import sanitize_file

async def run_scraper(args):
    """
    Main orchestration function. It:
    1. Loads the base configuration to resolve target file.
    2. Runs Stage 1 (Google Maps Lead Scraping).
    3. Runs Stage 2 (Deep Website Email Crawling).
    4. Runs Sanitization (Cleanup franchise networks, odd characters, and duplicates).
    """
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Load configuration to fetch the target filename
    config = Config()
    filepath = args.output or config.get('output.filename', 'results.csv')
    
    logger.info("==================================================")
    logger.info("Starting Scraper & Enrichment Orchestrator (main.py)")
    logger.info("==================================================")
    
    # Run Stage 1: Google Maps Lead Scraping
    await run_lead_scraping(
        queries=args.queries,
        output=args.output,
        file_format=args.format,
        headless=args.headless,
        max_results=args.max_results,
        scroll_steps=args.scroll_steps
    )
    print("Stage 1 (Google Maps Extraction) completed.")
    
    # Run Stage 2: Email enrichment
    await run_email_extraction(output=filepath)
    print("Stage 2 completed.")
    
    # Run Sanitization Pass
    logger.info(f"Running data sanitization pass on '{filepath}'...")
    sanitize_file(filepath)
    print("Sanitization pass completed.")
    
    print("Pipeline finished successfully.")

def main():
    """
    Entry point that parses command-line flags.
    Example usage: python3 main.py --queries "Pizza in London" --max-results 5
    """
    parser = argparse.ArgumentParser(description='Google Maps Web Scraper Orchestrator')
    
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
    
    args = parser.parse_args()
    
    # Start the asynchronous event loop
    try:
        asyncio.run(run_scraper(args))
    except KeyboardInterrupt:
        print("\nPipeline interrupted by user. Exiting safely.")
        sys.exit(0)

if __name__ == '__main__':
    main()
