#!/usr/bin/env python3
"""
process_invoice.py - Fail-fast driver: runs ONE invoice PDF through Gates 1-5.

(No loop on purpose - add your own batch loop around this script later.)

    python process_invoice.py <invoice.pdf> [--no-move] [--json] [--db <path>]
                              [--processed-root <dir>] [--llm | --no-llm]

Flow:  Gate 1   duplicate hash check        -> stops if exact file duplicate
       Gate 2.1 vendor identity check       -> stops if unknown / inactive
                                               (text + vision LLM cross-check)
       Gate 2.2 header key-value extraction -> stops if PO missing
                                               (text + vision LLM cross-check)
       Gate 3   history dedup + PO checks   -> stops on duplicates / PO breach
       Gate 4   line items + integrity      -> stops on math / currency failure
       Gate 5   FX + threshold + routing    -> CLEARED / DUAL_APPROVAL

In normal mode every invoice (clean or flagged) gets a row in the
`processed_invoices` table and the PDF is moved into processed/<status>/ so
the inbox stays clean; --processed-root <dir> stages that tree elsewhere.
With --no-move the run is a true read-only dry run:
gates still run and the verdict is still reported, but nothing is written -
no ledger row, no history append, no processed/<status>/ folder, no file
move.
"""

import argparse
import datetime as dt
import json
import shutil
import sqlite3
import sys
import traceback
from pathlib import Path

import gate1_duplicate_check as gate1
import gate2a_vendor_identity as gate2a
import gate2b_key_value_extract as gate2b
import gate3_dedup_po_check as gate3
import gate4_line_integrity as gate4
import gate5_business_routing as gate5
import history_sync
import vision_llm

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "ap_automation.db"
PROCESSED_ROOT = BASE_DIR / "processed"

# Gate flag -> final pipeline status (= folder name, lowercased)
FLAG_TO_STATUS = {
    gate1.FLAG_EXACT_DUPLICATE:    "FLAGGED_EXACT_DUPLICATE",
    gate2a.FLAG_UNKNOWN_VENDOR:    "FLAGGED_UNKNOWN_VENDOR",
    gate2a.FLAG_INACTIVE_VENDOR:   "FLAGGED_INACTIVE_VENDOR",
    gate2b.FLAG_MISSING_PO:        "FLAGGED_MISSING_PO",
    gate3.FLAG_DUPLICATE_INVOICE:  "FLAGGED_DUPLICATE_INVOICE",
    gate3.FLAG_PO_LIMIT_BREACHED:  "FLAGGED_PO_LIMIT_BREACHED",
    gate3.FLAG_SUSPECTED_DUPLICATE: "FLAGGED_SUSPECTED_DUPLICATE",
    gate4.FLAG_DATA_INTEGRITY:     "FLAGGED_DATA_INTEGRITY",
    gate4.FLAG_CURRENCY_MISMATCH:  "FLAGGED_CURRENCY_MISMATCH",
    gate5.FLAG_THRESHOLD_BREACH:   "FLAGGED_THRESHOLD_BREACH",
    gate2a.FLAG_EXTRACTION_MISMATCH: "FLAGGED_EXTRACTION_MISMATCH",
    vision_llm.FLAG_LLM_UNAVAILABLE: "FLAGGED_LLM_UNAVAILABLE",
    vision_llm.FLAG_LLM_ERROR:       "FLAGGED_LLM_ERROR",
}
STATUS_PROCESSING_ERROR = "FLAGGED_PROCESSING_ERROR"
STATUS_EXACT_DUPLICATE = FLAG_TO_STATUS[gate1.FLAG_EXACT_DUPLICATE]


def print_gate(label: str, verdict: dict) -> None:
    mark = "PASS" if verdict.get("passed") else "FAIL"
    detail = verdict.get("reason") or ""
    print(f"[{label}] {mark}  {detail}")


def record_llm_status(record: dict, verdict: dict) -> None:
    """Copy the per-gate LLM check into the report-facing record fields.

    The extraction provenance wins over the preflight choice, because ask()
    may have switched to the fallback model after a load failure.
    """
    llm = verdict.get("llm") or {}
    vision = verdict.get("vision") or {}
    fields = vision.get("fields") or {}
    meta = fields.get("_meta") or {}
    if llm:
        actual = vision.get("status")
        record["llm_status"] = (actual if actual in {"disabled", "unavailable", "error"}
                                else llm.get("status"))
        record["llm_model"] = meta.get("model") or llm.get("model")


def record_result(db_path: Path, row: dict) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO processed_invoices
               (file_name, sha256, source_path, dest_path, processed_at, gate_reached,
                status, flag_reason, routed_to, invoice_id, invoice_date, po_number,
                vendor_id, vendor_name, currency, total_amount, amount_eur,
                fx_rate_used, requires_dual_approval, details_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row["file_name"], row["sha256"], row["source_path"], row["dest_path"],
             row["processed_at"], row["gate_reached"], row["status"], row["flag_reason"],
             row["routed_to"], row["invoice_id"], row["invoice_date"], row["po_number"],
             row["vendor_id"], row["vendor_name"], row["currency"], row["total_amount"],
             row["amount_eur"], row["fx_rate_used"], row["requires_dual_approval"],
             row["details_json"]))
        conn.commit()
    finally:
        conn.close()


