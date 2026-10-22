#!/usr/bin/env python3
"""
LCA Scraping: Have I Been Pwned (HIBP) Breach Verification CLI
================================================================

This script independently checks business contact emails from results.csv 
against Have I Been Pwned (HIBP) using Playwright web automation to verify 
if any email has been compromised in known data breaches.

RESPONSIBILITY & ETHICAL USAGE NOTICE:
---------------------------------------
These are third-party business contact emails obtained through automated scraping.
HIBP is a security intelligence service not designed for unmoderated mass queries.
To adhere to reasonable usage practices and avoid operational bans:
1. Volumetric throttling: Enforce long, randomized delays (minutes, not seconds).
2. Stealth & Emulation: Mimic human browsing with curved mouse tracks, human typing,
   and persistent session storage (storage_state).
3. Cloudflare Turnstile awareness: Uses a visible browser (headless=False) by default
   to allow automatic challenge resolution, with a clean interactive manual fallback.
4. Internal usage only: Extracted breach intelligence is strictly for internal lead
   qualification and scoring, and should NEVER be directly exposed or mentioned
   in unsolicited cold outreach campaigns.

CLI Examples:
-------------
python3 check_breaches.py --output results.csv
python3 check_breaches.py --output results.csv --limit 5
python3 check_breaches.py --output results.csv --dry-run
python3 check_breaches.py --output results.csv --headless
"""

import argparse
import asyncio
import csv
import logging
import os
import random
import sys
import time
from datetime import datetime
from bs4 import BeautifulSoup

from config import Config
from browser_manager import BrowserManager
from anti_detection import (
    simulate_mouse_movement,
    type_slowly,
    random_delay,
)
from utils import setup_logging

# Required schema columns for HIBP enrichment
HIBP_FIELDNAMES = [
    'hibp_checked_at',
    'hibp_breached',
    'hibp_breach_count',
    'hibp_breach_names',
    'hibp_breach_dates',
    'hibp_compromised_data',
    'hibp_breach_descriptions'
]

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


def load_leads(filepath):
    """
    Loads leads from the CSV file.
    Ensures that existing headers are preserved and HIBP fields are appended
    if not already present in the file schema.
    
    Returns:
        tuple: (fieldnames: list, rows: list of dict)
    """
    logger = logging.getLogger(__name__)
    if not os.path.isfile(filepath):
        logger.error(f"Lead file not found at: {filepath}")
        return [], []

    rows = []
    fieldnames = list(BASE_FIELDNAMES)

    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                # Retain existing fieldnames in exact original order
                fieldnames = list(reader.fieldnames)
                # Append any missing HIBP fields to the end
                for h in HIBP_FIELDNAMES:
                    if h not in fieldnames:
                        fieldnames.append(h)
            
            for row in reader:
                # Skip duplicate header lines if accidentally inserted
                if row.get('business_name') == 'business_name':
                    continue
                # Ensure all fieldnames exist in each row dict
                for col in fieldnames:
                    if col not in row or row[col] is None:
                        row[col] = ''
                rows.append(dict(row))
    except Exception as e:
        logger.error(f"Failed to read CSV '{filepath}': {e}", exc_info=True)
        return [], []

    return fieldnames, rows


def save_leads_atomic(filepath, fieldnames, rows):
    """
    Persists updated lead rows to CSV atomically using a temporary file
    and atomic replacement, safeguarding against corruption upon interruption.
    """
    logger = logging.getLogger(__name__)
    temp_filepath = f"{filepath}.tmp"
    try:
        with open(temp_filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_filepath, filepath)
        return True
    except Exception as e:
        logger.error(f"Error saving incremental progress to '{filepath}': {e}", exc_info=True)
        if os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except OSError:
                pass
        return False


async def is_turnstile_resolved(page):
    """
    Checks if Cloudflare Turnstile has successfully resolved and injected a response token.
    """
    try:
        # Check standard Turnstile hidden response input
        locator = page.locator('input[name="cf-turnstile-response"]')
        if await locator.count() > 0:
            val = await locator.first.get_attribute('value')
            if val and len(val.strip()) > 0:
                return True
    except Exception:
        pass
    return False


