"""
Manual Contact Drafter
----------------------
Use this when you have manually researched the decision-maker for a lead.

Input: manual_contacts.csv with columns:
    company_name, dm_name, dm_title, dm_email

For each row:
  1. Finds the matching lead in the DB by company_name
  2. Updates decision_maker_name, decision_maker_title, decision_maker_email
  3. Drafts the email using the same Claude rules as draft_emails.py
  4. Saves draft_subject + draft_email with status = 'drafted'

Everything downstream (send, open tracking, reply tracking) works unchanged.

Usage:
    python manual_draft.py               # reads manual_contacts.csv by default
    python manual_draft.py my_file.csv   # or pass a custom CSV path
"""

import csv
import sys
import time
from config import ANTHROPIC_API_KEY
from db import get_connection, _ph
from draft_emails import generate_email, sanitize_text

import anthropic

INPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "manual_contacts.csv"


def find_lead_by_company(conn, company_name):
    """Find best matching lead for a company (prefer leads with job descriptions)."""
    ph = _ph()
    c = conn.cursor()
    c.execute(
        f"""SELECT * FROM leads
            WHERE LOWER(company_name) = LOWER({ph})
            AND status NOT IN ('sent', 'opened', 'replied')
            ORDER BY
                CASE WHEN job_description IS NOT NULL AND job_description != '' THEN 0 ELSE 1 END,
                id ASC
            LIMIT 1""",
        (company_name.strip(),)
    )
    row = c.fetchone()
    if row is None:
        return None
    if hasattr(row, 'keys'):
        return dict(row)
    cols = [d[0] for d in c.description]
    return dict(zip(cols, row))


def update_dm_and_draft(conn, lead_id, dm_name, dm_title, dm_email, subject, body):
    ph = _ph()
    c = conn.cursor()
    if _ph() == "%s":
        c.execute(
            """UPDATE leads SET
                decision_maker_name = %s,
                decision_maker_title = %s,
                decision_maker_email = %s,
                draft_subject = %s,
                draft_email = %s,
                status = 'drafted',
                updated_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (dm_name, dm_title, dm_email, subject, body, lead_id)
        )
    else:
        c.execute(
            """UPDATE leads SET
                decision_maker_name = ?,
                decision_maker_title = ?,
                decision_maker_email = ?,
                draft_subject = ?,
                draft_email = ?,
                status = 'drafted',
                updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (dm_name, dm_title, dm_email, subject, body, lead_id)
        )
    conn.commit()


def run():
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set in .env")
        return

    try:
        with open(INPUT_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            contacts = list(reader)
    except FileNotFoundError:
        print(f"ERROR: File '{INPUT_FILE}' not found.")
        print("Create a CSV file with columns: company_name, dm_name, dm_title, dm_email")
        return

    if not contacts:
        print("No rows found in CSV.")
        return

    required_cols = {"company_name", "dm_name", "dm_title", "dm_email"}
    actual_cols = set(contacts[0].keys())
    missing = required_cols - actual_cols
    if missing:
        print(f"ERROR: CSV is missing columns: {missing}")
        print("Required columns: company_name, dm_name, dm_title, dm_email")
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    conn = get_connection()

    total = len(contacts)
    done = 0
    failed = 0
    not_found = 0

    print(f"Processing {total} contacts from '{INPUT_FILE}'...\n")

    for i, row in enumerate(contacts):
        company  = row["company_name"].strip()
        dm_name  = row["dm_name"].strip()
        dm_title = row["dm_title"].strip()
        dm_email = row["dm_email"].strip()
        prefix   = f"[{i+1}/{total}] {company}"

        if not company or not dm_email:
            print(f"{prefix} SKIPPED (missing company_name or dm_email)")
            failed += 1
            continue

        lead = find_lead_by_company(conn, company)
        if not lead:
            print(f"{prefix} NOT FOUND in DB (check company name spelling)")
            not_found += 1
            continue

        # Inject manual DM details into the lead dict before drafting
        lead["decision_maker_name"]  = dm_name
        lead["decision_maker_title"] = dm_title
        lead["decision_maker_email"] = dm_email

        try:
            subject, body = generate_email(client, lead)
            if subject and body:
                update_dm_and_draft(conn, lead["id"], dm_name, dm_title, dm_email, subject, body)
                done += 1
                print(f"{prefix} -> {dm_name} ({dm_title}) -> drafted OK")
            else:
                failed += 1
                print(f"{prefix} FAILED (empty AI response)")
        except Exception as e:
            failed += 1
            print(f"{prefix} ERROR: {str(e)[:80]}")

        time.sleep(0.5)

    conn.close()
    print(f"\nDone. Drafted: {done} | Failed: {failed} | Not found in DB: {not_found}")

    if done > 0:
        print("\nRe-exporting Excel...")
        from export_xlsx import export
        export()


if __name__ == "__main__":
    run()
