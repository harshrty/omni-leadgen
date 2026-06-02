"""
Remove all leads that are NOT enriched from the database.
Keeps: enriched, drafted, sent, opened, replied
Deletes: scraped, no_match, and anything without a decision_maker_email

Run:
    python cleanup_unenriched.py          # preview (dry run)
    python cleanup_unenriched.py --apply  # actually delete
"""
import sys
from db import get_all_leads, get_stats

DRY_RUN = "--apply" not in sys.argv

KEEP_STATUSES = {"enriched", "drafted", "sent", "opened", "replied"}

def run():
    leads = get_all_leads()
    to_delete = [
        l for l in leads
        if (l.get("status") or "scraped").lower() not in KEEP_STATUSES
    ]

    print("")
    print("=" * 50)
    print("  CLEANUP: Remove unenriched leads")
    print("=" * 50)
    print(f"  Total leads in DB : {len(leads)}")
    print(f"  To delete         : {len(to_delete)}")
    print(f"  To keep           : {len(leads) - len(to_delete)}")
    print("")

    if not to_delete:
        print("  Nothing to delete.")
        return

    # Show breakdown of what will be deleted
    from collections import Counter
    counts = Counter((l.get("status") or "scraped") for l in to_delete)
    print("  Deleting by status:")
    for status, count in sorted(counts.items()):
        print(f"    {status:<16}: {count}")
    print("")

    if DRY_RUN:
        print("  DRY RUN — nothing deleted.")
        print("  Run with --apply to actually delete.")
    else:
        from db import get_connection, _ph
        ids = [l["id"] for l in to_delete]
        conn = get_connection()
        ph = _ph()
        placeholders = ",".join([ph] * len(ids))
        conn.cursor().execute(f"DELETE FROM leads WHERE id IN ({placeholders})", ids)
        conn.commit()
        conn.close()
        print(f"  Deleted {len(to_delete)} leads.")
        print("")
        get_stats()

if __name__ == "__main__":
    run()
