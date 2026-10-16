-- Additional fix: combos required exact word "print", but message used "printing" 
-- (same word-form limitation as documented TC-051 gap). Add "printing" variants.

BEGIN;

UPDATE ticket_taxonomy
SET rules_definition = to_json('{"combos": [["pos", "scan"], ["pos", "print"], ["pos", "printing"], ["scanner", "scan"], ["scanner", "print"], ["barcode", "scan"], ["barcode", "print"], ["receipt", "printer", "scan"], ["receipt", "printer", "print"], ["receipt", "print"], ["receipts", "print"], ["receipts", "printing"], ["receipts", "scan"], ["receipts", "printer", "scan"], ["receipts", "printer", "print"]]}'::text)
WHERE category = 'POS not scanning/printing';

COMMIT;

SELECT category, rules_definition FROM ticket_taxonomy WHERE category = 'POS not scanning/printing';
