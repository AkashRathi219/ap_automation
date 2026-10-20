#!/usr/bin/env python3
"""
Gate 3 - Metadata Deduplication & PO Validation (zero AI).

Cross-references Gate 2 metadata against the SQLite historical_invoices table.

Validation 1 (Exact match):      Vendor ID + Invoice Amount already exists
                                 -> FLAG (Duplicate Invoice), attach history.
Validation 2 (PO overdraw):      PO Total - Historical Paid - Current Total < 0
                                 -> FLAG (PO Limit Breached).
                                 (Needs PO budgets in `po_master`; skipped when
                                 the ERP has not supplied a budget for the PO.)
Validation 3 (Heuristic dup):    Same Total Amount + same PO, different invoice
                                 number -> FLAG (Suspected Duplicate).

Standalone: python gate3_dedup_po_check.py <invoice.pdf>
            (re-runs Gate 2a/2.2 extraction to obtain the needed context)
"""

import json
import sqlite3
import sys
from pathlib import Path

from gate2a_vendor_identity import match_vendor
from gate2b_key_value_extract import extract_metadata

DB_PATH = Path(__file__).resolve().parent / "ap_automation.db"

AMOUNT_TOLERANCE = 0.01
# Offline fallback FX rates (Gate 5 prefers the live API; these keep the
# historical EUR comparisons deterministic when no rate is reachable).
FALLBACK_FX_TO_EUR = {"EUR": 1.0, "GBP": 1.17, "USD": 0.92, "CHF": 1.06}

FLAG_DUPLICATE_INVOICE = "DUPLICATE_INVOICE"
FLAG_PO_LIMIT_BREACHED = "PO_LIMIT_BREACHED"
FLAG_SUSPECTED_DUPLICATE = "SUSPECTED_DUPLICATE"


def to_eur(amount, currency) -> float:
    return float(amount) * FALLBACK_FX_TO_EUR.get((currency or "EUR").upper(), 1.0)


def run(pdf_path, vendor=None, metadata=None, db_path=None) -> dict:
    """Return gate verdict; vendor/metadata come from Gate 2 when available."""
    db_path = DB_PATH if db_path is None else Path(db_path)
    result = {"gate": "gate3_dedup_po_check", "passed": True, "flag": None,
              "reason": None, "checks": {}}

    if metadata is None:
        metadata = extract_metadata(pdf_path)
    if vendor is None:
        info = match_vendor(pdf_path, db_path=db_path)
        vendor = info["vendor"]

    if vendor is None:
        result["reason"] = "no matched vendor - Gate 2.1 must run/pass first"
        return result
    if metadata.get("total_amount") is None:
        result["reason"] = "no total amount extracted - cannot deduplicate"
        return result

    vendor_id = vendor["vendor_id"]
    invoice_id = metadata.get("invoice_number")
    po_number = metadata.get("po_number")
    currency = metadata.get("currency") or vendor["approved_currency"]
    amount_eur = round(to_eur(metadata["total_amount"], currency), 2)
    result["amount_eur"] = amount_eur

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # Validation 1 - exact vendor + amount duplicate ------------------
        dup = conn.execute(
            """SELECT invoice_id, invoice_date, amount_eur, po_number, status
               FROM historic_invoices
               WHERE vendor_id = ? AND ABS(amount_eur - ?) < ?""",
            (vendor_id, amount_eur, AMOUNT_TOLERANCE)).fetchone()
        result["checks"]["exact_duplicate"] = bool(dup)
        if dup:
            result.update({"passed": False, "flag": FLAG_DUPLICATE_INVOICE,
                           "reason": (f"vendor {vendor_id} + amount {amount_eur} EUR "
                                      f"already exists as {dup['invoice_id']}")})
            result["prior_record"] = dict(dup)
            return result

        # Validation 2 - PO overdraw --------------------------------------
        if po_number:
            paid = conn.execute(
                """SELECT COALESCE(SUM(amount_eur), 0) AS paid
                   FROM historic_invoices WHERE po_number = ?""", (po_number,)).fetchone()["paid"]
            budget_row = conn.execute(
                "SELECT po_total_eur FROM po_master WHERE po_number = ?", (po_number,)).fetchone()
            result["checks"]["po_historical_paid_eur"] = round(paid, 2)
            if budget_row and budget_row["po_total_eur"] is not None:
                remaining = budget_row["po_total_eur"] - paid - amount_eur
                result["checks"]["po_remaining_eur"] = round(remaining, 2)
                if remaining < 0:
                    result.update({"passed": False, "flag": FLAG_PO_LIMIT_BREACHED,
                                   "reason": (f"PO {po_number} budget "
                                              f"{budget_row['po_total_eur']} EUR exhausted "
                                              f"(paid {paid:.2f} + current {amount_eur})")})
                    return result
            else:
                result["checks"]["po_budget"] = "not on file - overdraw check skipped"

        # Validation 3 - heuristic duplicate (same PO + amount, other id) --
        twin = conn.execute(
            """SELECT invoice_id, invoice_date, amount_eur, status
               FROM historic_invoices
               WHERE po_number = ? AND ABS(amount_eur - ?) < ? AND invoice_id <> ?""",
            (po_number, amount_eur, AMOUNT_TOLERANCE, invoice_id)).fetchone()
        result["checks"]["heuristic_duplicate"] = bool(twin)
        if twin:
            result.update({"passed": False, "flag": FLAG_SUSPECTED_DUPLICATE,
                           "reason": (f"same PO {po_number} + amount {amount_eur} EUR as "
                                      f"{twin['invoice_id']} but different invoice number "
                                      f"({invoice_id}) - possible re-issue")})
            result["prior_record"] = dict(twin)
            return result
    finally:
        conn.close()

    result["reason"] = ("no historical duplicates; "
                        + result["checks"].get("po_budget", "PO checks clean"))
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python gate3_dedup_po_check.py <invoice.pdf>")
    print(json.dumps(run(sys.argv[1]), indent=2, default=str))
