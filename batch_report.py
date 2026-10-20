#!/usr/bin/env python3
"""
batch_report.py - FR-4 batch audit report: JSON file + stdout summary table.

Builds the report dict from per-file records, prints a concise summary table,
and writes it as <out-dir>/batch_<YYYYMMDD_HHMMSS>.json where the filename
timestamp equals the report's batch_id. Per-file records are PII-minimized to
invoice identifiers, amounts and gate verdicts (SPEC section 6).

    python batch_report.py --records <records.json> --out-dir <dir>

records.json shape: {"records": [...]} with optional top-level
"start_time" / "end_time" ISO strings (default: load time, duration 0).
"""

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

REPORT_FIELDS = ("file_name", "sha256", "status", "gate_reached", "flag_reason",
                 "routed_to", "llm_status", "llm_model")
OPTIONAL_FIELDS = ("invoice_id", "vendor_id", "amount_eur")


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _minimize(rec: dict, dry_run: bool = False) -> dict:
    out = {key: rec.get(key) for key in REPORT_FIELDS}
    out.update({key: rec[key] for key in OPTIONAL_FIELDS if rec.get(key) is not None})
    out["dry_run"] = rec.get("dry_run", dry_run)
    return out


def build_report(records: list, start_time: str, end_time: str,
                 dry_run: bool = False) -> dict:
    """Assemble the FR-4 report dict from per-file records."""
    start = _parse_iso(start_time)
    end = _parse_iso(end_time)
    duration = max((end - start).total_seconds(), 0.0) if start and end else 0.0
    return {
        "batch_id": f"batch_{_now_stamp()}",
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(duration, 3),
        "dry_run": bool(dry_run),
        "total_processed": len(records),
        "status_counts": dict(Counter(rec.get("status") or "UNKNOWN" for rec in records)),
        "files": [_minimize(rec, dry_run) for rec in records],
    }


def write_report(report: dict, out_dir: Path) -> Path:
    """Write the report JSON into out_dir (created if missing); return the path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_id = report.get("batch_id") or f"batch_{_now_stamp()}"
    path = out_dir / f"{batch_id}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def print_summary(report: dict) -> None:
    """Print a concise stdout summary table (FR-4)."""
    print(f"=== BATCH SUMMARY {report.get('batch_id', '')} ===")
    print(f"start_time       : {report.get('start_time')}")
    print(f"end_time         : {report.get('end_time')}")
    print(f"duration_seconds : {report.get('duration_seconds')}")
    print(f"dry_run          : {report.get('dry_run')}")
    print(f"total_processed  : {report.get('total_processed')}")
    counts = report.get("status_counts") or {}
    print("status_counts    : " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    files = report.get("files") or []
    if files:
        print("-" * 84)
        print(f"{'file_name':<40} {'status':<30} llm")
        for rec in files:
            print(f"{str(rec.get('file_name')):<40} {str(rec.get('status')):<30} "
                  f"{rec.get('llm_status')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write the FR-4 batch audit report JSON and print a summary table.")
    parser.add_argument("--records", required=True,
                        help='Path to a JSON file: {"records": [...]} '
                             "(optional top-level start_time/end_time ISO strings)")
    parser.add_argument("--out-dir", required=True,
                        help="Directory for batch_<YYYYMMDD_HHMMSS>.json (created if missing)")
    args = parser.parse_args()

    payload = json.loads(Path(args.records).read_text(encoding="utf-8"))
    now = datetime.now().isoformat(timespec="seconds")
    report = build_report(payload.get("records", []),
                          payload.get("start_time") or now,
                          payload.get("end_time") or now)
    print_summary(report)
    print(f"REPORT WRITTEN {write_report(report, Path(args.out_dir))}")


if __name__ == "__main__":
    main()
