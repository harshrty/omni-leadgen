"""
B2B Lead Email Verifier — finds domains, generates email patterns, SMTP-verifies.

Input:  raw_leads.csv  (First Name, Last Name, Company Name)
Output: verified_leads_output.csv (written row-by-row, crash-safe)

Usage:
  pip install -r email_verifier_requirements.txt
  python email_verifier.py
  python email_verifier.py --input my_leads.csv --output results.csv
  python email_verifier.py --workers 3 --skip-verified
"""
import asyncio
import csv
import dns.resolver
import hashlib
import logging
import os
import random
import re
import smtplib
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from colorama import Fore, Style, init as colorama_init
from tqdm import tqdm

colorama_init(autoreset=True)

# ── CONFIG ──────────────────────────────────────────────────────────────────
INPUT_FILE = "raw_leads.csv"
OUTPUT_FILE = "verified_leads_output.csv"
MAX_WORKERS = 4           # parallel SMTP checks
SMTP_TIMEOUT = 10         # seconds per SMTP connection
DDG_DELAY = (1.5, 3.0)   # delay range between DDG searches
SMTP_DELAY = (0.5, 1.5)  # delay between SMTP attempts per domain
FROM_EMAIL = "verify@leadcheck.local"  # HELO/MAIL FROM (never actually sends)

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

SKIP_DOMAINS = {
    "google.com", "linkedin.com", "facebook.com", "twitter.com", "youtube.com",
    "wikipedia.org", "instagram.com", "glassdoor.com", "indeed.com", "yelp.com",
    "bloomberg.com", "crunchbase.com", "x.com", "tiktok.com", "amazon.com",
    "reddit.com", "github.com", "duckduckgo.com", "pinterest.com", "medium.com",
    "quora.com", "bbb.org", "irs.gov", "sec.gov",
}

# ── LOGGING ─────────────────────────────────────────────────────────────────

class ColorLog:
    @staticmethod
    def info(msg):
        print(f"{Fore.CYAN}[INFO]{Style.RESET_ALL} {msg}")

    @staticmethod
    def ok(msg):
        print(f"{Fore.GREEN}[  OK]{Style.RESET_ALL} {msg}")

    @staticmethod
    def warn(msg):
        print(f"{Fore.YELLOW}[WARN]{Style.RESET_ALL} {msg}")

    @staticmethod
    def fail(msg):
        print(f"{Fore.RED}[FAIL]{Style.RESET_ALL} {msg}")

    @staticmethod
    def step(msg):
        print(f"{Fore.MAGENTA}[STEP]{Style.RESET_ALL} {msg}")

    @staticmethod
    def smtp(msg):
        print(f"{Fore.BLUE}[SMTP]{Style.RESET_ALL} {msg}")


log = ColorLog()


# ── DOMAIN DISCOVERY ────────────────────────────────────────────────────────

def _extract_domain(url):
    """Extract clean domain from a URL."""
    url = url.lower().strip()
    for prefix in ["https://", "http://", "www."]:
        if url.startswith(prefix):
            url = url[len(prefix):]
    domain = url.split("/")[0].split("?")[0].split("#")[0]
    if "." in domain and len(domain) > 3:
        return domain
    return ""


def find_domain_ddg(company_name, retries=3):
    """Find company domain via DuckDuckGo search with exponential backoff."""
    from ddgs import DDGS

    for attempt in range(retries):
        try:
            query = company_name + " official website"
            results = DDGS().text(query, max_results=8)

            for r in results:
                url = r.get("href", "")
                domain = _extract_domain(url)
                if not domain:
                    continue
                # Skip social media / aggregator sites
                if any(domain.endswith(s) or domain.startswith(s.split(".")[0])
                       for s in SKIP_DOMAINS):
                    continue
                return domain

            return ""

        except Exception as e:
            if attempt < retries - 1:
                wait = (2 ** attempt) + random.uniform(0.5, 1.5)
                log.warn(f"DDG retry {attempt+1}/{retries} for '{company_name}': {str(e)[:50]}. "
                         f"Waiting {wait:.1f}s...")
                time.sleep(wait)
            else:
                log.fail(f"DDG failed for '{company_name}': {str(e)[:60]}")
                return ""

    return ""


# ── EMAIL PERMUTATION ───────────────────────────────────────────────────────

def generate_email_patterns(first_name, last_name, domain):
    """Generate standard B2B email patterns."""
    first = re.sub(r'[^a-z]', '', first_name.lower().strip())
    last = re.sub(r'[^a-z]', '', last_name.lower().strip())

    if not first or not last or not domain:
        return []

    initial = first[0]

    patterns = [
        f"{first}.{last}@{domain}",         # john.smith@company.com
        f"{initial}{last}@{domain}",         # jsmith@company.com
        f"{first}@{domain}",                 # john@company.com
        f"{first}{last}@{domain}",           # johnsmith@company.com
        f"{last}.{first}@{domain}",          # smith.john@company.com
        f"{first}_{last}@{domain}",          # john_smith@company.com
        f"{initial}.{last}@{domain}",        # j.smith@company.com
        f"{first}{initial}@{domain}",        # johns@company.com  (first + last initial)
    ]

    return patterns


