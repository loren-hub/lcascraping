import csv
import logging
import os
import resend
from datetime import datetime
from config import Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_template_info(query, config):
    templates = config.get('email_outreach.templates', [])
    for t in templates:
        if t.get('keyword', '').lower() in query.lower() and t.get('keyword') != 'default':
            return t
    
    # Fallback to default
    for t in templates:
        if t.get('keyword') == 'default':
            return t
            
    return None

def load_html_template(template_name):
    # Base path of templates/
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, 'templates', f'{template_name}.html')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return None

async def run_email_outreach(filepath, config, dry_run=False):
    # Initialize resend API Key
    resend.api_key = os.getenv('RESEND_API_KEY')
    
    if not resend.api_key and not dry_run:
        logging.error("RESEND_API_KEY environment variable is not set. Emails will not be sent.")
        return

    sender_email = config.get('email_outreach.sender_email')
    if not sender_email:
        logging.error("email_outreach.sender_email is not configured in config.yaml.")
        return

    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            expected_fieldnames = ['business_name', 'business_email', 'phone', 'website', 'address', 'search_query', 'scraped_at', 'email_sent_at']
            reader = csv.DictReader(f, fieldnames=expected_fieldnames)
            
            rows = []
            for row in reader:
                if row.get('business_name') == 'business_name':
                    continue
                # Ensure all keys exist
                for key in expected_fieldnames:
                    if row.get(key) is None:
                        row[key] = ''
                rows.append(row)
                
    except FileNotFoundError:
        logging.error(f"Could not find {filepath}.")
        return

    logging.info(f"Starting Stage 3: Email Outreach for {len(rows)} businesses. (Dry Run: {dry_run})")
    
    emails_sent = 0
    for row in rows:
        email = row.get('business_email', '').strip()
        sent_at = row.get('email_sent_at', '').strip()
        
        if not email or sent_at:
            continue
            
        business_name = row.get('business_name', '')
        query = row.get('search_query', '')
        
        template_info = get_template_info(query, config)
        if not template_info:
            logging.warning(f"No template mapped for query: {query}")
            continue
            
        template_name = template_info.get('template_name')
        subject = template_info.get('subject', 'Hello')
        
        html_content = load_html_template(template_name)
        if not html_content:
            logging.error(f"Could not load HTML template for {template_name}")
            continue
            
        # Inject variables
        html_content = html_content.replace('{{business_name}}', business_name)
        
        if dry_run:
            logging.info(f"[DRY RUN] Would send email to {email} using template '{template_name}'")
            logging.info(f"[DRY RUN] Subject: {subject}")
        else:
            try:
                params = {
                    "from": sender_email,
                    "to": [email],
                    "subject": subject,
                    "html": html_content
                }
                
                response = resend.Emails.send(params)
                logging.info(f"--> Sent email to {email}: {response}")
                
                row['email_sent_at'] = datetime.now().isoformat()
                emails_sent += 1
            except Exception as e:
                logging.error(f"Failed to send email to {email}: {e}")

    # Write back only if not dry run and we actually sent something
    if not dry_run and emails_sent > 0:
        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=expected_fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            
        logging.info(f"Done! Pipeline fully completed. Updated results saved to {filepath}")
    else:
        logging.info(f"Finished email outreach. Emails sent: {emails_sent}")