async def wait_for_turnstile(page, timeout=25.0, logger=None):
    """
    Monitors Cloudflare Turnstile until resolved or timeout is reached.
    If timeout expires without resolution, activates manual fallback prompting the operator.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    logger.info("Esperando resolución de Cloudflare Turnstile...")
    start_time = time.time()
    
    # Quick polling phase
    while time.time() - start_time < timeout:
        if await is_turnstile_resolved(page):
            logger.info("Cloudflare Turnstile resuelto automáticamente con éxito.")
            return True
        
        # Subtle mouse nudge towards the widget container to stimulate interaction
        if time.time() - start_time > 3.0:
            try:
                widget = page.locator('#turnstileCheckEmailForBreaches')
                if await widget.count() > 0 and await widget.is_visible():
                    box = await widget.bounding_box()
                    if box:
                        await page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            except Exception:
                pass
                
        await asyncio.sleep(0.8)

    # If still not resolved, trigger interactive manual fallback
    logger.warning("==========================================================================")
    logger.warning("⚠️  [FALLBACK MANUAL ACTIVADO] Turnstile no se resolvió automáticamente.")
    logger.warning("   Por favor, dirígete a la ventana del navegador abierta y resuelve el")
    logger.warning("   challenge o checkbox de Cloudflare Turnstile manualmente.")
    logger.warning("==========================================================================")

    async def poll_turnstile_resolve():
        while True:
            if await is_turnstile_resolved(page):
                logger.info("Token de Turnstile detectado en el navegador.")
                return True
            await asyncio.sleep(1.0)

    async def wait_user_confirmation():
        if sys.stdin.isatty():
            try:
                await asyncio.to_thread(
                    input,
                    "\n👉 Pulsa [ENTER] en esta terminal tras resolver el Turnstile en el navegador: "
                )
                return True
            except (EOFError, OSError, KeyboardInterrupt):
                return False
        else:
            logger.info("Terminal no interactiva. Esperando resolución de Turnstile en navegador (hasta 60s)...")
            await asyncio.sleep(60.0)
            return False

    poll_task = asyncio.create_task(poll_turnstile_resolve())
    input_task = asyncio.create_task(wait_user_confirmation())

    done, pending = await asyncio.wait(
        [poll_task, input_task],
        return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()

    # Final verification after operator action
    resolved = await is_turnstile_resolved(page)
    if resolved:
        logger.info("Turnstile confirmado como resuelto.")
    else:
        logger.warning("Turnstile continúa sin token. Se procederá con intento defensivo.")
    return resolved


def parse_breach_results(html_content, logger=None):
    """
    Parses HIBP search result DOM to determine breach presence and extract complete details.
    
    Expected selectors:
      - Sin brechas: #email-result-good (result-count == "0", result-message starts with "Good news")
      - Con brechas: #email-result-bad (#breachCount, #breachCountLabel, #breachCountDescription)
      - Lista de brechas: #breachTimeline #timelineItems .timeline-item
          - Fecha: .timeline-date .timeline-date-text (ej. "Apr" + "2025" -> "Apr 2025")
          - Nombre: .timeline-title h5 (mb-0 fw-semibold text-white)
          - Descripción: .timeline-content p.mb-2 (texto plano)
          - Datos comprometidos: ul.timeline-details-list li (sin icono <i>)
          
    Returns:
        dict: Parsed breach details or None if results could not be found/parsed.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. Check for clean / no-breach result (#email-result-good)
    good_div = soup.select_one('#email-result-good')
    if good_div:
        # Check if visible (no 'd-none' class)
        good_classes = good_div.get('class', [])
        if 'd-none' not in good_classes:
            count_el = good_div.select_one('.result-count')
            count_text = count_el.get_text(strip=True) if count_el else "0"
            msg_el = good_div.select_one('.result-message')
            msg_text = msg_el.get_text(strip=True) if msg_el else ""

            if count_text == "0" or "good news" in msg_text.lower():
                return {
                    'breached': False,
                    'count': 0,
                    'names': '',
                    'dates': '',
                    'compromised_data': '',
                    'descriptions': ''
                }

    # 2. Check for breached result (#email-result-bad)
    bad_div = soup.select_one('#email-result-bad')
    if bad_div:
        bad_classes = bad_div.get('class', [])
        if 'd-none' not in bad_classes:
            count_el = bad_div.select_one('#breachCount')
            count_val = 0
            if count_el:
                txt = count_el.get_text(strip=True)
                if txt.isdigit():
                    count_val = int(txt)

            breaches = []
            timeline_items = soup.select('#timelineItems .timeline-item, #breachTimeline .timeline-item')
            
            for item in timeline_items:
                # Date (join multiple date spans e.g. "Apr" "2025")
                date_spans = item.select('.timeline-date .timeline-date-text')
                date_str = " ".join(s.get_text(strip=True) for s in date_spans if s.get_text(strip=True))

                # Name
                title_el = item.select_one('.timeline-title h5, h5')
                name_str = title_el.get_text(strip=True) if title_el else ""

                # Description (plain text without markup, normalize spaces, sanitize ';')
                desc_el = item.select_one('.timeline-content p.mb-2, p.mb-2')
                desc_str = ""
                if desc_el:
                    desc_str = " ".join(desc_el.get_text().split())
                    desc_str = desc_str.replace(';', ',')  # avoid breaking outer semicolon delimiter

                # Compromised data categories
                data_lis = item.select('ul.timeline-details-list li')
                data_types = []
                for li in data_lis:
                    # Decompose <i> dot icons before getting text
                    for icon in li.find_all('i'):
                        icon.decompose()
                    cleaned_cat = " ".join(li.get_text().split()).strip()
                    if cleaned_cat:
                        data_types.append(cleaned_cat)
                comp_data_str = ",".join(data_types)

                if name_str or date_str or comp_data_str:
                    breaches.append({
                        'name': name_str,
                        'date': date_str,
                        'compromised_data': comp_data_str,
                        'description': desc_str
                    })

            final_count = max(count_val, len(breaches))
            return {
                'breached': True,
                'count': final_count,
                'names': ";".join(b['name'] for b in breaches),
                'dates': ";".join(b['date'] for b in breaches),
                'compromised_data': ";".join(b['compromised_data'] for b in breaches),
                'descriptions': ";".join(b['description'] for b in breaches)
            }

    # Defensive check: neither container was active/visible
    logger.warning("No se pudo detectar de forma unívoca ni #email-result-good ni #email-result-bad en el DOM.")
    return None


async def verify_email_on_hibp(page, email, config, logger):
    """
    Executes the end-to-end verification of a single email address against Have I Been Pwned:
    1. Loads / reloads https://haveibeenpwned.com
    2. Enters the email into #emailInput using human typing
    3. Handles Turnstile resolution (auto or manual fallback)
    4. Clicks search submission
    5. Awaits result render and parses breach details
    """
    base_url = config.get('hibp.base_url', 'https://haveibeenpwned.com')
    turnstile_timeout = float(config.get('hibp.turnstile_timeout', 25.0))
    result_timeout = float(config.get('hibp.result_timeout', 25.0))

    logger.info(f"Navegando a HIBP para verificar: {email}")
    try:
        # Load main page
        await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1.0)
    except Exception as e:
        logger.error(f"Fallo de conexión al cargar {base_url}: {e}")
        return None

    # Ensure form exists
    form = page.locator('form#pwnedSearch')
    email_input = page.locator('#emailInput')
    if await email_input.count() == 0:
        logger.error("No se encontró el campo input#emailInput en la página de HIBP.")
        return None

    # Simulate human approach: move mouse and type slowly
    await simulate_mouse_movement(page)
    await email_input.click()
    await page.wait_for_timeout(300)
    await type_slowly(page, '#emailInput', email, config)
    await page.wait_for_timeout(500)

    # Wait for Turnstile challenge resolution
    resolved = await wait_for_turnstile(page, timeout=turnstile_timeout, logger=logger)
    if not resolved:
        logger.warning(f"Turnstile no resuelto para {email}. Procediendo con intento de envío.")

    # Submit search
    check_btn = page.locator('#checkButton, form#pwnedSearch button[type="submit"]')
    if await check_btn.count() > 0:
        logger.info("Enviando formulario de búsqueda...")
        await simulate_mouse_movement(page)
        try:
            await check_btn.first.click()
        except Exception:
            await email_input.press("Enter")
    else:
        logger.info("Enviando formulario mediante tecla Enter en #emailInput...")
        await email_input.press("Enter")

    # Await result container appearance
    logger.info("Esperando respuesta de HIBP...")
    start_wait = time.time()
    result_data = None

    while time.time() - start_wait < result_timeout:
        # Check if good or bad result block is visible
        try:
            good_visible = await page.locator('#email-result-good').is_visible()
            bad_visible = await page.locator('#email-result-bad').is_visible()
            
            if good_visible or bad_visible:
                # Brief settle delay to ensure inner items are populated
                await asyncio.sleep(0.5)
                html = await page.content()
                result_data = parse_breach_results(html, logger=logger)
                if result_data is not None:
                    break
        except Exception:
            pass

        await asyncio.sleep(1.0)

    if result_data is None:
        # Final inspection before giving up on this email
        html = await page.content()
        result_data = parse_breach_results(html, logger=logger)
        if result_data is None:
            # Check for error notice / alert on page
            soup = BeautifulSoup(html, 'html.parser')
            alert = soup.select_one('.alert, .alert-danger, .validation-summary-errors, .field-validation-error')
            if alert:
                logger.warning(f"Mensaje de validación/error detectado en HIBP: {alert.get_text(strip=True)}")

    return result_data


