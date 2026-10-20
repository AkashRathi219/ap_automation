#!/usr/bin/env python3
"""
Gate 1 - Ingestion & Cryptographic Duplication Check (pre-AI, zero compute).

Action:     Calculate the SHA-256 hash of the uploaded PDF file.
Validation: Query the processed_invoices ledger for this hash.
Fail-fast:  If a hash match is found, the exact file was already processed ->
            FLAG (Exact File Duplicate) and terminate.

Standalone: python gate1_duplicate_check.py <invoice.pdf>
"""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "ap_automation.db"

FLAG_EXACT_DUPLICATE = "EXACT_FILE_DUPLICATE"


def file_sha256(pdf_path) -> str:
    """Streaming SHA-256 of the file bytes."""
    digest = hashlib.sha256()
    with open(pdf_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(pdf_path, db_path=None) -> dict:
    """Return gate verdict: {passed, flag, reason, sha256, prior_record}."""
    pdf_path = Path(pdf_path)
    db_path = DB_PATH if db_path is None else Path(db_path)
    sha256 = file_sha256(pdf_path)
    result = {"gate": "gate1_duplicate_check", "passed": True, "flag": None,
              "reason": None, "sha256": sha256, "prior_record": None}

    if not db_path.exists():
        result["reason"] = "database missing - run setup_db.py first"
        return result

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """SELECT id, file_name, invoice_id, vendor_id, status, processed_at
               FROM processed_invoices WHERE sha256 = ?""", (sha256,)).fetchone()
    finally:
        conn.close()

    if row:
        result["passed"] = False
        result["flag"] = FLAG_EXACT_DUPLICATE
        result["reason"] = (f"identical file already processed as '{row['file_name']}' "
                            f"(invoice {row['invoice_id']}, status {row['status']}, "
                            f"at {row['processed_at']})")
        result["prior_record"] = dict(row)
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python gate1_duplicate_check.py <invoice.pdf>")
    print(json.dumps(run(sys.argv[1]), indent=2, default=str))
