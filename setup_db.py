#!/usr/bin/env python3
"""
setup_db.py - Build the local SQLite database for the AP fail-fast pipeline.

Creates `ap_automation.db` (next to this script) and loads:
  * vendor_master      <- data/vendor_master.csv        (seed)
  * historic_invoices  <- data/historic_invoices.csv    (seed, used by Gate 1/3 dedup)
  * po_master          <- optional PO budget table      (used by Gate 3 validation 2)
  * processed_invoices <- results ledger written by the pipeline (Gate 1/3 query it)

Usage:
    python setup_db.py            # create/refresh seed data (keeps processed results)
    python setup_db.py --reset    # rebuild from scratch (DISCARDS processed results)
    python setup_db.py --db <path>  # build/refresh a database at a custom path
"""

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "ap_automation.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS vendor_master (
    vendor_id             TEXT PRIMARY KEY,
    vendor_name           TEXT NOT NULL,
    category              TEXT,
    payment_terms_days    INTEGER,
    approved_currency     TEXT,
    spend_threshold_eur   REAL,
    status                TEXT,
    country               TEXT,
    contact_email         TEXT,
    requires_dual_approval INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS historic_invoices (
    invoice_id        TEXT PRIMARY KEY,
    vendor_id         TEXT,
    vendor_name       TEXT,
    invoice_date      TEXT,
    amount_eur        REAL,
    currency          TEXT,
    status            TEXT,
    po_number         TEXT,
    payment_reference TEXT
);
CREATE INDEX IF NOT EXISTS idx_hist_vendor_amount ON historic_invoices (vendor_id, amount_eur);
CREATE INDEX IF NOT EXISTS idx_hist_po            ON historic_invoices (po_number);

-- Optional Purchase Order budget table (Gate 3, Validation 2 - PO overdraw).
-- The case-study dataset ships no PO budgets, so this table stays empty until
-- PO totals are synced from the ERP; the gate skips gracefully when no row exists.
CREATE TABLE IF NOT EXISTS po_master (
    po_number   TEXT PRIMARY KEY,
    vendor_id   TEXT,
    po_total_eur REAL,
    description TEXT
);

-- Results ledger: every processed invoice (clean or flagged) gets one row.
CREATE TABLE IF NOT EXISTS processed_invoices (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name             TEXT NOT NULL,
    sha256                TEXT NOT NULL UNIQUE,   -- Gate 1 duplicate key
    source_path           TEXT,
    dest_path             TEXT,
    processed_at          TEXT NOT NULL,
    gate_reached          TEXT,
    status                TEXT NOT NULL,          -- final routing status (folder name source)
    flag_reason           TEXT,
    routed_to             TEXT,
    invoice_id            TEXT,
    invoice_date          TEXT,
    po_number             TEXT,
    vendor_id             TEXT,
    vendor_name           TEXT,
    currency              TEXT,
    total_amount          REAL,
    amount_eur            REAL,
    fx_rate_used          REAL,
    requires_dual_approval INTEGER,
    details_json          TEXT                    -- full per-gate evidence trail
);
CREATE INDEX IF NOT EXISTS idx_processed_vendor ON processed_invoices (vendor_id);
CREATE INDEX IF NOT EXISTS idx_processed_status  ON processed_invoices (status);
"""


def resolve_csv(name: str, explicit: str | None) -> Path:
    """Find a source CSV: CLI arg > ./data/<name> > ../ap-automation-assessment/<name>."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(BASE_DIR / "data" / name)
    candidates.append(BASE_DIR.parent / "ap-automation-assessment" / name)
    for c in candidates:
        if c.is_file():
            return c
    sys.exit(f"ERROR: could not find {name}. Looked in: "
             + ", ".join(str(c) for c in candidates))


def load_vendor_master(conn: sqlite3.Connection, csv_path: Path) -> int:
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    conn.executemany(
        """INSERT INTO vendor_master
           (vendor_id, vendor_name, category, payment_terms_days, approved_currency,
            spend_threshold_eur, status, country, contact_email, requires_dual_approval)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(vendor_id) DO UPDATE SET
               vendor_name=excluded.vendor_name, category=excluded.category,
               payment_terms_days=excluded.payment_terms_days,
               approved_currency=excluded.approved_currency,
               spend_threshold_eur=excluded.spend_threshold_eur,
               status=excluded.status, country=excluded.country,
               contact_email=excluded.contact_email,
               requires_dual_approval=excluded.requires_dual_approval""",
        [(r["vendor_id"], r["vendor_name"], r["category"], int(r["payment_terms_days"]),
          r["approved_currency"], float(r["spend_threshold_eur"]), r["status"],
          r["country"], r["contact_email"],
          1 if r["requires_dual_approval"].strip().upper() == "TRUE" else 0)
         for r in rows],
    )
    return len(rows)


def load_historic_invoices(conn: sqlite3.Connection, csv_path: Path) -> int:
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    conn.executemany(
        """INSERT INTO historic_invoices
           (invoice_id, vendor_id, vendor_name, invoice_date, amount_eur,
            currency, status, po_number, payment_reference)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(invoice_id) DO UPDATE SET
               vendor_id=excluded.vendor_id, vendor_name=excluded.vendor_name,
               invoice_date=excluded.invoice_date, amount_eur=excluded.amount_eur,
               currency=excluded.currency, status=excluded.status,
               po_number=excluded.po_number, payment_reference=excluded.payment_reference""",
        [(r["invoice_id"], r["vendor_id"], r["vendor_name"], r["invoice_date"],
          float(r["amount_eur"]), r["currency"], r["status"],
          r["po_number"], r["payment_reference"])
         for r in rows],
    )
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build/refresh the AP SQLite database.")
    parser.add_argument("--vendor-csv", help="Path to vendor_master.csv")
    parser.add_argument("--historic-csv", help="Path to historic_invoices.csv")
    parser.add_argument("--db", help="Path to the SQLite database file (default: ap_automation.db next to this script)")
    parser.add_argument("--reset", action="store_true",
                        help="Delete and rebuild the database (discards processed results)")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else DB_PATH
    if args.reset and db_path.exists():
        db_path.unlink()
        print(f"Removed {db_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    vendor_csv = resolve_csv("vendor_master.csv", args.vendor_csv)
    historic_csv = resolve_csv("historic_invoices.csv", args.historic_csv)

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        n_vendors = load_vendor_master(conn, vendor_csv)
        n_hist = load_historic_invoices(conn, historic_csv)
        conn.commit()

        n_proc = conn.execute("SELECT COUNT(*) FROM processed_invoices").fetchone()[0]
        n_po = conn.execute("SELECT COUNT(*) FROM po_master").fetchone()[0]
        print(f"Database ready: {db_path}")
        print(f"  vendor_master      : {n_vendors} rows  <- {vendor_csv}")
        print(f"  historic_invoices  : {n_hist} rows  <- {historic_csv}")
        print(f"  po_master          : {n_po} rows  (optional PO budgets)")
        print(f"  processed_invoices : {n_proc} rows  (results ledger)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