async def run_breach_pipeline(filepath, config, dry_run=False, limit=None, headless_override=None):
    """
    Main orchestration loop for checking HIBP breaches.
    Reads leads, filters pending emails, processes them with single-worker Playwright,
    maintains persistent session storage, and saves results incrementally to CSV.
    """
    logger = logging.getLogger(__name__)
    
    # Resolve configuration settings
    storage_state_file = config.get('hibp.storage_state_file', 'hibp_state.json')
    delay_min = float(config.get('hibp.delay_min_seconds', 120.0))
    delay_max = float(config.get('hibp.delay_max_seconds', 300.0))
    
    # Headless decision: default is False unless overridden
    headless = headless_override if headless_override is not None else config.get('hibp.headless', False)

    logger.info("==========================================================================")
    logger.info("🚀 Iniciando verificación de brechas HIBP (Have I Been Pwned)")
    logger.info(f"   - Archivo destino: {filepath}")
    logger.info(f"   - Modo headless: {headless}")
    logger.info(f"   - Dry-run: {dry_run}")
    logger.info(f"   - Límite de emails: {limit if limit is not None else 'Sin límite'}")
    logger.info(f"   - Rango de pausas: {delay_min}s - {delay_max}s entre emails")
    logger.info(f"   - Sesión persistente: {storage_state_file}")
    logger.info("==========================================================================")

    fieldnames, rows = load_leads(filepath)
    if not rows:
        logger.error(f"No hay filas válidas para procesar en '{filepath}'. Finalizando.")
        return

    # Filter target leads: non-empty business_email AND empty hibp_checked_at
    pending_indices = []
    for idx, row in enumerate(rows):
        email = (row.get('business_email') or '').strip()
        checked_at = (row.get('hibp_checked_at') or '').strip()
        if email and not checked_at:
            pending_indices.append(idx)

    total_pending = len(pending_indices)
    logger.info(f"Filas totales: {len(rows)} | Leads con email pendientes de verificar: {total_pending}")

    if total_pending == 0:
        logger.info("✅ Todos los leads con email ya han sido verificados previamente (idempotencia activa).")
        return

    if limit is not None:
        pending_indices = pending_indices[:limit]
        logger.info(f"Se procesarán {len(pending_indices)} leads conforme al límite establecido.")

    # Initialize BrowserManager with anti-detection and optional storage_state
    browser_manager = BrowserManager(config)
    page = await browser_manager.create_page(
        storage_state=storage_state_file if os.path.isfile(storage_state_file) else None,
        headless=headless
    )

    checked_count = 0
    breached_count = 0
    clean_count = 0
    error_count = 0

    try:
        for loop_idx, row_idx in enumerate(pending_indices):
            row = rows[row_idx]
            email = row.get('business_email', '').strip()
            business_name = row.get('business_name', 'Desconocido')

            logger.info("--------------------------------------------------------------------------")
            logger.info(f"[{loop_idx + 1}/{len(pending_indices)}] Verificando lead: '{business_name}' <{email}>")

            # Pause between emails (only if not the very first email checked in this run)
            if loop_idx > 0:
                sleep_time = random.uniform(delay_min, delay_max)
                if dry_run:
                    logger.info(f"[DRY-RUN] Simulación de pausa defensiva: {sleep_time:.1f} s ({sleep_time/60:.2f} min).")
                else:
                    logger.info(f"⏳ Pausa defensiva anti-baneo: durmiendo {sleep_time:.1f} s ({sleep_time/60:.2f} min)...")
                    await asyncio.sleep(sleep_time)

            # Query HIBP
            result = await verify_email_on_hibp(page, email, config, logger)

            if result is None:
                logger.error(f"❌ Error al consultar HIBP para '{email}'. No se modificará el registro para permitir reintento.")
                error_count += 1
                continue

            checked_count += 1
            now_iso = datetime.now().isoformat()

            if result['breached']:
                breached_count += 1
                logger.warning(
                    f"⚠️  BRECHA DETECTADA: {result['count']} brecha(s) para {email}\n"
                    f"    - Nombres: {result['names']}\n"
                    f"    - Fechas: {result['dates']}\n"
                    f"    - Datos: {result['compromised_data']}"
                )
            else:
                clean_count += 1
                logger.info(f"✅ LIMPIO: No se encontraron brechas para {email} (0 breaches).")

            # Update row values
            row['hibp_checked_at'] = now_iso
            row['hibp_breached'] = 'true' if result['breached'] else 'false'
            row['hibp_breach_count'] = str(result['count'])
            row['hibp_breach_names'] = result['names']
            row['hibp_breach_dates'] = result['dates']
            row['hibp_compromised_data'] = result['compromised_data']
            row['hibp_breach_descriptions'] = result['descriptions']

            if dry_run:
                logger.info(f"[DRY-RUN] Datos extraídos para {email} sin guardar en CSV.")
            else:
                # Save session cookies/storage_state after each successful verification
                try:
                    await browser_manager.context.storage_state(path=storage_state_file)
                except Exception as e:
                    logger.warning(f"No se pudo guardar storage_state: {e}")

                # Save leads atomically row-by-row
                save_success = save_leads_atomic(filepath, fieldnames, rows)
                if save_success:
                    logger.info(f"💾 Progreso guardado incrementalmente en '{filepath}'.")
                else:
                    logger.error(f"Error al guardar progreso en '{filepath}'.")

    except KeyboardInterrupt:
        logger.warning("\nProceso interrumpido por el usuario. El progreso verificado hasta ahora se encuentra a salvo.")
    finally:
        logger.info("Cerrando sesión del navegador...")
        try:
            await browser_manager.close()
        except Exception:
            pass

    logger.info("==========================================================================")
    logger.info("📊 RESUMEN FINAL DE VERIFICACIÓN HIBP")
    logger.info(f"   - Emails verificados: {checked_count}")
    logger.info(f"   - Emails con brechas: {breached_count}")
    logger.info(f"   - Emails limpios:     {clean_count}")
    logger.info(f"   - Fallos / Errores:   {error_count}")
    logger.info("==========================================================================")


