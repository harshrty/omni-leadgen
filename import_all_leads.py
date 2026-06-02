"""
Import all leads from external files into the database.

Sources:
  1. new_leads.xlsx — enriched leads with DM name, title, email, location
  2. apollo_leads.csv — company name + website URL (scraped status)

Usage:
    python import_all_leads.py
"""
import csv
import sqlite3
from db import get_connection, get_stats


def _existing_companies(conn):
    c = conn.cursor()
    c.execute("SELECT LOWER(company_name) as cn FROM leads")
    return {row[0] for row in c.fetchall()}


def import_xlsx_leads(conn):
    """Import new_leads.xlsx — enriched leads with full DM info."""
    try:
        import openpyxl
    except ImportError:
        print("  ERROR: openpyxl not installed. Run: pip install openpyxl")
        return 0, 0

    try:
        wb = openpyxl.load_workbook("new_leads.xlsx", read_only=True)
    except FileNotFoundError:
        print("  new_leads.xlsx not found, skipping.")
        return 0, 0

    ws = wb["Leads"]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return 0, 0

    existing = _existing_companies(conn)
    c = conn.cursor()
    inserted = 0
    skipped = 0

    for row in rows[1:]:  # skip header
        company   = (row[0] or "").strip()
        dm_name   = (row[1] or "").strip()
        job_title = (row[2] or "").strip()
        email     = (row[3] or "").strip()
        location  = (row[4] or "").strip()

        if not company:
            skipped += 1
            continue
        if not email or "*" in email:
            skipped += 1
            continue
        if company.lower() in existing:
            skipped += 1
            continue

        try:
            c.execute(
                """INSERT INTO leads
                   (company_name, job_title, job_location,
                    decision_maker_name, decision_maker_title,
                    decision_maker_email, status)
                   VALUES (?,?,?,?,?,?,'enriched')""",
                (company, job_title or "N/A", location,
                 dm_name, job_title, email)
            )
            conn.commit()
            existing.add(company.lower())
            inserted += 1
            print(f"  + {company} → {dm_name} <{email}>")
        except sqlite3.IntegrityError:
            skipped += 1

    return inserted, skipped


def import_apollo_csv(conn):
    """Import apollo_leads.csv — company name + website, scraped status."""
    try:
        with open("apollo_leads.csv", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except FileNotFoundError:
        print("  apollo_leads.csv not found, skipping.")
        return 0, 0

    existing = _existing_companies(conn)
    c = conn.cursor()
    inserted = 0
    skipped = 0

    for row in rows:
        company = (row.get("Company Name") or "").strip()
        website = (row.get("Website URL") or "").strip()

        if not company:
            skipped += 1
            continue
        if company.lower() in existing:
            skipped += 1
            continue

        try:
            c.execute(
                """INSERT INTO leads
                   (company_name, company_website, job_title, status)
                   VALUES (?,?,'(Apollo import)','scraped')""",
                (company, website)
            )
            conn.commit()
            existing.add(company.lower())
            inserted += 1
            print(f"  + {company}")
        except sqlite3.IntegrityError:
            skipped += 1

    return inserted, skipped


def main():
    conn = get_connection()

    print("\n" + "=" * 60)
    print("  IMPORT: new_leads.xlsx (enriched leads)")
    print("=" * 60)
    ins1, skip1 = import_xlsx_leads(conn)
    print(f"\n  Inserted: {ins1} | Skipped (already in DB or invalid): {skip1}")

    print("\n" + "=" * 60)
    print("  IMPORT: apollo_leads.csv (company + website)")
    print("=" * 60)
    ins2, skip2 = import_apollo_csv(conn)
    print(f"\n  Inserted: {ins2} | Skipped (already in DB): {skip2}")

    conn.close()

    print("\n" + "=" * 60)
    print(f"  TOTAL imported: {ins1 + ins2}")
    print("=" * 60)
    get_stats()


if __name__ == "__main__":
    main()