# ── MX RECORD LOOKUP ────────────────────────────────────────────────────────

_mx_cache = {}


def get_mx_host(domain):
    """Get the primary MX host for a domain. Cached."""
    if domain in _mx_cache:
        return _mx_cache[domain]

    try:
        answers = dns.resolver.resolve(domain, "MX")
        # Sort by priority (lowest = highest priority)
        mx_records = sorted(answers, key=lambda r: r.preference)
        mx_host = str(mx_records[0].exchange).rstrip(".")
        _mx_cache[domain] = mx_host
        return mx_host
    except Exception:
        _mx_cache[domain] = ""
        return ""


# ── SMTP VERIFICATION ──────────────────────────────────────────────────────

def verify_email_smtp(email, mx_host):
    """
    Verify a single email via SMTP RCPT TO check.
    Returns: True (valid), False (invalid), None (inconclusive/greylisted)
    """
    if not mx_host:
        return None

    try:
        with smtplib.SMTP(timeout=SMTP_TIMEOUT) as smtp:
            smtp.connect(mx_host, 25)
            smtp.helo(socket.getfqdn())
            smtp.mail(FROM_EMAIL)
            code, msg = smtp.rcpt(email)
            smtp.quit()

            if code == 250:
                return True
            elif code in (550, 551, 552, 553, 554):
                return False
            else:
                return None  # greylisted or temp error

    except smtplib.SMTPServerDisconnected:
        return None
    except smtplib.SMTPConnectError:
        return None
    except socket.timeout:
        return None
    except ConnectionRefusedError:
        return None
    except OSError:
        return None
    except Exception:
        return None


def verify_email_patterns(patterns, domain):
    """
    Try each email pattern via SMTP. Return the first verified one.
    Falls back to best guess if SMTP is inconclusive for all.
    """
    mx_host = get_mx_host(domain)
    if not mx_host:
        log.warn(f"  No MX record for {domain}")
        return patterns[0] if patterns else "", "no_mx", ""

    log.smtp(f"  MX: {domain} → {mx_host}")

    best_guess = patterns[0] if patterns else ""
    inconclusive = []

    for email in patterns:
        result = verify_email_smtp(email, mx_host)

        if result is True:
            log.ok(f"  {Fore.GREEN}VERIFIED: {email}{Style.RESET_ALL}")
            return email, "verified", mx_host
        elif result is False:
            log.fail(f"  REJECTED: {email}")
        else:
            inconclusive.append(email)
            log.warn(f"  INCONCLUSIVE: {email}")

        time.sleep(random.uniform(*SMTP_DELAY))

    # If all are inconclusive (catch-all domain), return first pattern as best guess
    if inconclusive:
        log.warn(f"  Catch-all or greylisted — using best guess: {best_guess}")
        return best_guess, "catch_all", mx_host

    # All rejected
    return "", "all_rejected", mx_host


# ── CSV I/O ─────────────────────────────────────────────────────────────────

def load_input(path):
    """Load and clean the input CSV."""
    df = pd.read_csv(path, dtype=str).fillna("")

    # Normalize column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Try to map common column names
    col_map = {}
    for col in df.columns:
        if "first" in col and "name" in col:
            col_map["first_name"] = col
        elif "last" in col and "name" in col:
            col_map["last_name"] = col
        elif "company" in col:
            col_map["company_name"] = col
        elif col in ("first", "firstname"):
            col_map["first_name"] = col
        elif col in ("last", "lastname"):
            col_map["last_name"] = col
        elif col in ("company", "organization", "org"):
            col_map["company_name"] = col

    if len(col_map) < 3:
        # Fallback: assume first 3 columns are first, last, company
        cols = list(df.columns)
        if len(cols) >= 3:
            col_map = {"first_name": cols[0], "last_name": cols[1], "company_name": cols[2]}
        else:
            log.fail(f"CSV must have at least 3 columns. Found: {list(df.columns)}")
            sys.exit(1)

    rows = []
    for _, row in df.iterrows():
        first = str(row.get(col_map["first_name"], "")).strip()
        last = str(row.get(col_map["last_name"], "")).strip()
        company = str(row.get(col_map["company_name"], "")).strip()

        if not first or not company:
            continue
        if first.lower() in ("nan", "none", "n/a", ""):
            continue

        rows.append({"first_name": first, "last_name": last, "company_name": company})

    return rows


def init_output(path):
    """Create output CSV with headers if it doesn't exist."""
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "First Name", "Last Name", "Company Name", "Domain",
                "Verified Email", "Status", "MX Host", "All Patterns",
            ])


def append_output(path, row):
    """Append a single row to output CSV (crash-safe)."""
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(row)


