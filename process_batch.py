#!/usr/bin/env python3
"""
process_batch.py - Phase 2 sequential batch driver (FR-1, FR-2, FR-4, FR-5).

Scans --input for PDFs and runs each one through process_invoice.process()
(Gates 1-5, ledger row, history sync and routing all live there - nothing is
duplicated here). A crash on ONE file becomes a FLAGGED_PROCESSING_ERROR
result (FR-2) and the batch continues. Every run writes the FR-4 audit
report to batch_reports/ and prints a stdout summary table.

    python process_batch.py [--input <dir>] [--no-move] [--db <path>]
                            [--processed-root <dir>] [--limit N] [--json]
                            [--llm | --no-llm]

--no-move is a true read-only dry run: gates still run and the verdict is
still reported, the PDFs stay in the input dir, and nothing is written -
no ledger row, no history append, no processed/<status>/ folder, no file
move; the FR-4 report is still written, tagged dry_run=true.
--processed-root routes the processed/<status>/ tree of non-dry runs into
an alternative directory (default: processed next to this script);
--no-llm switches the vision LLM off for an intentional text-only run;
--limit N processes at most N files (N<=0 or omitted = no cap).
"""

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import batch_report
import gate1_duplicate_check as gate1
import process_invoice
import vision_llm

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "invoices"
REPORT_DIR = BASE_DIR / "batch_reports"


def build_queue(in_dir: Path, limit: int | None = None) -> list[Path]:
    """Return the *.pdf files in in_dir (case-insensitive) sorted by name,
    capped at `limit` entries when limit is a positive int."""
    in_dir = Path(in_dir)
    entries = sorted(in_dir.iterdir(), key=lambda p: p.name.lower())
    pdfs = [p for p in entries if p.is_file() and p.suffix.lower() == ".pdf"]
    for path in entries:
        if path.is_file() and path.suffix.lower() != ".pdf":
            print(f"WARNING: skipping non-PDF file: {path.name}")
    if limit is not None and limit > 0:
        pdfs = pdfs[:limit]
    return pdfs


def error_record(pdf_path: Path, exc: Exception) -> dict:
    """FR-2: minimal FLAGGED_PROCESSING_ERROR row for a file that crashed
    inside process(); every extraction field stays NULL."""
    try:
        sha256 = gate1.file_sha256(pdf_path)
    except Exception:
        sha256 = ""
    return {"file_name": pdf_path.name, "source_path": str(pdf_path),
            "sha256": sha256,
            "processed_at": dt.datetime.now().isoformat(timespec="seconds"),
            "gate_reached": "driver",
            "status": process_invoice.STATUS_PROCESSING_ERROR,
            "flag_reason": repr(exc),
            "routed_to": None, "dest_path": None,
            "invoice_id": None, "invoice_date": None, "po_number": None,
            "vendor_id": None, "vendor_name": None, "currency": None,
            "total_amount": None, "amount_eur": None, "fx_rate_used": None,
            "requires_dual_approval": None,
            "llm_status": None, "llm_model": None,
            "details_json": json.dumps({"error": repr(exc)})}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sequentially process every PDF in --input through Gates 1-5.")
    parser.add_argument("--input", default=None,
                        help="Directory containing the invoice PDFs "
                             "(default: invoices next to this script)")
    parser.add_argument("--no-move", action="store_true",
                        help="True read-only dry run: keep PDFs in the input dir "
                             "and write nothing (no ledger row, no history append, "
                             "no processed/<status>/ move)")
    parser.add_argument("--db", default=None,
                        help="Path to an alternative SQLite database file "
                             "(default: ap_automation.db next to this script)")
    parser.add_argument("--processed-root", default=None,
                        help="Directory for the processed/<status>/ tree "
                             "(default: processed next to this script)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N files (N<=0 or omitted = no cap)")
    parser.add_argument("--json", action="store_true",
                        help="Print the per-file records as JSON")
    parser.add_argument("--llm", action=argparse.BooleanOptionalAction, default=None,
                        help="Enable/disable the vision LLM (default: enabled; "
                             "use --no-llm for intentional text-only mode)")
    args = parser.parse_args()

    if args.llm is not None:
        vision_llm.set_llm_enabled(args.llm)

    in_dir = Path(args.input) if args.input else DEFAULT_INPUT
    db_path = Path(args.db) if args.db else process_invoice.DB_PATH
    dry_run = bool(args.no_move)
    processed_root = Path(args.processed_root) if args.processed_root else None
    if not in_dir.is_dir():
        sys.exit(f"ERROR: input dir not found: {in_dir}")
    if not db_path.exists():
        sys.exit(f"ERROR: {db_path.name} not found - run setup_db.py first")

    files = build_queue(in_dir, args.limit)
    print(f"Found {len(files)} PDFs to process")

    llm = vision_llm.check_llm()
    print(f"Vision LLM: {llm['status']}"
          + (f" ({llm['model']})" if llm.get("model") else ""))
    if llm.get("using_fallback"):
        print("  primary model unavailable; using the approved fallback")
    if llm["fallback_models"]:
        print(f"  fallback ready: {', '.join(llm['fallback_models'])}")
    elif llm["ok"]:
        print("  fallback ready: none (only one approved model installed)")
    if files and llm["enabled"] and not llm["ok"]:
        sys.exit(f"ERROR: vision LLM is enabled but not usable: {llm.get('detail')}\n"
                 "       Start Ollama / install an approved model, or rerun with "
                 "--no-llm for intentional text-only mode.")

    start_time = dt.datetime.now().isoformat(timespec="seconds")
    records = []
    for i, pdf_path in enumerate(files, 1):
        started = time.monotonic()
        try:
            record = process_invoice.process(pdf_path, move=not dry_run,
                                             db_path=db_path,
                                             processed_root=processed_root)
        except Exception as exc:
            record = error_record(pdf_path, exc)
            record["dry_run"] = dry_run
            if not dry_run:
                process_invoice.record_result(db_path, record)
        elapsed = time.monotonic() - started
        print(f"[{i}/{len(files)}] {pdf_path.name} -> {record['status']}"
              f" - {record.get('gate_reached')} ({elapsed:.1f}s)")
        records.append(record)
    end_time = dt.datetime.now().isoformat(timespec="seconds")

    report = batch_report.build_report(records, start_time, end_time, dry_run=dry_run)
    batch_report.print_summary(report)
    print(f"REPORT WRITTEN {batch_report.write_report(report, REPORT_DIR)}")
    if args.json:
        print(json.dumps(records, indent=2, default=str))


if __name__ == "__main__":
    main()
