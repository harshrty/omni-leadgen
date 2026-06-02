import sqlite3
from datetime import datetime
from config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _fetchall(cursor):
    return [dict(r) for r in cursor.fetchall()]


def _fetchone(cursor):
    row = cursor.fetchone()
    return dict(row) if row else None


def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            company_website TEXT,
            company_domain TEXT,
            company_contact_email TEXT,
            company_description TEXT,
            company_industry TEXT,
            job_title TEXT,
            job_description TEXT,
            job_url TEXT,
            job_location TEXT,
            job_posted_date TEXT,
            salary TEXT,
            decision_maker_name TEXT,
            decision_maker_title TEXT,
            decision_maker_email TEXT,
            decision_maker_linkedin TEXT,
            draft_subject TEXT,
            draft_email TEXT,
            draft_linkedin_note TEXT,
            tech_keywords TEXT,
            status TEXT DEFAULT 'scraped',
            message_id TEXT,
            sent_at TEXT,
            opened_at TEXT,
            replied_at TEXT,
            company_size TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_status ON leads(status)")
    try:
        c.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_company_job
            ON leads(company_name, job_title)
        """)
    except sqlite3.OperationalError:
        pass
    for col_name, col_type in [
        ("company_description", "TEXT"),
        ("company_industry", "TEXT"),
        ("tech_keywords", "TEXT"),
        ("salary", "TEXT"),
        ("message_id", "TEXT"),
        ("sent_at", "TEXT"),
        ("opened_at", "TEXT"),
        ("replied_at", "TEXT"),
        ("company_size", "TEXT"),
        ("follow_up_at", "TEXT"),
    ]:
        try:
            c.execute("ALTER TABLE leads ADD COLUMN " + col_name + " " + col_type)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()
    print("Database ready: SQLite → " + DB_PATH)


def insert_lead(company_name, job_title, job_description="",
                job_url="", job_location="", company_domain="",
                job_posted_date="", salary=""):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            """INSERT OR IGNORE INTO leads
               (company_name, company_domain, job_title, job_description,
                job_url, job_location, job_posted_date, salary, status)
               VALUES (?,?,?,?,?,?,?,?,'scraped')""",
            (company_name, company_domain, job_title,
             job_description, job_url, job_location, job_posted_date, salary)
        )
        inserted = c.rowcount > 0
        conn.commit()
        return inserted
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def get_leads_by_status(status):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM leads WHERE status = ?", (status,))
    rows = _fetchall(c)
    conn.close()
    return rows


def update_lead(lead_id, **fields):
    if not fields:
        return
    fields["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(k + " = ?" for k in fields)
    values = list(fields.values()) + [lead_id]
    conn = get_connection()
    conn.cursor().execute(
        f"UPDATE leads SET {set_clause} WHERE id = ?", values
    )
    conn.commit()
    conn.close()


def get_existing_companies():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT company_name FROM leads")
    rows = _fetchall(c)
    conn.close()
    return {r["company_name"].strip().lower() for r in rows}


def get_all_leads():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM leads ORDER BY created_at DESC")
    rows = _fetchall(c)
    conn.close()
    return rows


def get_stats():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT status, COUNT(*) as count FROM leads GROUP BY status")
    rows = _fetchall(c)
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


def mark_sent(lead_id, message_id, follow_up_days=3):
    from datetime import timedelta
    follow_up_at = (datetime.now() + timedelta(days=follow_up_days)).isoformat()
    update_lead(lead_id, status="sent", message_id=message_id,
                sent_at=datetime.now().isoformat(),
                follow_up_at=follow_up_at)


def mark_opened(lead_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT status FROM leads WHERE id = ?", (lead_id,))
    row = _fetchone(c)
    conn.close()
    if row and row["status"] not in ("opened", "replied"):
        update_lead(lead_id, status="opened", opened_at=datetime.now().isoformat())


def mark_replied(lead_id):
    update_lead(lead_id, status="replied", replied_at=datetime.now().isoformat(),
                follow_up_at=None)


def get_leads_due_for_followup():
    """Return sent/opened leads whose follow_up_at is in the past and not yet replied."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        SELECT * FROM leads
        WHERE status IN ('sent', 'opened')
          AND follow_up_at IS NOT NULL
          AND follow_up_at <= ?
        ORDER BY follow_up_at ASC
    """, (now,))
    rows = _fetchall(c)
    conn.close()
    return rows


def get_lead_by_id(lead_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
    row = _fetchone(c)
    conn.close()
    return row


def get_lead_by_message_id(message_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM leads WHERE message_id = ?", (message_id,))
    row = _fetchone(c)
    conn.close()
    return row


def get_lead_by_email(email):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM leads WHERE decision_maker_email = ? AND status IN ('sent', 'opened')",
        (email,)
    )
    row = _fetchone(c)
    conn.close()
    return row


def clone_lead(lead_id, dm_name, dm_title, dm_email):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
    original = _fetchone(c)
    if not original:
        conn.close()
        return None

    copy_fields = [
        "company_name", "company_website", "company_domain", "company_contact_email",
        "company_description", "company_industry", "job_title", "job_description",
        "job_url", "job_location", "job_posted_date", "salary", "tech_keywords",
    ]
    cols = ", ".join(copy_fields + [
        "decision_maker_name", "decision_maker_title", "decision_maker_email", "status"
    ])
    values = [original.get(f) for f in copy_fields] + [dm_name, dm_title, dm_email, "scraped"]
    placeholders = ", ".join(["?"] * len(values))

    new_id = None
    try:
        c.execute(f"INSERT INTO leads ({cols}) VALUES ({placeholders})", values)
        new_id = c.lastrowid
    except sqlite3.IntegrityError:
        jt_idx = copy_fields.index("job_title")
        values[jt_idx] = (original.get("job_title") or "") + " (2nd DM)"
        c.execute(f"INSERT INTO leads ({cols}) VALUES ({placeholders})", values)
        new_id = c.lastrowid

    conn.commit()
    conn.close()
    return new_id


def delete_lead(lead_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    conn.commit()
    conn.close()


# Auto-initialize on import
init_db()

if __name__ == "__main__":
    get_stats()
