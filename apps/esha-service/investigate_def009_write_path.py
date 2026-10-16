"""
DEF-009 self-service investigation script.

Esha already has read access to the shared Postgres DB via her own service's
DB session (packages.database.session) - per Assignment Section 6, there is
no isolated database, so this is the same DB main.py already reads/writes.
No need to wait on Zeenat for the SQL reproduction query - capture it here.

This does two things:
  1. Captures the actual SQL query + real output for defect_log.md (the
     "SQL reproduction query still owed" gap).
  2. Characterizes the pattern - timestamp clustering, idempotency_key
     shapes, source diversity - to help confirm or rule out Zeenat's
     "local test/healthcheck tooling" theory independently, rather than
     relying on her description of it.

Usage:
    cd apps/esha-service
    python investigate_def009_write_path.py
"""
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from packages.database.session import SessionLocal
from packages.database.models import AnalyticsEvent
from sqlalchemy import func


def run():
    db = SessionLocal()
    try:
        print("=== DEF-009 investigation — run against the live shared DB ===\n")

        # --- Query A: the repro query owed to defect_log.md ---
        count = (
            db.query(func.count(AnalyticsEvent.id))
            .filter(
                AnalyticsEvent.client_id.is_(None),
                AnalyticsEvent.event_type == "tenant_resolution_marker",
            )
            .scalar()
        )
        print(f"Query A — unlinked marker count: {count}")
        print("SQL equivalent:")
        print("  SELECT COUNT(*) FROM analytics_events")
        print("  WHERE client_id IS NULL AND event_type = 'tenant_resolution_marker';\n")

        # --- Query B: breakdown by event_type + source ---
        print("Query B — breakdown by event_type/source among client_id-NULL rows:")
        rows = (
            db.query(AnalyticsEvent.event_type, AnalyticsEvent.source, func.count(AnalyticsEvent.id))
            .filter(AnalyticsEvent.client_id.is_(None))
            .group_by(AnalyticsEvent.event_type, AnalyticsEvent.source)
            .all()
        )
        for event_type, source, n in rows:
            print(f"  {event_type:<28} source={source!r:<20} count={n}")
        print()

        # --- Query C: timestamp clustering — does this look like a
        # recurring scheduled job, or a one-off historical seed? ---
        markers = (
            db.query(AnalyticsEvent.occurred_at, AnalyticsEvent.created_at,
                     AnalyticsEvent.source, AnalyticsEvent.idempotency_key)
            .filter(
                AnalyticsEvent.client_id.is_(None),
                AnalyticsEvent.event_type == "tenant_resolution_marker",
            )
            .order_by(AnalyticsEvent.occurred_at)
            .all()
        )
        if markers:
            print(f"Query C — {len(markers)} tenant_resolution_marker rows found:")
            print(f"  Earliest occurred_at: {markers[0][0]}")
            print(f"  Latest occurred_at:   {markers[-1][0]}")
            span = markers[-1][0] - markers[0][0]
            print(f"  Span: {span}")
            # created_at vs occurred_at gap tells us if these were all
            # written in one batch (e.g. a migration/seed script) vs
            # trickling in over time (e.g. a real recurring job)
            created_times = sorted(set(m[1] for m in markers))
            print(f"  Distinct created_at values: {len(created_times)} "
                  f"(1 value = written in a single batch; many spread-out "
                  f"values = genuinely recurring over time)")
            key_prefixes = sorted(set(m[3].rsplit("_", 2)[0] if m[3] else "" for m in markers))
            print(f"  Distinct idempotency_key prefixes: {key_prefixes[:5]}"
                  f"{'...' if len(key_prefixes) > 5 else ''}")
        else:
            print("Query C — no tenant_resolution_marker rows found on this DB connection.")
        print()

        print("=== What this tells you ===")
        print("- If 'Distinct created_at values' is 1 (or very few), these rows were")
        print("  written in a single batch — consistent with a one-time seed/migration")
        print("  script (like Zeenat's described scratch/seed_71_markers.py), NOT an")
        print("  ongoing recurring write path. That would actually contradict the")
        print("  original DEF-009 finding of 'recurring daily' — worth re-checking")
        print("  whether that was ever independently confirmed or just observed once.")
        print("- If timestamps spread out over many days with fresh values appearing")
        print("  after today, something is still actively writing these rows RIGHT")
        print("  NOW — rerun this script tomorrow and compare the count. A count that")
        print("  grows on its own is real evidence of a live, unidentified process.")

    finally:
        db.close()


if __name__ == "__main__":
    run()