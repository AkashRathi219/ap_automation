#!/usr/bin/env python3
"""
Gate 4 - Deep Table Extraction & Data Integrity (heavy compute, line items).

Action:     Map the line-item grid: Description, Qty, Unit Price, Subtotal,
            VAT and currency, then run the integrity checks.
Validation 1 (Mathematical cross-check): sum(qty * unit price) == subtotal
            and subtotal + VAT == total (cent tolerance).
Validation 2 (Currency integrity): extracted currency must equal the vendor's
            approved_currency in vendor_master.
Fail-fast:  Math failure or unapproved currency -> FLAG (Data Integrity /
            Currency Mismatch).

Standalone: python gate4_line_integrity.py <invoice.pdf>
            (re-runs Gate 2 extraction to obtain metadata/vendor context)
"""

import json
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

from gate2a_vendor_identity import match_vendor
from gate2b_key_value_extract import extract_metadata

MATH_TOLERANCE = 0.02  # cent-level rounding tolerance

FLAG_DATA_INTEGRITY = "DATA_INTEGRITY_FAILURE"
FLAG_CURRENCY_MISMATCH = "CURRENCY_MISMATCH"

_HEADER_KEYWORDS = re.compile(r"\b(Description|Qty|Unit|Amount)\b")
_NUMERIC_LINE = re.compile(r"^\s*[€$£]?\s*\d[\d,]*(?:\.\d+)?\s*$")


def _page_lines(pdf_path):
    with fitz.open(pdf_path) as doc:
        raw = "\n".join(page.get_text() for page in doc)
    return [ln.strip() for ln in raw.splitlines()]


def parse_amount(text):
    if text is None:
        return None
    cleaned = re.sub(r"[^\d,.\-]", "", str(text)).replace(",", "")
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def extract_line_items(pdf_path) -> dict:
    """Parse the Description/Qty/Unit-Price/Amount grid from the text layer."""
    lines = _page_lines(pdf_path)

    start = next((i for i, ln in enumerate(lines)
                  if ln.lower().startswith("description")), None)
    items, anomalies = [], []
    if start is None:
        return {"line_items": [], "anomalies": ["no Description table header found"]}

    i = start
    while i < len(lines) and _HEADER_KEYWORDS.search(lines[i]):
        i += 1  # skip header lines (Qty / Unit Price ... / Amount)
    while i < len(lines):
        line = lines[i]
        if line.lower().startswith("subtotal") or "IBAN" in line:
            break
        if not line or not _NUMERIC_LINE.match(line):
            if line:
                items.append({"description": line, "numbers": []})
        elif items:
            items[-1]["numbers"].append(parse_amount(line))
        i += 1

    rows = []
    for item in items:
        nums = item["numbers"]
        if len(nums) == 3:
            rows.append({"description": item["description"], "qty": nums[0],
                         "unit_price": nums[1], "amount": nums[2]})
        else:
            anomalies.append(f"unparsed table row: '{item['description']}' "
                             f"({len(nums)} numeric cells, expected 3)")
    return {"line_items": rows, "anomalies": anomalies}


def run(pdf_path, vendor=None, metadata=None) -> dict:
    """Return gate verdict with line items and per-check evidence."""
    result = {"gate": "gate4_line_integrity", "passed": True, "flag": None,
              "reason": None, "checks": {}}

    if metadata is None:
        metadata = extract_metadata(pdf_path)
    if vendor is None:
        vendor = match_vendor(pdf_path)["vendor"]

    table = extract_line_items(pdf_path)
    rows, checks = table["line_items"], result["checks"]
    result["line_items"] = rows
    result["anomalies"] = table["anomalies"]
    checks["rows_extracted"] = len(rows)

    problems = list(table["anomalies"])

    # -- Validation 1: mathematical cross-check ---------------------------
    if rows:
        line_errors = [r["description"] for r in rows
                       if abs(r["qty"] * r["unit_price"] - r["amount"]) > MATH_TOLERANCE]
        computed_total = round(sum(r["amount"] for r in rows), 2)
        checks["sum_line_amounts"] = computed_total
        checks["subtotal"] = metadata.get("subtotal")
        checks["total_amount"] = metadata.get("total_amount")
        if line_errors:
            problems.append("qty*price != amount for: " + "; ".join(line_errors))
        if metadata.get("subtotal") is not None and \
                abs(computed_total - metadata["subtotal"]) > MATH_TOLERANCE:
            problems.append(f"sum of lines {computed_total} != subtotal "
                            f"{metadata['subtotal']}")
        if None not in (metadata.get("subtotal"), metadata.get("vat_amount"),
                        metadata.get("total_amount")):
            recomputed = round(metadata["subtotal"] + metadata["vat_amount"], 2)
            checks["recomputed_total"] = recomputed
            if abs(recomputed - metadata["total_amount"]) > MATH_TOLERANCE:
                problems.append(f"subtotal+VAT {recomputed} != total "
                                f"{metadata['total_amount']}")
    else:
        problems.append("no line items could be extracted")

    # -- Validation 2: currency integrity ---------------------------------
    currency = metadata.get("currency")
    approved = vendor.get("approved_currency") if vendor else None
    checks["currency"] = currency
    checks["approved_currency"] = approved
    if currency and approved and currency != approved:
        problems.append(f"invoice currency {currency} not approved "
                        f"for vendor ({approved})")
        result["flag"] = FLAG_CURRENCY_MISMATCH
    elif currency and approved:
        result["currency"] = currency

    if problems:
        result["passed"] = False
        result["flag"] = result["flag"] or FLAG_DATA_INTEGRITY
        result["reason"] = "; ".join(problems)
    else:
        result["reason"] = (f"{len(rows)} line items OK; subtotal+VAT==total; "
                            f"currency {currency} approved")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python gate4_line_integrity.py <invoice.pdf>")
    print(json.dumps(run(sys.argv[1]), indent=2, default=str))
