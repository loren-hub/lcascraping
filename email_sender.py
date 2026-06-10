import csv
import logging
import os
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

async def run_email_outreach(filepath, config, dry_run=False):
    """
    Orchestrates Stage 3: Email Outreach.
    
    This function reads scraped businesses from a CSV file, selects the target audience 
    (those with valid emails that haven't been contacted yet), maps and loads the 
    appropriate email template based on their search query, interpolates variables 
    (e.g., business name), and sends the email via the Resend API.
    
    It maintains idempotency by recording the timestamp ('email_sent_at') in the CSV file
    only when emails are successfully dispatched in live mode.
    
    Args:
        filepath (str): Path to the CSV file containing the scraped leads.
        config (Config): The configuration manager instance.
        dry_run (bool): If True, logs the outreach action without sending real emails or writing to CSV.
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

    # 2. Load and parse the leads CSV file
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            # Expected headers matching the schema from previous stages
            expected_fieldnames = ['business_name', 'business_email', 'phone', 'website', 'address', 'search_query', 'scraped_at', 'email_sent_at']
            reader = csv.DictReader(f, fieldnames=expected_fieldnames)
            
            rows = []
            for row in reader:
                # Skip the CSV header row if it is duplicated or read as data
                if row.get('business_name') == 'business_name':
                    continue
                # Ensure all dictionary keys are populated to avoid KeyErrors
                for key in expected_fieldnames:
                    if row.get(key) is None:
                        row[key] = ''
                rows.append(row)
                
    except FileNotFoundError:
        logging.error(f"Could not find lead file at {filepath}.")
        return

    logging.info(f"Starting Stage 3: Email Outreach for {len(rows)} businesses. (Dry Run: {dry_run})")
    
    emails_sent = 0
    # 3. Process each lead and send personalized emails
    for row in rows:
        email = row.get('business_email', '').strip()
        sent_at = row.get('email_sent_at', '').strip()
        
        # Skip leads that do not have an extracted email, or have already received an email
        if not email or sent_at:
            continue
            
        business_name = row.get('business_name', '')
        query = row.get('search_query', '')
        
        # Retrieve the global template configuration
        template_filename = config.get('email_outreach.template_filename', 'template.html')
        subject = config.get('email_outreach.subject', 'Propuesta de colaboración')
        
        # Load the HTML template string
        html_content = load_html_template(template_filename)
        if not html_content:
            logging.error(f"Could not load HTML template for: '{template_filename}'")
            continue
            
        # Personalize template by replacing template variables
        # Note: Feel free to expand variable injections here (e.g. {{website}}, {{phone}})
        html_content = html_content.replace('{{business_name}}', business_name)
        
        # 4. Handle sending behavior based on Dry Run toggle
        if dry_run:
            logging.info(f"[DRY RUN] Would send email to: {email} using template '{template_name}'")
            logging.info(f"[DRY RUN] Subject: {subject}")
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
                
                # Mark current timestamp to prevent duplicate sending on rerun
                row['email_sent_at'] = datetime.now().isoformat()
                emails_sent += 1
            except Exception as e:
                logging.error(f"Failed to send email to {email}: {e}")

    # 5. Persist progress: Save updated rows back to CSV only if live emails were sent
    if not dry_run and emails_sent > 0:
        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=expected_fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            
        logging.info(f"Done! Pipeline fully completed. Updated results saved to {filepath}")
    else:
        logging.info(f"Finished email outreach. Emails sent: {emails_sent}")
