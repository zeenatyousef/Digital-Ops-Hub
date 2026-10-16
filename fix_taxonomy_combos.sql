-- Fix DB-driven taxonomy rules to close DEF-002 gaps (Esha's independent testing)
-- Adds: "logged in"/"logged into", "billed", and "records" variants

BEGIN;

UPDATE ticket_taxonomy
SET rules_definition = to_json('{"combos": [["password"], ["credential"], ["credentials"], ["login", "access"], ["reset", "my"], ["account", "locked"], ["locked", "out"], ["logged", "in"], ["logged", "into"]]}'::text)
WHERE category = 'Password reset/login access issue';

UPDATE ticket_taxonomy
SET rules_definition = to_json('{"combos": [["refund"], ["billing", "dispute"], ["payment", "promise"], ["charge", "me"], ["charged", "me"], ["money", "back"], ["reimburse"], ["reimbursement"], ["overcharged"], ["wrong", "amount"], ["billed"]]}'::text)
WHERE category = 'Refund/billing dispute';

UPDATE ticket_taxonomy
SET rules_definition = to_json('{"combos": [["delete", "data"], ["delete", "my", "data"], ["wipe", "database"], ["delete", "database"], ["remove", "all", "data"], ["erase", "data"], ["drop", "table"], ["remove", "all", "records"], ["delete", "records"], ["erase", "records"]]}'::text)
WHERE category = 'Request to delete/wipe data';

COMMIT;

-- Verify
SELECT category, rules_definition FROM ticket_taxonomy
WHERE category IN ('Password reset/login access issue', 'Refund/billing dispute', 'Request to delete/wipe data');
