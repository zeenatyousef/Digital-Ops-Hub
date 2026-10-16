-- Fix DB-driven POS taxonomy rule to also match plural "receipts" (DEF-002, Esha)

BEGIN;

UPDATE ticket_taxonomy
SET rules_definition = to_json('{"combos": [["pos", "scan"], ["pos", "print"], ["scanner", "scan"], ["scanner", "print"], ["barcode", "scan"], ["barcode", "print"], ["receipt", "printer", "scan"], ["receipt", "printer", "print"], ["receipt", "print"], ["receipts", "print"], ["receipts", "scan"], ["receipts", "printer", "scan"], ["receipts", "printer", "print"]]}'::text)
WHERE category = 'POS not scanning/printing';

COMMIT;

SELECT category, rules_definition FROM ticket_taxonomy WHERE category = 'POS not scanning/printing';
