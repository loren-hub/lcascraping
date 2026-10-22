import asyncio
import csv
import logging
import os
import random
import resend
from datetime import datetime
from config import Config

# Configure logging format and level
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def load_html_template(template_name):
    """
    Loads the contents of an HTML template file from the root directory.
    
    Args:
        template_name (str): The filename of the template (including the .html extension).
        
    Returns:
        str or None: The HTML template string if found, otherwise None.
    """
    # Locate the absolute root directory relative to this script
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, template_name)
    
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
            
    return None

BASE_FIELDNAMES = [
    'business_name',
    'business_email',
    'phone',
    'website',
    'address',
    'search_query',
    'scraped_at',
    'email_sent_at'
]


def save_leads_atomic(filepath, fieldnames, rows):
    """
    Persists updated lead rows to CSV atomically using a temporary file
    and atomic replacement, safeguarding against corruption upon interruption.
    """
    temp_filepath = f"{filepath}.tmp"
    try:
        with open(temp_filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_filepath, filepath)
        return True
    except Exception as e:
        logging.error(f"Error saving incremental progress to '{filepath}': {e}", exc_info=True)
        if os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except OSError:
                pass
        return False


async def run_email_outreach(filepath, config, dry_run=False, limit=None):
    """
    Orchestrates Stage 3: Email Outreach.
    
    This function reads scraped businesses from a CSV file, selects the target audience 
    (those with valid emails that haven't been contacted yet), maps and loads the 
    appropriate email template based on their search query, interpolates variables 
    (e.g., business name), and sends the email via the Resend API.
    
    It maintains idempotency by recording the timestamp ('email_sent_at') in the CSV file
    incrementally and atomically when emails are successfully dispatched in live mode.
    
    Args:
        filepath (str): Path to the CSV file containing the scraped leads.
        config (Config): The configuration manager instance.
        dry_run (bool): If True, logs the outreach action without sending real emails or writing to CSV.
        limit (int, optional): Maximum number of emails to send in this execution.
    """
    # 1. Initialize Resend API client using the environment variable
    resend.api_key = os.getenv('RESEND_API_KEY')
    
    # Enforce API key check unless running in dry-run mode
    if not resend.api_key and not dry_run:
        logging.error("RESEND_API_KEY environment variable is not set. Emails will not be sent.")
        return

    # Fetch the verified sender email address from config
    sender_email = config.get('email_outreach.sender_email')
    if not sender_email:
        logging.error("email_outreach.sender_email is not configured in config.yaml.")
        return

    # 2. Load and parse the leads CSV file preserving all existing headers dynamically
    if not os.path.isfile(filepath):
        logging.error(f"Could not find lead file at {filepath}.")
        return

    rows = []
    fieldnames = list(BASE_FIELDNAMES)
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                fieldnames = list(reader.fieldnames)
                for b in BASE_FIELDNAMES:
                    if b not in fieldnames:
                        fieldnames.append(b)

            for row in reader:
                # Skip duplicate header line if accidentally present
                if row.get('business_name') == 'business_name':
                    continue
                # Ensure all fieldnames exist in each row dict
                for col in fieldnames:
                    if col not in row or row[col] is None:
                        row[col] = ''
                rows.append(dict(row))
    except Exception as e:
        logging.error(f"Failed to read CSV '{filepath}': {e}", exc_info=True)
        return

    limit_str = f", Limit: {limit}" if limit is not None else ""
    logging.info(f"Starting Stage 3: Email Outreach for {len(rows)} businesses. (Dry Run: {dry_run}{limit_str})")
    
    emails_sent = 0
    # 3. Process each lead and send personalized emails
    for row in rows:
        email = row.get('business_email', '').strip()
        sent_at = row.get('email_sent_at', '').strip()
        
        # Skip leads that do not have an extracted email, or have already received an email
        if not email or sent_at:
            continue
            
        # Stop if limit is reached
        if limit is not None and emails_sent >= limit:
            logging.info(f"Reached sending limit of {limit} email(s). Stopping outreach.")
            break

        # Delay between emails to simulate human timing (only if not the first email sent in this execution)
        if emails_sent > 0:
            delay_config = config.get('email_outreach.delay_between_emails', {})
            min_delay = delay_config.get('min', 5.0)
            max_delay = delay_config.get('max', 15.0)
            sleep_time = random.uniform(min_delay, max_delay)
            if dry_run:
                logging.info(f"[DRY RUN] Would delay for {sleep_time:.2f} seconds before next email.")
            else:
                logging.info(f"Sleeping for {sleep_time:.2f} seconds to simulate human timing...")
                await asyncio.sleep(sleep_time)
            
        business_name = row.get('business_name', '')
        
        # Retrieve the global template configuration
        template_filename = config.get('email_outreach.template_filename', 'template.html')
        subject = config.get('email_outreach.subject', 'Campaña informativa LCA')
        
        # Load the HTML template string
        html_content = load_html_template(template_filename)
        if not html_content:
            logging.error(f"Could not load HTML template for: '{template_filename}'")
            continue
            
        # Personalize template by replacing template variables
        html_content = html_content.replace('{{business_name}}', business_name)
        
        # 4. Handle sending behavior based on Dry Run toggle
        if dry_run:
            logging.info(f"[DRY RUN] Would send email to: {email} using template '{template_filename}'")
            logging.info(f"[DRY RUN] Subject: {subject}")
            emails_sent += 1
        else:
            try:
                # Prepare payload parameters for Resend API
                params = {
                    "from": sender_email,
                    "to": [email],
                    "subject": subject,
                    "html": html_content
                }
                
                # Dispatch the email through the Resend client
                response = resend.Emails.send(params)
                logging.info(f"--> Sent email to {email}: {response}")
                
                # Mark current timestamp and persist immediately to prevent duplicate sending
                row['email_sent_at'] = datetime.now().isoformat()
                emails_sent += 1
                save_leads_atomic(filepath, fieldnames, rows)
            except Exception as e:
                logging.error(f"Failed to send email to {email}: {e}")

    logging.info(f"Finished email outreach. Emails sent: {emails_sent}")

