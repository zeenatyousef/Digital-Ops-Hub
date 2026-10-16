"""
One-time cleanup: removes leftover analytics_events rows created by tests
that used a random event_key on every run (fixed in test_main.py as of
2026-09-01). These rows have no client_id and were landing in the
"unknown" bucket of GET /analytics/client-summary and
GET /analytics/client-health, inflating those numbers on every pytest run.

Safe to run multiple times — deletes by the exact test-pollution
idempotency_key patterns, nothing else.

Run from the repo root:
    python -m apps.esha-service.cleanup_test_pollution_events
or from apps/esha-service:
    python cleanup_test_pollution_events.py
"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from packages.database.session import SessionLocal
from packages.database.models import AnalyticsEvent

# Matches the OLD random-key prefixes this cleanup is removing, plus the NEW
# fixed keys (so re-running tests after this cleanup doesn't re-accumulate --
# the fixed-key rows get recreated fresh and idempotently going forward, this
# script just clears out today's leftovers once).
POLLUTION_PREFIXES = (
    "test-event-",
    "test-dash-",
    "test-datefilter-",
    "test-role-",
)


def main():
    db = SessionLocal()
    try:
        rows = db.query(AnalyticsEvent).filter(
            AnalyticsEvent.client_id.is_(None)
        ).all()

        to_delete = [
            r for r in rows
            if r.idempotency_key and r.idempotency_key.startswith(POLLUTION_PREFIXES)
        ]

        if not to_delete:
            print("No leftover test-pollution rows found. Nothing to do.")
            return

        print(f"Found {len(to_delete)} leftover test-pollution row(s):")
        for r in to_delete:
            print(f"  - {r.id} | {r.event_type} | {r.idempotency_key} | {r.occurred_at}")

        for r in to_delete:
            db.delete(r)
        db.commit()
        print(f"Deleted {len(to_delete)} row(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
