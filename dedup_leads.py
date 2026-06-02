"""
Dedup Leads
-----------
Removes duplicate leads that share the same decision_maker_email.

For each group of leads with the same email, keeps the BEST one:
  Score: has draft_email (4) + has DM name (3) + has description (2) + has keywords (1)
  Tie-break: prefer higher status (sent > opened > replied > drafted > enriched > scraped)

Leads with no email are left untouched.
Leads with status sent/opened/replied are always kept (never deleted).

Usage:
    python dedup_leads.py          # dry run — shows what would be deleted
    python dedup_leads.py --apply  # actually delete duplicates
"""
import sys
from db import get_all_leads, delete_lead

DRY_RUN = "--apply" not in sys.argv

STATUS_RANK = {"replied": 6, "opened": 5, "sent": 4, "drafted": 3, "enriched": 2, "scraped": 1, "no_match": 0}

SAFE_STATUSES = {"sent", "opened", "replied"}


def score(lead):
    return (
        (4 if (lead.get("draft_email") or "").strip() else 0) +
        (3 if (lead.get("decision_maker_name") or "").strip() else 0) +
        (2 if (lead.get("company_description") or "").strip() else 0) +
        (1 if (lead.get("tech_keywords") or "").strip() else 0)
    )


def run():
    leads = get_all_leads()

    # Group by normalised email
    by_email = {}
    for l in leads:
        email = (l.get("decision_maker_email") or "").strip().lower()
        if not email:
            continue
        by_email.setdefault(email, []).append(l)

    duplicates = {e: group for e, group in by_email.items() if len(group) > 1}

    if not duplicates:
        print("No duplicate emails found. Database is clean.")
        return

    print(f"Found {len(duplicates)} email(s) with duplicates\n")

    total_to_delete = 0

    for email, group in sorted(duplicates.items()):
        # Never delete a safe (sent/opened/replied) lead — if any exist, keep all of them
        safe = [l for l in group if (l.get("status") or "") in SAFE_STATUSES]
        candidates = [l for l in group if (l.get("status") or "") not in SAFE_STATUSES]

        if not candidates:
            print(f"  {email} — all {len(group)} are sent/opened/replied, skipping")
            continue

        # Sort candidates: highest score first, then highest status rank
        candidates.sort(key=lambda l: (score(l), STATUS_RANK.get(l.get("status") or "", 0)), reverse=True)

        keep = candidates[0]
        to_delete = candidates[1:]

        print(f"  {email}")
        print(f"    KEEP  id={keep['id']} [{keep.get('status')}] {keep.get('company_name')} / {keep.get('job_title')} (score={score(keep)})")
        for l in to_delete:
            print(f"    DEL   id={l['id']} [{l.get('status')}] {l.get('company_name')} / {l.get('job_title')} (score={score(l)})")
            total_to_delete += 1
            if not DRY_RUN:
                delete_lead(l["id"])

        if safe:
            for l in safe:
                print(f"    KEEP  id={l['id']} [{l.get('status')}] {l.get('company_name')} (protected — already sent)")

        print()

    if DRY_RUN:
        print(f"DRY RUN: {total_to_delete} lead(s) would be deleted. Run with --apply to execute.")
    else:
        print(f"Done. Deleted {total_to_delete} duplicate lead(s).")


if __name__ == "__main__":
    run()
