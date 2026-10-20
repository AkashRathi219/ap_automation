#!/usr/bin/env python3
"""
history_sync.py - Append terminal invoices to the cross-batch dedup history.

Implements SPEC FR-3 (Phase 2 batch processing): every invoice that finishes
the gate sequence with an appendable terminal status gains exactly one
`historic_invoices` row, so Gate 3 duplicate checks recognize it across
separate batch runs. Invoices flagged as FLAGGED_EXACT_DUPLICATE at Gate 1
and early gate flags (Gate 2.x / Gate 3 / Gate 4, OQ-1 default) never append.

Record -> historic_invoices column mapping (extra record keys are ignored):

    invoice_id        <- record["invoice_id"]      (required, PRIMARY KEY)
    vendor_id         <- record["vendor_id"]       (required)
    amount_eur        <- record["amount_eur"]      (required, numeric)
    status            <- record["status"]          (must be in APPEND_STATUSES)
    vendor_name       <- record.get("vendor_name")   (default "")
    invoice_date      <- record.get("invoice_date")  (default "")
    currency          <- record.get("currency")      (default "")
    po_number         <- record.get("po_number")     (default "")
    payment_reference <- (not present in pipeline records; default "")

Records with a missing/non-numeric required field are skipped, not crashed
on; an already-present invoice_id is absorbed by INSERT OR IGNORE.

CLI:
    python history_sync.py --db <path> --record <record.json>
      prints exactly:  HISTORY_SYNC SYNCED <invoice_id>
                   or: HISTORY_SYNC SKIPPED <reason>
"""

import argparse
import json
import sqlite3
from pathlib import Path

APPEND_STATUSES = {"CLEARED_STANDARD", "DUAL_APPROVAL", "FLAGGED_THRESHOLD_BREACH"}

_REQUIRED_FIELDS = ("invoice_id", "vendor_id", "amount_eur")

_INSERT_SQL = """
INSERT OR IGNORE INTO historic_invoices
    (invoice_id, vendor_id, vendor_name, invoice_date, amount_eur,
     currency, status, po_number, payment_reference)
VALUES (?,?,?,?,?,?,?,?,?)
"""


def _missing_fields(record: dict) -> list:
    missing = []
    for name in _REQUIRED_FIELDS:
        value = record.get(name)
        if value is None:
            missing.append(name)
        elif name == "amount_eur":
            try:
                float(value)
            except (TypeError, ValueError):
                missing.append(name)
    return missing


def sync_history(db_path: Path, record: dict) -> dict:
    """Insert one historic_invoices row. Returns {"synced": bool, "reason": str}."""
    missing = _missing_fields(record)
    if missing:
        return {"synced": False, "reason": "missing_fields:" + ",".join(missing)}
    status = record.get("status")
    if status not in APPEND_STATUSES:
        return {"synced": False, "reason": f"status_not_appendable:{status}"}

    row = (record["invoice_id"], record["vendor_id"], record.get("vendor_name") or "",
           record.get("invoice_date") or "", float(record["amount_eur"]),
           record.get("currency") or "", status, record.get("po_number") or "", "")
    conn = sqlite3.connect(Path(db_path))
    try:
        cur = conn.execute(_INSERT_SQL, row)
        conn.commit()
    finally:
        conn.close()
    if cur.rowcount == 0:
        return {"synced": False, "reason": "duplicate_invoice_id"}
    return {"synced": True, "reason": "appended"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Append one appendable invoice record to historic_invoices (FR-3).")
    parser.add_argument("--db", required=True, help="Path to the SQLite database")
    parser.add_argument("--record", required=True, help="Path to a JSON record file")
    args = parser.parse_args()

    with open(args.record, encoding="utf-8") as fh:
        record = json.load(fh)
    result = sync_history(Path(args.db), record)
    if result["synced"]:
        print(f"HISTORY_SYNC SYNCED {record['invoice_id']}")
    else:
        print(f"HISTORY_SYNC SKIPPED {result['reason']}")


if __name__ == "__main__":
    main()