def process(pdf_path: Path, move: bool = True, db_path=None,
            processed_root=None) -> dict:
    """Run one PDF through the gate sequence and return its result record."""
    db_path = DB_PATH if db_path is None else Path(db_path)
    now = dt.datetime.now().isoformat(timespec="seconds")
    verdicts = []
    record = {"file_name": pdf_path.name, "source_path": str(pdf_path),
              "processed_at": now, "gate_reached": "gate1", "status": None,
              "flag_reason": None, "routed_to": None, "invoice_id": None,
              "invoice_date": None, "po_number": None, "vendor_id": None,
              "vendor_name": None, "currency": None, "total_amount": None,
              "amount_eur": None, "fx_rate_used": None,
              "requires_dual_approval": None, "sha256": None,
              "llm_status": None, "llm_model": None,
              "dest_path": None, "details_json": None}

    # ---- Gate 1: cryptographic duplicate check --------------------------
    v1 = gate1.run(pdf_path, db_path=db_path)
    verdicts.append(v1)
    record["sha256"] = v1["sha256"]
    print_gate("Gate 1   duplicate hash   ", v1)
    if not v1["passed"]:
        record["gate_reached"] = "gate1"
        record["status"] = FLAG_TO_STATUS[v1["flag"]]
        record["flag_reason"] = v1["reason"]
        return finalize(record, verdicts, pdf_path, move, db_path=db_path,
                        processed_root=processed_root)

    # ---- Gate 2.1: vendor identity --------------------------------------
    v2a = gate2a.run(pdf_path, db_path=db_path)
    verdicts.append(v2a)
    record_llm_status(record, v2a)
    print_gate("Gate 2.1 vendor identity ", v2a)
    if not v2a["passed"]:
        record["gate_reached"] = "gate2.1"
        record["status"] = FLAG_TO_STATUS[v2a["flag"]]
        record["flag_reason"] = v2a["reason"]
        record["vendor_name"] = (v2a.get("identity") or {}).get("vendor_name_raw")
        return finalize(record, verdicts, pdf_path, move, db_path=db_path,
                        processed_root=processed_root)

    vendor = v2a["vendor"]
    record.update({"vendor_id": vendor["vendor_id"], "vendor_name": vendor["vendor_name"],
                   "requires_dual_approval": vendor["requires_dual_approval"]})

    # ---- Gate 2.2: header key-values ------------------------------------
    v2b = gate2b.run(pdf_path)
    verdicts.append(v2b)
    record_llm_status(record, v2b)
    print_gate("Gate 2.2 key-values      ", v2b)
    meta = v2b["metadata"]
    record.update({"invoice_id": meta.get("invoice_number"),
                   "invoice_date": meta.get("invoice_date"),
                   "po_number": meta.get("po_number"),
                   "currency": meta.get("currency"),
                   "total_amount": meta.get("total_amount")})
    if not v2b["passed"]:
        record["gate_reached"] = "gate2.2"
        record["status"] = FLAG_TO_STATUS[v2b["flag"]]
        record["flag_reason"] = v2b["reason"]
        return finalize(record, verdicts, pdf_path, move, db_path=db_path,
                        processed_root=processed_root)

    # ---- Gate 3: history dedup + PO validation --------------------------
    v3 = gate3.run(pdf_path, vendor=vendor, metadata=meta, db_path=db_path)
    verdicts.append(v3)
    print_gate("Gate 3   dedup / PO      ", v3)
    record["amount_eur"] = v3.get("amount_eur")
    if not v3["passed"]:
        record["gate_reached"] = "gate3"
        record["status"] = FLAG_TO_STATUS[v3["flag"]]
        record["flag_reason"] = v3["reason"]
        return finalize(record, verdicts, pdf_path, move, db_path=db_path,
                        processed_root=processed_root)

    # ---- Gate 4: line items + integrity ---------------------------------
    v4 = gate4.run(pdf_path, vendor=vendor, metadata=meta)
    verdicts.append(v4)
    print_gate("Gate 4   integrity       ", v4)
    if not v4["passed"]:
        record["gate_reached"] = "gate4"
        record["status"] = FLAG_TO_STATUS[v4["flag"]]
        record["flag_reason"] = v4["reason"]
        return finalize(record, verdicts, pdf_path, move, db_path=db_path,
                        processed_root=processed_root)

    # ---- Gate 5: FX, threshold, routing ---------------------------------
    v5 = gate5.run(pdf_path, vendor=vendor, metadata=meta)
    verdicts.append(v5)
    print_gate("Gate 5   routing         ", v5)
    record["gate_reached"] = "complete"
    record["status"] = v5["status"]
    record["routed_to"] = v5["routed_to"]
    record["flag_reason"] = None if v5["passed"] else v5["reason"]
    record["amount_eur"] = v5.get("amount_eur")
    record["fx_rate_used"] = v5.get("fx_rate")
    return finalize(record, verdicts, pdf_path, move, db_path=db_path,
                    processed_root=processed_root)