def main():
    """CLI Entry point."""
    setup_logging()
    
    parser = argparse.ArgumentParser(
        description='LCA Scraping: Have I Been Pwned (HIBP) Breach Verification CLI'
    )
    parser.add_argument(
        '--output',
        help='Ruta al archivo CSV con los leads a verificar (default: results.csv o config.yaml)'
    )
    parser.add_argument(
        '--limit', '-l',
        type=int,
        help='Número máximo de emails a verificar en esta ejecución'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Navega y prueba selectores sin escribir cambios en el CSV'
    )
    parser.add_argument(
        '--headless',
        action='store_true',
        help='Fuerza la ejecución en modo headless (por defecto es visible/no-headless)'
    )
    parser.add_argument(
        '--delay-min',
        type=float,
        help='Override de tiempo mínimo de pausa (segundos) entre emails'
    )
    parser.add_argument(
        '--delay-max',
        type=float,
        help='Override de tiempo máximo de pausa (segundos) entre emails'
    )
    args = parser.parse_args()

    config = Config()

    filepath = args.output or config.get('output.filename', 'results.csv')
    
    # Overrides for delays if provided on CLI
    if args.delay_min is not None:
        config.settings.setdefault('hibp', {})['delay_min_seconds'] = args.delay_min
    if args.delay_max is not None:
        config.settings.setdefault('hibp', {})['delay_max_seconds'] = args.delay_max

    try:
        asyncio.run(
            run_breach_pipeline(
                filepath=filepath,
                config=config,
                dry_run=args.dry_run,
                limit=args.limit,
                headless_override=True if args.headless else None
            )
        )
    except KeyboardInterrupt:
        print("\nEjecución cancelada por el usuario.")
        sys.exit(0)


if __name__ == '__main__':
    main()
