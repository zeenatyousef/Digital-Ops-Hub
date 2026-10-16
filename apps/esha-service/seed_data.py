"""
Seed data script for esha-service — updated for the new schema
(client_id, category, platform, version, is_active as real columns).

Populates realistic hashtag sets for the 4 test clients named in the task doc:
Bebop, Samvix, FBR, ABC Traders.

Also populates realistic analytics_events (post reach/engagement metrics and
ticket.opened/ticket.closed pairs) so /analytics/client-summary and
/analytics/client-health have real data to compute from, instead of
returning "unavailable" for everything until someone manually POSTs test
events through /docs first.

Run with:  python -m seed_data
(from inside apps/esha-service, with venv active and Docker's Postgres running)
"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from packages.database.session import SessionLocal
from packages.database.models import Tenant, Client, HashtagSet, HashtagItem, AnalyticsEvent

# Canonical demo tenant UUID — must match main.py's CANONICAL_TENANT_ID and
# the real demo Super Admin login. See DEF-007 in evidence/defect_log.md.
CANONICAL_TENANT_ID = UUID("00000000-0000-0000-0000-00000000000a")


SEED_DATA = {
    "bebop": {
        "platform": "instagram",
        "category": "brand",
        "tags": ["#BebopStaplesMill", "#RichmondEats", "#RVAFood", "#HalalFoodRVA"],
    },
    "samvix": {
        "platform": "instagram",
        "category": "brand",
        "tags": ["#Samvix", "#SamvixDeals", "#TechDealsPK"],
    },
    "fbr": {
        "platform": "twitter",
        "category": "industry",
        "tags": ["#FBRUpdates", "#TaxSeasonPK", "#FBRPakistan"],
    },
    "abc-traders": {
        "platform": "facebook",
        "category": "local",
        "tags": ["#ABCTraders", "#WholesaleDeals", "#TradersHub"],
    },
}


# =========================================================
# ANALYTICS EVENT SEED DATA
#
# reach/engagement are made-up but plausible test numbers. Ticket
# resolution_hours values are realistic multi-hour gaps (not the
# few-seconds gap you get testing by hand through /docs), so
# avg_ticket_resolution_hours looks like real support data in the demo.
#
# NOTE: fbr is intentionally left out here — no post/ticket test data for
# it yet, so /analytics/client-summary and /analytics/client-health will
# correctly report "unavailable" for fbr until real data exists. That's
# consistent with §10: missing data stays missing, not zero.
# =========================================================
ANALYTICS_SEED = {
    "bebop": {
        "posts": [
            {"reach": 4200, "engagement": 310},
            {"reach": 3100, "engagement": 155},
        ],
        "tickets": [
            {"resolution_hours": 2.5},
            {"resolution_hours": 5.0},
        ],
    },
    "samvix": {
        "posts": [
            {"reach": 2800, "engagement": 90},
        ],
        "tickets": [
            {"resolution_hours": 1.0},
        ],
    },
    "abc-traders": {
        "posts": [
            {"reach": 950, "engagement": 20},
        ],
        "tickets": [
            {"resolution_hours": 8.0},
        ],
    },
}


def get_or_create_dev_tenant(db):
    """Resolves the seed tenant by its fixed canonical UUID (matches
    main.py's get_or_create_dev_tenant and the real demo login) instead of
    by name, so seeded data always lands under the same tenant the demo
    actually uses. See DEF-007."""
    tenant = db.query(Tenant).filter(Tenant.id == CANONICAL_TENANT_ID).first()
    if not tenant:
        tenant = Tenant(id=CANONICAL_TENANT_ID, name="esha-dev-tenant", status="active")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        print(f"Created dev tenant: {tenant.id}")
    return tenant


def get_or_create_client(db, tenant_id, client_name: str) -> Client:
    existing = db.query(Client).filter(
        Client.tenant_id == tenant_id, Client.company_name == client_name
    ).first()
    if existing:
        return existing
    new_client = Client(
        tenant_id=tenant_id, company_name=client_name,
        contact_email=f"{client_name}@example.com",
    )
    db.add(new_client)
    db.commit()
    db.refresh(new_client)
    print(f"Created client: {client_name} -> {new_client.id}")
    return new_client


def _event_exists(db, event_key: str) -> bool:
    return db.query(AnalyticsEvent).filter(
        AnalyticsEvent.idempotency_key == event_key
    ).first() is not None


def seed_analytics_events(db, tenant):
    """Idempotent: safe to run seed_data.py multiple times without creating
    duplicate events, since every event_key is checked before insert (same
    idempotency pattern as POST /analytics/event in main.py)."""
    now = datetime.now(timezone.utc)

    for client_name, data in ANALYTICS_SEED.items():
        client_row = get_or_create_client(db, tenant.id, client_name)

        for i, post in enumerate(data["posts"]):
            event_key = f"seed-post-{client_name}-{i}"
            if _event_exists(db, event_key):
                continue
            db.add(AnalyticsEvent(
                tenant_id=tenant.id,
                client_id=client_row.id,
                event_type="post.published",
                object_type="post",
                object_id=uuid4(),
                metrics=json.dumps({"reach": post["reach"], "engagement": post["engagement"]}),
                source="seed_data",
                occurred_at=now - timedelta(days=i + 1),
                idempotency_key=event_key,
            ))

        for i, ticket in enumerate(data["tickets"]):
            object_id = uuid4()
            opened_key = f"seed-ticket-{client_name}-{i}-open"
            closed_key = f"seed-ticket-{client_name}-{i}-close"
            if _event_exists(db, opened_key):
                continue
            opened_at = now - timedelta(days=i + 1, hours=ticket["resolution_hours"])
            closed_at = now - timedelta(days=i + 1)
            db.add(AnalyticsEvent(
                tenant_id=tenant.id,
                client_id=client_row.id,
                event_type="ticket.opened",
                object_type="ticket",
                object_id=object_id,
                metrics=json.dumps({}),
                source="seed_data",
                occurred_at=opened_at,
                idempotency_key=opened_key,
            ))
            db.add(AnalyticsEvent(
                tenant_id=tenant.id,
                client_id=client_row.id,
                event_type="ticket.closed",
                object_type="ticket",
                object_id=object_id,
                metrics=json.dumps({}),
                source="seed_data",
                occurred_at=closed_at,
                idempotency_key=closed_key,
            ))

        db.commit()
        print(f"Seeded analytics events for {client_name}: "
              f"{len(data['posts'])} posts, {len(data['tickets'])} ticket pairs")


def run_seed():
    db = SessionLocal()
    try:
        tenant = get_or_create_dev_tenant(db)

        for client_name, info in SEED_DATA.items():
            client_row = get_or_create_client(db, tenant.id, client_name)

            existing = (
                db.query(HashtagSet)
                .filter(
                    HashtagSet.tenant_id == tenant.id,
                    HashtagSet.client_id == client_row.id,
                    HashtagSet.platform == info["platform"],
                    HashtagSet.is_active == True,
                )
                .first()
            )

            if existing:
                print(f"Skipping {client_name} ({info['platform']}) — already seeded (set: {existing.id})")
                continue

            hashtag_set = HashtagSet(
                tenant_id=tenant.id,
                client_id=client_row.id,
                name=f"{client_name} {info['platform']} set",
                category=info["category"],
                platform=info["platform"],
                version=1,
                is_active=True,
            )
            db.add(hashtag_set)
            db.commit()
            db.refresh(hashtag_set)

            for tag in info["tags"]:
                db.add(HashtagItem(hashtag_set_id=hashtag_set.id, tag=tag))
            db.commit()

            print(f"Seeded {client_name} ({info['platform']}, {info['category']}): "
                  f"{len(info['tags'])} tags -> set {hashtag_set.id}")

        seed_analytics_events(db, tenant)

        print("\nSeeding complete.")

    finally:
        db.close()


if __name__ == "__main__":
    run_seed()