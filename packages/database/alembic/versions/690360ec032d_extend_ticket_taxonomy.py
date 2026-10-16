"""extend_ticket_taxonomy

Revision ID: 690360ec032d
Revises: b28f73d47690
Create Date: 2026-08-23 20:54:59.830117

"""
from typing import Sequence, Union
import json
import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '690360ec032d'
down_revision: Union[str, Sequence[str], None] = 'b28f73d47690'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add columns to ticket_taxonomy
    op.add_column('ticket_taxonomy', sa.Column('product', sa.String(length=255), nullable=True))
    op.add_column('ticket_taxonomy', sa.Column('severity', sa.String(length=50), nullable=True))
    op.add_column('ticket_taxonomy', sa.Column('owner_team', sa.String(length=255), nullable=True))
    op.add_column('ticket_taxonomy', sa.Column('human_required', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('ticket_taxonomy', sa.Column('rules_definition', sa.JSON(), nullable=True))
    op.add_column('ticket_taxonomy', sa.Column('priority', sa.Integer(), nullable=False, server_default='100'))

    # Make new columns NOT NULL now that default or nullable is handled
    # Since SQLite doesn't support changing nullable directly without recreate, we'll keep them nullable in DB
    # but required at ORM layer. This is safe and standard for SQLite migrations.

    # Seed initial rules for both the benchmark tenant and the default tenant (if they exist)
    bind = op.get_bind()
    tenant_ids = []
    for t_id in [
        "d5de8b4d-b089-4d4e-9283-fd952f8df783", # Vishaqa benchmark tenant
        "00000000-0000-0000-0000-00000000000a"  # National Wireless tenant
    ]:
        res = bind.execute(sa.text("SELECT id FROM tenants WHERE id = :tid"), {"tid": t_id}).fetchone()
        if res:
            tenant_ids.append(t_id)

    seed_rules = [
        # Guardrails
        {
            "category": "Suspected security incident/breach",
            "product": "Security",
            "severity": "Critical",
            "owner_team": "Security/Admin",
            "confidence_threshold": 0.95,
            "human_required": True,
            "priority": 10,
            "rules_definition": {
                "combos": [
                    ["hacked"], ["hack"], ["breach"], ["breached"],
                    ["security", "incident"], ["unauthorized", "access"], ["compromised"]
                ]
            }
        },
        {
            "category": "Password reset/login access issue",
            "product": "Security",
            "severity": "High",
            "owner_team": "Security/Admin",
            "confidence_threshold": 0.9,
            "human_required": True,
            "priority": 20,
            "rules_definition": {
                "combos": [
                    ["password"], ["credential"], ["credentials"],
                    ["login", "access"], ["reset", "my"], ["account", "locked"], ["locked", "out"]
                ]
            }
        },
        {
            "category": "Request to delete/wipe data",
            "product": "Destructive Action",
            "severity": "Critical",
            "owner_team": "Admin/DB Owner",
            "confidence_threshold": 0.95,
            "human_required": True,
            "priority": 30,
            "rules_definition": {
                "combos": [
                    ["delete", "data"], ["delete", "my", "data"], ["wipe", "database"],
                    ["delete", "database"], ["remove", "all", "data"], ["erase", "data"], ["drop", "table"]
                ]
            }
        },
        {
            "category": "Refund/billing dispute",
            "product": "Financial",
            "severity": "High",
            "owner_team": "Account Manager",
            "confidence_threshold": 0.9,
            "human_required": True,
            "priority": 40,
            "rules_definition": {
                "combos": [
                    ["refund"], ["billing", "dispute"], ["payment", "promise"], ["charge", "me"],
                    ["charged", "me"], ["money", "back"], ["reimburse"], ["reimbursement"],
                    ["overcharged"], ["wrong", "amount"]
                ]
            }
        },
        {
            "category": "Critical production system down",
            "product": "Production Outage",
            "severity": "Critical",
            "owner_team": "Director/Escalation",
            "confidence_threshold": 0.9,
            "human_required": True,
            "priority": 50,
            "rules_definition": {
                "combos": [
                    ["production", "down"], ["system", "down"], ["everything", "down"],
                    ["site", "down"], ["service", "down"], ["completely", "down"],
                    ["outage"], ["completely", "blocked"], ["invoice", "blocked"], ["entire", "down"]
                ],
                "phrases": ["not working at all"]
            }
        },
        # FBR Digital Invoicing
        {
            "category": "Slow invoice processing",
            "product": "FBR Digital Invoicing",
            "severity": "Medium",
            "owner_team": "Oracle Support",
            "confidence_threshold": 0.8,
            "human_required": False,
            "priority": 60,
            "rules_definition": {
                "combos": [
                    ["fbr", "slow"], ["ora-", "slow"], ["invoice", "slow"], ["invoices", "slow"]
                ]
            }
        },
        {
            "category": "Invoice data mismatch/validation error",
            "product": "FBR Digital Invoicing",
            "severity": "High",
            "owner_team": "Oracle/FBR Integration Support",
            "confidence_threshold": 0.85,
            "human_required": False,
            "priority": 70,
            "rules_definition": {
                "combos": [
                    ["fbr", "mismatch"], ["fbr", "validation"], ["ora-", "mismatch"],
                    ["ora-", "validation"], ["invoice", "mismatch"], ["invoice", "validation"],
                    ["invoices", "mismatch"], ["invoices", "validation"]
                ]
            }
        },
        {
            "category": "Invoice won't post/gateway error",
            "product": "FBR Digital Invoicing",
            "severity": "Critical",
            "owner_team": "Oracle/FBR Integration Support",
            "confidence_threshold": 0.9,
            "human_required": False,
            "priority": 80,
            "rules_definition": {
                "combos": [
                    ["fbr"], ["ora-"], ["invoice"], ["invoices"]
                ]
            }
        },
        # POS
        {
            "category": "POS not scanning/printing",
            "product": "POS",
            "severity": "High",
            "owner_team": "POS Product Support",
            "confidence_threshold": 0.85,
            "human_required": False,
            "priority": 90,
            "rules_definition": {
                "combos": [
                    ["pos", "scan"], ["pos", "print"], ["scanner", "scan"], ["scanner", "print"],
                    ["barcode", "scan"], ["barcode", "print"], ["receipt", "printer", "scan"],
                    ["receipt", "printer", "print"], ["receipt", "print"]
                ]
            }
        },
        {
            "category": "POS device offline",
            "product": "POS",
            "severity": "Medium",
            "owner_team": "POS Product Support",
            "confidence_threshold": 0.8,
            "human_required": False,
            "priority": 100,
            "rules_definition": {
                "combos": [
                    ["pos", "offline"], ["scanner", "offline"], ["barcode", "offline"],
                    ["receipt", "printer", "offline"], ["receipt", "print", "offline"]
                ]
            }
        },
        {
            "category": "New user setup/how-to question",
            "product": "POS",
            "severity": "Low",
            "owner_team": "POS Product Support",
            "confidence_threshold": 0.75,
            "human_required": False,
            "priority": 110,
            "rules_definition": {
                "combos": [
                    ["pos"], ["scanner"], ["barcode"], ["receipt", "printer"], ["receipt", "print"]
                ]
            }
        },
        # Website
        {
            "category": "Site completely down",
            "product": "Website",
            "severity": "Critical",
            "owner_team": "Web Lead",
            "confidence_threshold": 0.9,
            "human_required": False,
            "priority": 56,
            "rules_definition": {
                "combos": [
                    ["checkout", "down"], ["payment error", "down"], ["website", "down"], ["site", "down"]
                ],
                "exclusions": ["downloads", "download", "simultaneously", "complaints", "client-facing"]
            }
        },
        {
            "category": "Checkout/payment error",
            "product": "Website",
            "severity": "High",
            "owner_team": "Web Lead",
            "confidence_threshold": 0.85,
            "human_required": False,
            "priority": 130,
            "rules_definition": {
                "combos": [
                    ["checkout"], ["payment"], ["payment error"]
                ]
            }
        },
        {
            "category": "Minor design/UI bug",
            "product": "Website",
            "severity": "Low",
            "owner_team": "Web Lead",
            "confidence_threshold": 0.7,
            "human_required": False,
            "priority": 140,
            "rules_definition": {
                "combos": [
                    ["checkout"], ["website"], ["site"], ["homepage"], ["banner"], ["alignment"], ["layout"]
                ],
                "exclusions": ["downloads", "download", "simultaneously", "complaints", "client-facing"],
                "phrases": ["payment error"]
            }
        },
        # Hosting
        {
            "category": "Server down",
            "product": "Hosting",
            "severity": "Critical",
            "owner_team": "Web Lead",
            "confidence_threshold": 0.9,
            "human_required": False,
            "priority": 55,
            "rules_definition": {
                "combos": [
                    ["hosting", "down"], ["server", "down"]
                ],
                "exclusions": ["downloads", "download", "simultaneously", "complaints", "client-facing"]
            }
        },
        {
            "category": "Slow server response",
            "product": "Hosting",
            "severity": "Medium",
            "owner_team": "Web Lead",
            "confidence_threshold": 0.75,
            "human_required": False,
            "priority": 160,
            "rules_definition": {
                "combos": [
                    ["hosting"], ["server"]
                ]
            }
        },
        # Marketing/Social
        {
            "category": "Correction/scheduling issue",
            "product": "Marketing/Social",
            "severity": "Medium",
            "owner_team": "Marketing Lead",
            "confidence_threshold": 0.7,
            "human_required": False,
            "priority": 170,
            "rules_definition": {
                "combos": [
                    ["poster"], ["social"], ["post"]
                ]
            }
        }
    ]

    # Convert tenant ID strings to UUID objects for databases that enforce UUID type natively
    # And convert rules_definition to JSON string if bulk_insert doesn't handle dict cleanly
    rows = []
    for t_id in tenant_ids:
        for r in seed_rules:
            row = r.copy()
            row["id"] = str(uuid.uuid4())
            row["tenant_id"] = t_id
            row["rules_definition"] = json.dumps(row["rules_definition"])
            rows.append(row)

    # Bulk insert rows
    if rows:
        op.bulk_insert(
            sa.table('ticket_taxonomy',
                sa.column('id', sa.String),
                sa.column('tenant_id', sa.String),
                sa.column('category', sa.String),
                sa.column('confidence_threshold', sa.Float),
                sa.column('product', sa.String),
                sa.column('severity', sa.String),
                sa.column('owner_team', sa.String),
                sa.column('human_required', sa.Boolean),
                sa.column('rules_definition', sa.JSON),
                sa.column('priority', sa.Integer)
            ),
            rows
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Delete seeded rows
    op.execute("DELETE FROM ticket_taxonomy WHERE tenant_id IN ('d5de8b4d-b089-4d4e-9283-fd952f8df783', '00000000-0000-0000-0000-00000000000a')")

    # Drop columns
    op.drop_column('ticket_taxonomy', 'priority')
    op.drop_column('ticket_taxonomy', 'rules_definition')
    op.drop_column('ticket_taxonomy', 'human_required')
    op.drop_column('ticket_taxonomy', 'owner_team')
    op.drop_column('ticket_taxonomy', 'severity')
    op.drop_column('ticket_taxonomy', 'product')