def finalize(record: dict, verdicts: list, pdf_path: Path, move: bool,
             db_path=None, processed_root=None) -> dict:
    """Persist the ledger row, append cross-batch history (FR-3), move the
    PDF to its status folder, and report.

    move=False is a true read-only dry run: the intended destination is
    still computed and reported, but no ledger row is written, no history
    is appended, and no folder is created or file moved.
    """
    db_path = DB_PATH if db_path is None else Path(db_path)
    if processed_root is None:
        processed_root = PROCESSED_ROOT
    else:
        processed_root = Path(processed_root)
    record["details_json"] = json.dumps(verdicts, default=str)
    record["dry_run"] = not move

    dest_dir = processed_root / record["status"].lower()
    dest = dest_dir / pdf_path.name
    record["dest_path"] = str(dest)

    if not move:
        record["ledger_note"] = "skipped: dry run (no ledger write)"
        record["history_sync"] = "skipped: dry run (no history append)"
        return record

    if record["status"] == STATUS_EXACT_DUPLICATE:
        # Gate 1: the sha256 already has a ledger row - that row IS the audit
        # trail, so we only route the file for review (no duplicate insert).
        record["ledger_note"] = "kept prior ledger row (sha256 unique)"
    else:
        record_result(db_path, record)
        # FR-3: terminal invoices join historic_invoices; a sync failure is
        # recorded as a note and must never break ledger writing or routing.
        try:
            sync = history_sync.sync_history(db_path, record)
            record["history_sync"] = (sync["reason"] if sync["synced"]
                                      else "skipped:" + sync["reason"])
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            record["history_sync"] = f"error:{exc}"

    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pdf_path), str(dest))
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="Process one invoice PDF through Gates 1-5.")
    parser.add_argument("pdf", help="Path to the invoice PDF")
    parser.add_argument("--no-move", action="store_true",
                        help="True read-only dry run: no ledger row, no history "
                             "append, no processed folder, no move")
    parser.add_argument("--json", action="store_true", help="Print the record as JSON")
    parser.add_argument("--db", default=None,
                        help="Path to an alternative SQLite database file (default: ap_automation.db next to this script)")
    parser.add_argument("--processed-root", default=None,
                        help="Directory for the processed/<status>/ output tree "
                             "(default: processed next to this script)")
    parser.add_argument("--llm", action=argparse.BooleanOptionalAction, default=None,
                        help="Enable/disable the vision LLM (default: enabled; "
                             "use --no-llm for intentional text-only mode)")
    args = parser.parse_args()

    if args.llm is not None:
        vision_llm.set_llm_enabled(args.llm)

    db_path = Path(args.db) if args.db else DB_PATH
    processed_root = Path(args.processed_root) if args.processed_root else None
    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        sys.exit(f"ERROR: file not found: {pdf_path}")
    if not db_path.exists():
        sys.exit(f"ERROR: {db_path.name} not found - run setup_db.py first")

    llm = vision_llm.check_llm()
    print(f"Vision LLM: {llm['status']}"
          + (f" ({llm['model']})" if llm.get("model") else ""))
    if llm.get("using_fallback"):
        print("  primary model unavailable; using the approved fallback")
    if llm["enabled"] and not llm["ok"]:
        print(f"WARNING: {llm.get('detail')} - Gate 2.1 will flag this invoice")

    print(f"Processing: {pdf_path.name}")
    try:
        record = process(pdf_path, move=not args.no_move, db_path=db_path,
                         processed_root=processed_root)
    except Exception as exc:  # defensive: never lose an invoice silently
        traceback.print_exc()
        record = {"file_name": pdf_path.name, "status": STATUS_PROCESSING_ERROR,
                  "flag_reason": f"pipeline error: {exc}",
                  "gate_reached": "error", "flag": None, "passed": False,
                  "sha256": gate1.file_sha256(pdf_path) if pdf_path.exists() else None,
                  "processed_at": dt.datetime.now().isoformat(timespec="seconds"),
                  "source_path": str(pdf_path), "dest_path": None,
                  "invoice_id": None, "invoice_date": None, "po_number": None,
                  "vendor_id": None, "vendor_name": None, "currency": None,
                  "total_amount": None, "amount_eur": None, "fx_rate_used": None,
                  "requires_dual_approval": None, "routed_to": None,
                  "llm_status": None, "llm_model": None,
                  "details_json": json.dumps({"error": str(exc)})}
        try:
            finalize(record, [], pdf_path, move=not args.no_move, db_path=db_path,
                     processed_root=processed_root)
        except Exception:
            traceback.print_exc()  # last resort: error is at least on stdout

    print(f"RESULT: {record['status']}"
          + (f" -> {record['routed_to']}" if record.get("routed_to") else ""))
    if args.json:
        print(json.dumps(record, indent=2, default=str))


if __name__ == "__main__":
    main()
