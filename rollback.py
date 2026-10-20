#!/usr/bin/env python3
"""
rollback.py - Restore processed invoices to the inbox and reset the AP database.

Implements SPEC FR-5 (file rollback with deterministic collision avoidance) and
FR-6 (database reset to seed state) as two independent phases:

  * files phase: every regular file under --processed (recursive) is moved back
    into --inbox. A name that already exists in the inbox becomes
    <stem>__rollback_<N><suffix> with the lowest free N >= 1; existing inbox
    files are never overwritten. Afterwards the empty subdirectories under
    --processed are removed bottom-up (--processed itself is kept).
  * db phase: the --db file is unlinked (plus best-effort -wal/-shm) and rebuilt
    from the seed CSVs through setup_db, restoring the baseline 25 vendor_master
    / 120 historic_invoices / 0 processed_invoices. An existing non-empty file
    without the SQLite magic header is refused (RuntimeError), so a mistyped
    --db can never delete a user file.

--dry-run previews the file moves without touching files or the database; its
db line reports the current counts when they are readable, otherwise the counts
a reset would produce. --skip-files runs the db phase only, --skip-db the file
phase only, and both flags together are a no-op. The utility is idempotent:
re-running it on restored state exits 0 with files=0.

CLI:
    python rollback.py [--db PATH] [--inbox DIR] [--processed DIR]
                       [--dry-run] [--skip-files] [--skip-db]

Defaults resolve next to this script: ap_automation.db, invoices/, processed/.
"""

import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path

import setup_db

BASE_DIR = Path(__file__).resolve().parent
SQLITE_MAGIC = b"SQLite format 3\x00"

_SEED_COUNTS = (25, 120, 0)
_TABLES = ("vendor_master", "historic_invoices", "processed_invoices")


def unique_target(inbox: Path, name: str) -> Path:
    """First free destination for `name` in `inbox`: the plain name when free,
    else <stem>__rollback_<N><suffix> with the lowest free N >= 1."""
    dest = inbox / name
    if not dest.exists():
        return dest
    n = 1
    while (inbox / f"{dest.stem}__rollback_{n}{dest.suffix}").exists():
        n += 1
    return inbox / f"{dest.stem}__rollback_{n}{dest.suffix}"


def restore_files(inbox: Path, processed: Path, dry_run: bool = False) -> dict:
    """Move every regular file from processed/** into inbox, then remove the
    empty subdirectories bottom-up (processed root itself is kept). A missing
    --processed counts as zero files (missing_processed=True), not an error.
    Returns {"moved": [{"src", "dest"}], "removed_dirs": [Path, ...],
    "missing_processed": bool}; dry-run previews the moves only."""
    result = {"moved": [], "removed_dirs": [], "missing_processed": not processed.is_dir()}
    if result["missing_processed"]:
        return result
    if not dry_run:
        inbox.mkdir(parents=True, exist_ok=True)
    for src in sorted(processed.rglob("*")):
        if not src.is_file():
            continue
        dest = unique_target(inbox, src.name)
        if not dry_run:
            shutil.move(src, dest)
        result["moved"].append({"src": src, "dest": dest})
    if dry_run:
        return result
    for root, dirnames, _ in os.walk(processed, topdown=False):
        for dirname in dirnames:
            empty = Path(root) / dirname
            try:
                empty.rmdir()
            except OSError:
                continue
            result["removed_dirs"].append(empty)
    return result


def _current_counts(db_path: Path) -> tuple | None:
    if not db_path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    except (OSError, sqlite3.Error):
        return None
    try:
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _TABLES)
    except (OSError, sqlite3.Error):
        return None
    finally:
        conn.close()


def reset_database(db_path: Path, dry_run: bool = False) -> dict:
    """Rebuild db_path to seed state (25/120/0) using setup_db's schema and
    seed loaders. Dry-run never writes. Raises RuntimeError for an existing
    non-empty file without the SQLite magic header."""
    db_path = Path(db_path)
    if dry_run:
        vendors, historic, processed = _current_counts(db_path) or _SEED_COUNTS
        return {"db": db_path, "vendors": vendors, "historic": historic, "processed": processed}
    if db_path.is_file() and db_path.stat().st_size > 0:
        with open(db_path, "rb") as fh:
            if fh.read(len(SQLITE_MAGIC)) != SQLITE_MAGIC:
                raise RuntimeError(f"refusing to overwrite non-database file: {db_path}")
    vendor_csv = setup_db.resolve_csv("vendor_master.csv", None)
    historic_csv = setup_db.resolve_csv("historic_invoices.csv", None)
    for suffix in ("-wal", "-shm"):
        try:
            db_path.with_name(db_path.name + suffix).unlink()
        except OSError:
            pass
    try:
        db_path.unlink()
    except FileNotFoundError:
        pass
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(setup_db.SCHEMA)
        vendors = setup_db.load_vendor_master(conn, vendor_csv)
        historic = setup_db.load_historic_invoices(conn, historic_csv)
        conn.commit()
        processed = conn.execute("SELECT COUNT(*) FROM processed_invoices").fetchone()[0]
    finally:
        conn.close()
    return {"db": db_path, "vendors": vendors, "historic": historic, "processed": processed}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore processed invoices to the inbox and reset the AP database (FR-5/FR-6).")
    parser.add_argument("--db", help="Path to the SQLite database to reset "
                                     "(default: ap_automation.db next to this script)")
    parser.add_argument("--inbox", help="Directory receiving the restored files "
                                        "(default: invoices/ next to this script)")
    parser.add_argument("--processed", help="Directory whose staged files are restored "
                                            "(default: processed/ next to this script)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview the file moves; touch no files and no database")
    parser.add_argument("--skip-files", action="store_true",
                        help="Skip the file phase; reset the database only")
    parser.add_argument("--skip-db", action="store_true",
                        help="Skip the database phase; restore files only")
    args = parser.parse_args()

    print(f"ROLLBACK mode={'dry-run' if args.dry_run else 'apply'}")
    if args.skip_files and args.skip_db:
        print("ROLLBACK nothing-to-do")
        print("ROLLBACK OK")
        return

    inbox = Path(args.inbox) if args.inbox else BASE_DIR / "invoices"
    processed = Path(args.processed) if args.processed else BASE_DIR / "processed"
    db_path = Path(args.db) if args.db else BASE_DIR / "ap_automation.db"

    try:
        if not args.skip_files:
            files = restore_files(inbox, processed, dry_run=args.dry_run)
            for item in files["moved"]:
                verb = "would-move" if args.dry_run else "moved"
                print(f"ROLLBACK {verb} {item['src']} -> {item['dest']}")
            for removed in files["removed_dirs"]:
                print(f"ROLLBACK removed-dir {removed}")
            print(f"ROLLBACK files={len(files['moved'])} dirs={len(files['removed_dirs'])} missing_processed={files['missing_processed']}")
        if not args.skip_db:
            db = reset_database(db_path, dry_run=args.dry_run)
            print(f"ROLLBACK db={db['db']} vendors={db['vendors']} historic={db['historic']} processed={db['processed']}")
    except (Exception, SystemExit) as exc:
        print(f"ROLLBACK ERROR {exc}")
        sys.exit(1)
    print("ROLLBACK OK")


if __name__ == "__main__":
    main()
