"""
DEF-011 investigation/cleanup: identifies the campaigns flagged by
GET /analytics/scheduler-consistency as "published" with no completed
PublishingJob backing them, so a human can confirm they're safe test data
before anything is deleted.

DRY RUN BY DEFAULT. Only lists and inspects — never deletes or modifies
anything unless run with --delete AND --confirm together, as a deliberate
two-flag safety gate (this touches the shared Campaign/PublishingJob
tables, which esha-service does not own outright — see task doc §6 and
the dependency note in API_SPEC.md: "Esha does not bypass the application
database").

Run from apps/esha-service:
    python investigate_def011_campaign_pollution.py                # inspect only
    python investigate_def011_campaign_pollution.py --delete --confirm   # actually delete

What "delete" means here: removes ONLY the flagged Campaign rows (and their
PublishingJob rows via cascade, if the FK is set up that way) that are
status="published" with no completed job. It does NOT touch anything else,
and does NOT reset status instead of deleting (destructive either way, so
inspect first and decide which is right for your data before running
--delete).
"""
import sys
import os
import argparse
from collections import Counter

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from packages.database.session import SessionLocal
from packages.database.models import Campaign, Client, PublishingJob

CANONICAL_TENANT_ID = "00000000-0000-0000-0000-00000000000a"


def find_inconsistent_campaigns(db):
    campaigns = (
        db.query(Campaign)
        .filter(Campaign.tenant_id == CANONICAL_TENANT_ID, Campaign.status == "published")
        .all()
    )
    flagged = []
    for c in campaigns:
        jobs = c.publishing_jobs or []
        has_completed_job = any(j.status == "completed" for j in jobs)
        if not has_completed_job:
            flagged.append(c)
    return flagged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true", help="Delete the flagged campaigns")
    parser.add_argument("--confirm", action="store_true", help="Required alongside --delete to actually run")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        flagged = find_inconsistent_campaigns(db)
        print(f"\nFound {len(flagged)} campaign(s) marked 'published' with no completed publishing job:\n")

        by_client_name = Counter()
        for c in flagged:
            client = db.query(Client).filter(Client.id == c.client_id).first()
            client_name = client.company_name if client else "unknown"
            by_client_name[client_name] += 1
            job_statuses = [j.status for j in (c.publishing_jobs or [])]
            print(f"  {c.id}  client={client_name!r}  name={c.name!r}  created_at={c.created_at}  job_statuses={job_statuses or 'NONE'}")

        print("\nBreakdown by client:")
        for name, count in by_client_name.most_common():
            print(f"  {name}: {count}")

        if not args.delete:
            print("\nDRY RUN — nothing deleted. Re-run with --delete --confirm to remove these rows.")
            print("Before doing that: confirm with whoever owns the demo dataset that these are safe test")
            print("campaigns and not something that needs to be preserved or reset to a different status instead.")
            return

        if not args.confirm:
            print("\n--delete was passed without --confirm. Refusing to delete. Pass both flags to proceed.")
            return

        deleted_count = 0
        for c in flagged:
            db.delete(c)  # cascades to PublishingJob rows if the relationship is configured that way
            deleted_count += 1
        db.commit()
        print(f"\nDeleted {deleted_count} campaign(s). Re-run GET /analytics/scheduler-consistency to confirm inconsistent_count is now 0.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