def get_already_processed(path):
    """Get set of (first_name, last_name, company) already in output file."""
    done = set()
    if not os.path.exists(path):
        return done
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            for row in reader:
                if len(row) >= 3:
                    key = (row[0].strip().lower(), row[1].strip().lower(), row[2].strip().lower())
                    done.add(key)
    except Exception:
        pass
    return done


# ── MAIN PIPELINE ───────────────────────────────────────────────────────────

def process_lead(lead, domain_cache):
    """Process a single lead: domain lookup → patterns → SMTP verify."""
    first = lead["first_name"]
    last = lead["last_name"]
    company = lead["company_name"]
    company_key = company.lower().strip()

    log.step(f"{Fore.MAGENTA}{first} {last}{Style.RESET_ALL} @ "
             f"{Fore.CYAN}{company}{Style.RESET_ALL}")

    # 1. Domain discovery (cached per company)
    if company_key in domain_cache:
        domain = domain_cache[company_key]
        log.info(f"  Domain (cached): {domain}")
    else:
        log.info(f"  Searching domain for '{company}'...")
        domain = find_domain_ddg(company)
        domain_cache[company_key] = domain
        if domain:
            log.ok(f"  Domain found: {domain}")
        else:
            log.fail(f"  No domain found")
        time.sleep(random.uniform(*DDG_DELAY))

    if not domain:
        return [first, last, company, "", "", "no_domain", "", ""]

    # 2. Generate email patterns
    patterns = generate_email_patterns(first, last, domain)
    if not patterns:
        return [first, last, company, domain, "", "no_patterns", "", ""]

    log.info(f"  Generated {len(patterns)} patterns")

    # 3. SMTP verify
    verified_email, status, mx_host = verify_email_patterns(patterns, domain)

    return [
        first, last, company, domain,
        verified_email, status, mx_host,
        "; ".join(patterns),
    ]


def run(input_file=INPUT_FILE, output_file=OUTPUT_FILE, skip_verified=True):
    """Main entry point."""
    print("")
    print(f"{Fore.CYAN}{'=' * 65}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  B2B EMAIL VERIFIER — Domain Discovery + SMTP Check{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 65}{Style.RESET_ALL}")
    print("")

    # Load input
    if not os.path.exists(input_file):
        log.fail(f"Input file not found: {input_file}")
        log.info(f"Create {input_file} with columns: First Name, Last Name, Company Name")
        sys.exit(1)

    leads = load_input(input_file)
    log.ok(f"Loaded {len(leads)} leads from {input_file}")

    # Check already processed
    init_output(output_file)
    already_done = get_already_processed(output_file) if skip_verified else set()
    if already_done:
        log.info(f"Already processed: {len(already_done)} (will skip)")

    # Filter out already processed
    to_process = []
    for lead in leads:
        key = (lead["first_name"].lower(), lead["last_name"].lower(),
               lead["company_name"].lower())
        if key not in already_done:
            to_process.append(lead)

    if not to_process:
        log.ok("All leads already processed!")
        return

    log.info(f"Processing {len(to_process)} leads...")
    print("")

    domain_cache = {}
    verified_count = 0
    failed_count = 0

    for i, lead in enumerate(to_process):
        print(f"{Fore.WHITE}[{i+1}/{len(to_process)}] {'─' * 50}{Style.RESET_ALL}")

        try:
            result = process_lead(lead, domain_cache)
            append_output(output_file, result)

            status = result[5]
            if status == "verified":
                verified_count += 1
            elif status in ("catch_all",):
                verified_count += 1  # best guess counts
            else:
                failed_count += 1

        except KeyboardInterrupt:
            print("")
            log.warn("Stopped by user. All processed leads have been saved.")
            break
        except Exception as e:
            log.fail(f"Error processing {lead['first_name']} {lead['last_name']}: {str(e)[:60]}")
            append_output(output_file, [
                lead["first_name"], lead["last_name"], lead["company_name"],
                "", "", "error", "", str(e)[:100],
            ])
            failed_count += 1

    # Summary
    print("")
    print(f"{Fore.CYAN}{'=' * 65}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}  DONE:{Style.RESET_ALL}")
    print(f"    Verified/best-guess emails: {Fore.GREEN}{verified_count}{Style.RESET_ALL}")
    print(f"    Failed/no domain:           {Fore.RED}{failed_count}{Style.RESET_ALL}")
    print(f"    Domains cached:             {len(domain_cache)}")
    print(f"    Output saved to:            {Fore.CYAN}{output_file}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 65}{Style.RESET_ALL}")


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="B2B Lead Email Verifier")
    parser.add_argument("--input", default=INPUT_FILE, help="Input CSV path")
    parser.add_argument("--output", default=OUTPUT_FILE, help="Output CSV path")
    parser.add_argument("--skip-verified", action="store_true", default=True,
                        help="Skip already-processed leads (default: True)")
    parser.add_argument("--no-skip", action="store_true",
                        help="Reprocess all leads even if already in output")
    args = parser.parse_args()

    skip = not args.no_skip
    run(input_file=args.input, output_file=args.output, skip_verified=skip)
