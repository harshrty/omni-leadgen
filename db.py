import sqlite3
import os
from datetime import datetime
from config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            company_website TEXT,
            company_domain TEXT,
            company_phone TEXT,
            company_contact_email TEXT,
            job_title TEXT,
            job_description TEXT,
            job_url TEXT,
            job_location TEXT,
            job_posted_date TEXT,
            decision_maker_name TEXT,
            decision_maker_title TEXT,
            decision_maker_email TEXT,
            decision_maker_linkedin TEXT,
            draft_subject TEXT,
            draft_email TEXT,
            draft_linkedin_note TEXT,
            status TEXT DEFAULT 'scraped',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_status ON leads(status)")
    c.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_company_job
        ON leads(company_name, job_title)
    """)

    conn.commit()
    conn.close()
    print("Database ready: " + DB_PATH)


def insert_lead(company_name, job_title, job_description="",
                job_url="", job_location="", company_domain="",
                job_posted_date=""):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO leads
               (company_name, company_domain, job_title, job_description,
                job_url, job_location, job_posted_date, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'scraped')""",
            (company_name, company_domain, job_title,
             job_description, job_url, job_location, job_posted_date)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_leads_by_status(status):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM leads WHERE status = ?", (status,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_lead(lead_id, **fields):
    if not fields:
        return
    fields["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(k + " = ?" for k in fields)
    values = list(fields.values()) + [lead_id]
    conn = get_connection()
    conn.execute("UPDATE leads SET " + set_clause + " WHERE id = ?", values)
    conn.commit()
    conn.close()


def get_all_leads():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM leads ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats():
    conn = get_connection()
    rows = conn.execute(
        "SELECT status, COUNT(*) as count FROM leads GROUP BY status"
    ).fetchall()
    conn.close()

    print("")
    print("--- Pipeline Stats ---")
    total = 0
    for r in rows:
        print("  " + r["status"].ljust(16) + ": " + str(r["count"]))
        total += r["count"]
    print("  " + "TOTAL".ljust(16) + ": " + str(total))
    print("----------------------")
    print("")
    return {r["status"]: r["count"] for r in rows}


# Auto-initialize on import
init_db()

if __name__ == "__main__":
    get_stats()