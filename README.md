# AP Automation — Fail-Fast Invoice Pipeline

A local, zero-cloud-cost implementation of a five-gate accounts-payable
invoice pipeline, with a single-file Phase 1 driver and a folder-level Phase 2
batch driver. Gates run cheapest-first, so expensive extraction and LLM work
only happens for invoices that have already passed the cheap checks.

The pipeline uses:

* **Python** for the gates, batch driver, database access and reporting.
* **SQLite** for vendor master data, historic invoices and the results ledger.
* **PyMuPDF** for PDF text extraction and page rendering.
* **Ollama** with a local vision model for the Gates 2.1 / 2.2 cross-check.

By default, no invoice data is sent to a cloud LLM. The only optional runtime
network call is the daily FX rate lookup in Gate 5; it has an offline fallback.

A complete recorded run over all 17 reference invoices — commands, verbatim
console output and per-invoice results — is in
[SAMPLE_OUTPUT.md](SAMPLE_OUTPUT.md).

---

## Contents

1. [Requirements](#1-requirements)
2. [Loading the program](#2-loading-the-program)
3. [Running modes](#3-running-modes)
4. [Command reference](#4-command-reference)
5. [What happens during a run](#5-what-happens-during-a-run)
6. [Outputs and reports](#6-outputs-and-reports)
7. [Rollback and reset](#7-rollback-and-reset)
8. [Vision LLM](#8-vision-llm)
9. [Database](#9-database)
10. [Final statuses](#10-final-statuses)
11. [Configuration](#11-configuration)
12. [Troubleshooting](#12-troubleshooting)
13. [Project files](#13-project-files)
14. [Testing protocol](#14-testing-protocol)
15. [Known limitations](#15-known-limitations)
16. [Notes](#16-notes)

Sample output: [SAMPLE_OUTPUT.md](SAMPLE_OUTPUT.md) — the commands and full
console output of a real run over the 17 reference invoices.

---

## 1. Requirements

### Software

| Requirement | Notes |
|---|---|
| Python 3.10+ | Tested with Python 3.13. The code uses modern union type hints, so Python 3.9 is not sufficient. |
| PyMuPDF | Installed with `pip install -r requirements.txt`. |
| Ollama | Required for the default vision cross-check. If Ollama is not available, use `--no-llm`. |
| PowerShell | The examples use Windows PowerShell. Bash equivalents work with `/` path separators. |

### Approved vision models

Only these models are accepted by `vision_llm.py`:

| Role | Model |
|---|---|
| Primary | `llama3.2-vision` |
| Fallback | `qwen2.5vl` |

At least one must be installed in Ollama. If both are installed, the primary is
preferred and the fallback is used only when the primary cannot be loaded.

### Input data

* `invoices/` contains the 17 reference PDFs.
* `data/vendor_master.csv` contains 25 vendors.
* `data/historic_invoices.csv` contains 120 historical invoices.
* `data/` is read-only source data. Do not edit the CSVs by hand during normal
  operation.

### Network

Gate 5 tries to fetch a daily FX rate from `open.er-api.com`. If the request
fails, it uses a static fallback table (`GBP 1.17 / USD 0.92 / CHF 1.06`).
Everything else runs locally.

---

## 2. Loading the program

All commands below run from the repository root — the folder that contains
`process_batch.py`. Open PowerShell there, for example:

```powershell
cd C:\path\to\ap_automation
```

### Fast path without Ollama

If you only want to validate the pipeline without installing Ollama, run:

```powershell
python -m pip install -r requirements.txt
python setup_db.py
python process_batch.py --input invoices --no-move --no-llm
```

This evaluates all 17 PDFs and writes a dry-run batch report. The batch itself
changes neither the database nor the PDFs. The detailed setup below adds the
local vision-LLM cross-check.

### Step 1 — Check Python

```powershell
python --version
```

Use Python 3.10 or newer.

### Step 2 — Install Python dependencies

```powershell
python -m pip install -r requirements.txt
```

The only Python package is PyMuPDF. The rest of the pipeline uses the standard
library.

### Step 3 — Start Ollama

Start the Ollama desktop application, or run the server in a second PowerShell
window and leave it running:

```powershell
ollama serve
```

If the command says the address is already in use, Ollama is already running.

### Step 4 — Install the vision models

One-time download:

```powershell
ollama pull llama3.2-vision
ollama pull qwen2.5vl:3b
```

The second model is optional. Without it, the primary is still used; without
the primary, the fallback is used.

### Step 5 — Verify the LLM

```powershell
python vision_llm.py --check
```

A healthy result looks like:

```json
{
  "enabled": true,
  "ok": true,
  "status": "ready",
  "model": "llama3.2-vision:latest",
  "fallback_models": ["qwen2.5vl:3b"]
}
```

If the check says `unavailable`, start Ollama (or pull an approved model) and
run the check again. If you do not want to use the LLM, skip this step and add
`--no-llm` to your run commands.

### Step 6 — Build the database

```powershell
python setup_db.py
```

On a fresh checkout this creates `ap_automation.db` from the CSVs in `data/`
and loads:

* 25 vendors
* 120 historical invoices
* 0 processed invoices

If `ap_automation.db` already exists, `setup_db.py` refreshes the seed tables
and keeps the existing results ledger. To rebuild the database from scratch
later:

```powershell
python setup_db.py --reset
```

`--reset` discards the results ledger and cross-batch history. It does **not**
move PDFs back from `processed/`; use `rollback.py` for a full restore.

### Step 7 — Validate one invoice

Start with a read-only dry run, to inspect the result without changing anything:

```powershell
python process_invoice.py invoices\INV-2025-03701_V001_EuroFuel.pdf --no-move --json
```

A dry run writes nothing and leaves the PDF in `invoices/`. On the reference
invoice, the result line is
`RESULT: CLEARED_STANDARD -> Standard Approval Queue`.

To exercise normal persistence too, run the same command without `--no-move`:

```powershell
python process_invoice.py invoices\INV-2025-03701_V001_EuroFuel.pdf
```

A normal run records the result and moves the PDF into `processed\<status>\`
(an exact duplicate keeps its prior ledger row). This moves that PDF, so Step 8
will process the remaining 16 files. Skip the normal single run if you want the
batch to process all 17.

### Step 8 — Run the whole folder

```powershell
python process_batch.py --input invoices
```

This processes every PDF currently in the folder one at a time, writes a JSON
audit report, and moves each routed PDF into `processed\<status>\`. A batch
processing error is recorded but left in the inbox.

For a report-only validation run:

```powershell
python process_batch.py --input invoices --no-move
```

### Step 9 — Stop Ollama when finished

Closing the Ollama desktop app stops the server. From PowerShell:

```powershell
Stop-Process -Name ollama
```

Stopping Ollama does not delete the downloaded models. They remain installed
and are loaded again on demand.

> **Important:** the LLM is enabled by default. If Ollama is not running,
> a single invoice is flagged `FLAGGED_LLM_UNAVAILABLE`, and a batch with
> queued PDFs aborts before writing ledger rows or a report. For intentional
> text-only runs, use `--no-llm` (or set `VISION_LLM_ENABLED=0`).

---

## 3. Running modes

| Mode | Command | Database writes | PDF moved |
|---|---|---|---|
| Normal single invoice | `python process_invoice.py <pdf>` | Yes: ledger + history | Yes |
| Normal batch | `python process_batch.py --input invoices` | Yes: ledger + history | Yes |
| Dry run | add `--no-move` | None | No |
| Text-only | add `--no-llm` | Depends on `--no-move` | Depends on `--no-move` |
| Sandbox | add `--db scratch.db --processed-root <dir>` | To the sandbox DB | To the sandbox tree |
| Limited batch | `--limit 3` | Same as the selected mode | Same as the selected mode |

### Normal mode

The default behavior:

1. Run Gates 1–5.
2. Insert one row into `processed_invoices` — except for an exact duplicate,
   which keeps its prior ledger row.
3. Append terminal invoices to `historic_invoices` for cross-batch dedup.
4. Move the PDF to `processed/<status>/`.

Exception: when the batch driver catches a processing error, the source PDF
stays in the inbox and only the ledger/report record is written.

### Dry-run mode

`--no-move` is a true read-only dry run:

* Gates run and the verdict is printed.
* The PDF stays in the inbox.
* No `processed_invoices` row is inserted.
* No `historic_invoices` row is appended.
* No `processed/<status>/` folder is created.
* No file is moved.

For a completed batch, the audit report is still written, but it is tagged
`dry_run: true` at the top level and on every per-file record. If the LLM
preflight aborts the batch, no report is written.

### Text-only mode

`--no-llm` switches the vision cross-check off intentionally. This is useful
when Ollama is not installed or when you want a fast deterministic text-only
run. It is different from an LLM failure: an intentional text-only run records
`llm_status = "disabled"`; an enabled-but-unavailable LLM records
`FLAGGED_LLM_UNAVAILABLE`.

### Sandbox mode

Use `--db` to isolate the ledger and `--processed-root` to isolate routed PDFs:

```powershell
python process_invoice.py invoices\INV-2025-03701_V001_EuroFuel.pdf `
  --db "$env:TEMP\ap-test\test.db" `
  --processed-root "$env:TEMP\ap-test\processed"
```

The target database must already exist. Create it with:

```powershell
python setup_db.py --db "$env:TEMP\ap-test\test.db"
```

### Batch performance and error isolation

With the vision cross-check running locally, expect roughly **20–30 seconds per
invoice**; the full 17-PDF inbox takes about 7–8 minutes. Intentional text-only
batches (`--no-llm`) are much faster, typically under 150 ms per invoice.

Each file runs inside its own try/except. A corrupt or unreadable PDF becomes
`FLAGGED_PROCESSING_ERROR` and the batch continues with the next file. Progress
prints one line per file:

```text
[i/N] <filename> -> <STATUS> - <gate_reached> (<seconds>s)
```

An empty input folder prints `Found 0 PDFs to process` and exits 0.

---

## 4. Command reference

### Single-file driver

```text
python process_invoice.py <pdf> [--no-move] [--json] [--db <path>]
                          [--processed-root <dir>] [--llm | --no-llm]
```

| Flag | Effect |
|---|---|
| `<pdf>` | PDF to process. |
| `--no-move` | True read-only dry run: no ledger, no history, no folder, no move. |
| `--json` | Print the full result record as JSON. |
| `--db <path>` | Use an alternative SQLite database. The file must already exist. |
| `--processed-root <dir>` | Stage the `processed/<status>/` tree for normal runs in another directory. |
| `--llm` / `--no-llm` | Force the vision LLM on or off. Default is on. |

### Batch driver

```text
python process_batch.py [--input <dir>] [--no-move] [--db <path>]
                        [--processed-root <dir>] [--limit N] [--json]
                        [--llm | --no-llm]
```

| Flag | Default | Effect |
|---|---|---|
| `--input <dir>` | `invoices/` | Folder to scan for `*.pdf` files. Non-PDF files are skipped with a warning. |
| `--no-move` | off | True read-only dry run. The report is still written with `dry_run: true`. |
| `--db <path>` | `ap_automation.db` | Alternative SQLite database. |
| `--processed-root <dir>` | `processed/` | Alternative destination tree for normal-mode routing. |
| `--limit N` | no cap | Process at most N files. `N <= 0` or omitted means no cap. |
| `--json` | off | Print every per-file record as JSON. |
| `--llm` / `--no-llm` | on | Enable or disable the vision LLM. Use `--no-llm` for intentional text-only mode. |

Before processing, the batch driver runs `vision_llm.check_llm()`. If the LLM
is enabled but unusable and at least one PDF is queued, the batch exits
**before** writing ledger rows or a report. Rerun with `--no-llm` if text-only
processing is intended.

### Custom per-file loop

If you need custom logic between files, call the single-file driver from your
own loop:

```python
import glob
import subprocess

for pdf in sorted(glob.glob("invoices/*.pdf")):
    subprocess.run(["python", "process_invoice.py", pdf], check=True)
```

### Run a gate standalone

Each gate is a self-contained script and prints its verdict as JSON. This is
useful for debugging one stage without running the whole pipeline:

```powershell
python gate1_duplicate_check.py    invoices\<file>.pdf
python gate2a_vendor_identity.py   invoices\<file>.pdf
python gate2b_key_value_extract.py invoices\<file>.pdf
python gate3_dedup_po_check.py     invoices\<file>.pdf
python gate4_line_integrity.py     invoices\<file>.pdf
python gate5_business_routing.py   invoices\<file>.pdf
python vision_llm.py               invoices\<file>.pdf
```

### Rollback utility

```text
python rollback.py [--db <path>] [--inbox <dir>] [--processed <dir>]
                   [--dry-run] [--skip-files] [--skip-db]
```

| Flag | Effect |
|---|---|
| `--db <path>` | Database to reset. Default: `ap_automation.db`. |
| `--inbox <dir>` | Destination for restored files. Default: `invoices/`. |
| `--processed <dir>` | Source tree to restore from. Default: `processed/`. |
| `--dry-run` | Preview moves and DB counts; touch nothing. |
| `--skip-files` | Reset the database only. Staged files stay in `processed/`. |
| `--skip-db` | Restore files only. The database is untouched. |

Without flags, `rollback.py` targets production paths and resets the
production database. That is an explicit operator action, not a test step.

---

## 5. What happens during a run

Gates are evaluated in order. The first failure stops the invoice with the
corresponding status.

| Gate | Check | Stops with |
|---|---|---|
| 1 | SHA-256 exact-file duplicate check against `processed_invoices` | `FLAGGED_EXACT_DUPLICATE` |
| 2.1 | Vendor identity from the page-1 letterhead; fuzzy match against `vendor_master` | `FLAGGED_UNKNOWN_VENDOR`, `FLAGGED_INACTIVE_VENDOR` |
| 2.2 | Header extraction: invoice number, date, PO, currency, total | `FLAGGED_MISSING_PO` |
| 3 | History dedup, PO overdraw, same-PO/same-amount re-issue | `FLAGGED_DUPLICATE_INVOICE`, `FLAGGED_PO_LIMIT_BREACHED`, `FLAGGED_SUSPECTED_DUPLICATE` |
| 4 | Line-item math, subtotal + VAT = total, approved currency | `FLAGGED_DATA_INTEGRITY`, `FLAGGED_CURRENCY_MISMATCH` |
| 5 | FX to EUR, spend threshold, dual-approval routing | `FLAGGED_THRESHOLD_BREACH`, `CLEARED_STANDARD`, `DUAL_APPROVAL` |

Gates 2.1 and 2.2 run both a deterministic text extraction and a local vision
LLM extraction, then cross-check the values. A disagreement produces
`FLAGGED_EXTRACTION_MISMATCH`. An enabled-but-unusable LLM produces
`FLAGGED_LLM_UNAVAILABLE`; invalid or errored LLM output produces
`FLAGGED_LLM_ERROR`.

### Cross-batch dedup

Terminal invoices with `invoice_id`, `vendor_id` and `amount_eur` resolved and
a status in `APPEND_STATUSES` (`CLEARED_STANDARD`, `DUAL_APPROVAL`,
`FLAGGED_THRESHOLD_BREACH`) are appended to `historic_invoices` by
`history_sync.py`. Gate 3 can then catch duplicates across separate batch runs,
not only against the 120 seed rows.

Two duplicate shapes are caught earlier and never double-appended:

* **Exact same file re-run:** Gate 1 sees the same SHA-256 in the ledger and
  flags `FLAGGED_EXACT_DUPLICATE`.
* **Re-issued invoice with new file bytes:** Gate 1 passes, then Gate 3's
  vendor + amount check flags `FLAGGED_DUPLICATE_INVOICE`.

Gate 2.x flags, Gate 3/4 verdicts and processing errors never append to
`historic_invoices`.

---

## 6. Outputs and reports

### Processed files

In normal mode, routed PDFs are moved into a folder named after their final
status:

```text
processed/
  cleared_standard/
  dual_approval/
  flagged_missing_po/
  flagged_unknown_vendor/
  flagged_inactive_vendor/
  flagged_extraction_mismatch/
  flagged_llm_unavailable/
  flagged_llm_error/
  flagged_exact_duplicate/
  flagged_duplicate_invoice/
  flagged_po_limit_breached/
  flagged_suspected_duplicate/
  flagged_data_integrity/
  flagged_currency_mismatch/
  flagged_threshold_breach/
  flagged_processing_error/
```

The batch driver's `FLAGGED_PROCESSING_ERROR` case is the exception: the PDF
stays in the inbox while the ledger/report records the error. A single-file
run moves its error case into `flagged_processing_error/`.

`--processed-root <dir>` changes the root for normal runs. `--no-move` creates
no folder and moves no file.

### Batch reports

Every completed batch writes:

```text
batch_reports/batch_<YYYYMMDD_HHMMSS>.json
```

The filename timestamp is the report's `batch_id`. The report is deliberately
compact: per file it keeps the identifiers and gate verdict plus LLM
provenance, but not the full `details_json` evidence. Flag reasons, extracted
vendor names, PO references, or line-item descriptions may still appear inside
`flag_reason`; query the ledger for the full evidence trail.

#### Top-level keys

| Key | Meaning |
|---|---|
| `batch_id` | Report identifier; matches the filename timestamp. |
| `start_time` | Batch start time (ISO 8601). |
| `end_time` | Batch end time (ISO 8601). |
| `duration_seconds` | Elapsed batch time. |
| `dry_run` | `true` when the batch used `--no-move`; `false` otherwise. |
| `total_processed` | Number of files in the batch. |
| `status_counts` | Count of each final status. |
| `files` | Array of per-file records. |

#### Per-file keys

| Key | Meaning |
|---|---|
| `file_name` | Original PDF filename. |
| `sha256` | SHA-256 fingerprint of the PDF bytes. Gate 1 uses it for exact duplicate detection. |
| `status` | Final pipeline status, e.g. `CLEARED_STANDARD`. |
| `gate_reached` | Last stage reached: `complete`, `gate1`, `gate2.1`, `gate2.2`, `gate3`, `gate4`, `driver` or `error`. |
| `flag_reason` | Human-readable reason for a flag; `null` when the invoice cleared. |
| `routed_to` | Business queue label from Gate 5, e.g. `Standard Approval Queue`. This is not a filesystem path. |
| `llm_status` | Per-invoice vision status: `ready`, `disabled`, `unavailable`, `error`, or `null` if the LLM was never reached. |
| `llm_model` | Actual model used for extraction, e.g. `llama3.2-vision:latest` or `qwen2.5vl:3b`; `null` if disabled or unavailable. |
| `invoice_id` | Extracted invoice number; optional. |
| `vendor_id` | Matched vendor-master ID; optional. |
| `amount_eur` | Amount normalized to EUR by Gate 5; optional and `null` if the invoice did not reach that stage. |
| `dry_run` | Per-file dry-run flag. `true` means no ledger/history write and no move. |

`routed_to` is the business queue label, not the filesystem path. The actual
destination is stored as `dest_path` in the `processed_invoices` ledger and
shown in the single-file JSON record; it is intentionally omitted from the
batch report.

### Sample output

`SAMPLE_OUTPUT.md` in the project root records one complete run of the batch
driver over the 17 reference PDFs: environment, the exact commands, the
verbatim console output, a per-invoice result table and the state check
performed afterwards. Its companion folder `sample_output/` holds the JSON
report and console transcript of that run, kept outside `batch_reports/` so
the `batch_reports/` gitignore rule does not remove them from a submission.

### Database

The results ledger in `processed_invoices` is the durable audit trail for
normal runs. The batch report is a smaller, shareable summary. For detailed
per-gate evidence, query `processed_invoices.details_json`.

---

## 7. Rollback and reset

`rollback.py` undoes a run and restores the database to seed state.

```powershell
python rollback.py
```

Default behavior:

* Moves every regular file under `processed\` back into `invoices\`.
* Does not overwrite an existing inbox file. A collision becomes
  `<stem>__rollback_N<suffix>`, using the lowest free `N >= 1`.
* Removes empty `processed\<status>\` subdirectories bottom-up. The
  `processed\` root itself is kept.
* Rebuilds `ap_automation.db` from the seed CSVs:
  **25 vendors / 120 historic invoices / 0 processed invoices**.
* Treats a missing `processed\` as zero files, not an error.
* Is idempotent: rerunning on restored state exits 0 with `files=0`.
* Refuses to delete an existing non-empty file that is not a SQLite database.

Preview only:

```powershell
python rollback.py --dry-run
```

One phase at a time:

```powershell
python rollback.py --skip-files   # DB reset only; staged PDFs stay in processed\
python rollback.py --skip-db      # file restore only; DB untouched
```

Sandbox rollback:

```powershell
python rollback.py `
  --db "$env:TEMP\ap-test\test.db" `
  --inbox "$env:TEMP\ap-test\invoices" `
  --processed "$env:TEMP\ap-test\processed"
```

> **Warning:** the default `python rollback.py` resets the production
> database and discards the results ledger and cross-batch history. Make a
> copy of `ap_automation.db` first if you need the old ledger.

---

## 8. Vision LLM

`vision_llm.py` renders page 1 of the PDF to an image with PyMuPDF and asks a
local Ollama vision model for the same fields as the text extraction, in
strict JSON (`format: json`, `temperature: 0`).

### Model allowlist

| Role | Model |
|---|---|
| Primary | `llama3.2-vision` |
| Fallback | `qwen2.5vl` |

`vision_llm.py` uses the first installed approved model. If the primary cannot
be loaded, it falls back to the other. `llm_model` in the report shows the
model that actually produced the extraction, so fallback use is visible.

### Cross-check rules

Evidence for both extraction paths is stored in `details_json`.

| Situation | Result |
|---|---|
| Text and vision agree | Gate proceeds normally. |
| Both present, values disagree | `FLAGGED_EXTRACTION_MISMATCH` → `processed/flagged_extraction_mismatch/` |
| Text missing (image-only scan), vision has the value | Vision value adopted, noted as `*_source = vision`. |
| Text layer exists but PO field is blank | PO stays missing (hard fail). The LLM cannot fill a mandatory field from a document that visibly leaves it blank. |
| LLM enabled, Ollama or model unavailable | `FLAGGED_LLM_UNAVAILABLE`; the invoice does not silently clear text-only. |
| LLM enabled, invalid JSON or model error | `FLAGGED_LLM_ERROR`. |
| LLM turned off with `--no-llm` or `VISION_LLM_ENABLED=0` | Intentional text-only mode; `vision.status = disabled`. |

### Health check and status fields

`python vision_llm.py --check` reports:

* `enabled`: whether the LLM path is switched on.
* `ok`: whether a usable approved model is available.
* `status`: `ready`, `disabled`, `unavailable` or `error`.
* `model`: active model.
* `fallback_models`: other installed approved models.
* `using_fallback`: whether the active model is the fallback.
* `detail`: human-readable reason when not ready.

Per-invoice batch records expose the same idea through `llm_status` and
`llm_model`.

### Start and stop

Start the Ollama app, or run `ollama serve` in a second terminal and leave it
running:

```powershell
ollama serve
```

Check loaded models:

```powershell
ollama ps
```

Stop the server:

```powershell
Stop-Process -Name ollama
```

Downloaded models remain on disk.

---

## 9. Database

`ap_automation.db` is created next to the scripts.

| Table | Purpose |
|---|---|
| `vendor_master` | 25 vendors: status, approved currency, spend threshold, dual-approval flag. |
| `historic_invoices` | 120 historical invoices used by Gate 3 duplicate detection. |
| `po_master` | Optional PO budgets for Gate 3 overdraw checks. The case-study data ships no PO totals, so this check is skipped with a note until ERP data is synced. |
| `processed_invoices` | Results ledger: one row per new normal-mode result (clean or flagged); an exact duplicate keeps its prior row. Includes SHA-256, gate reached, status, routing, extracted metadata, FX rate and `details_json` evidence. |

Useful inspection commands:

```powershell
python setup_db.py --db scratch.db
python -c "import sqlite3; c=sqlite3.connect('ap_automation.db'); print(c.execute('select status, count(*) from processed_invoices group by status').fetchall())"
```

---

## 10. Final statuses

The status name is also the output folder name under `processed/` when the file
is routed.

| Status | Meaning |
|---|---|
| `cleared_standard` | All gates passed → Standard Approval Queue. |
| `dual_approval` | All gates passed; vendor requires two approvers → Dual Approval Queue. |
| `flagged_exact_duplicate` | Gate 1: identical file bytes already processed. |
| `flagged_unknown_vendor` | Gate 2.1: no vendor-master match. |
| `flagged_inactive_vendor` | Gate 2.1: matched vendor is inactive. |
| `flagged_extraction_mismatch` | Gate 2.1/2.2: text and vision disagree. |
| `flagged_llm_unavailable` | Gate 2.1/2.2: LLM enabled but server/model unavailable. |
| `flagged_llm_error` | Gate 2.1/2.2: LLM enabled but extraction failed or returned invalid output. |
| `flagged_missing_po` | Gate 2.2: no PO reference. |
| `flagged_duplicate_invoice` | Gate 3: vendor + amount matches history. |
| `flagged_po_limit_breached` | Gate 3: PO overdraw. |
| `flagged_suspected_duplicate` | Gate 3: same PO and same amount re-issue. |
| `flagged_data_integrity` | Gate 4: line-item math or totals failed. |
| `flagged_currency_mismatch` | Gate 4: currency is not approved for the vendor. |
| `flagged_threshold_breach` | Gate 5: amount exceeds the vendor threshold. |
| `flagged_processing_error` | Unexpected pipeline error, e.g. a corrupt PDF. |

---

## 11. Configuration

All settings are optional environment variables.

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama API endpoint. |
| `OLLAMA_VISION_MODEL` | unset | Pin a specific approved model. |
| `VISION_LLM_ENABLED` | on | `0`, `false` or `off` disables the LLM path. |
| `VISION_TIMEOUT` | `240` seconds | Per-request LLM timeout. |
| `VISION_DPI` | `150` | Page-render DPI for the vision model. |

Example text-only session:

```powershell
$env:VISION_LLM_ENABLED = "0"
python process_batch.py --input invoices
```

Reset it for the next session:

```powershell
Remove-Item Env:VISION_LLM_ENABLED
```

---

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Ollama server not reachable` from `vision_llm.py --check` | Ollama is stopped. | Start the Ollama app or run `ollama serve`. |
| Batch exits with `vision LLM is enabled but not usable` | LLM is on but no approved model/server is available. | Start Ollama and pull an approved model, or rerun with `--no-llm`. |
| Single invoice returns `FLAGGED_LLM_UNAVAILABLE` | LLM enabled but unusable. | Start Ollama / install a model, or use `--no-llm` for intentional text-only mode. |
| Single invoice returns `FLAGGED_LLM_ERROR` | The model returned invalid JSON or failed. | Check `ollama ps`, retry, or use the fallback model. |
| `ERROR: ap_automation.db not found` | Database has not been built. | Run `python setup_db.py`. |
| `FLAGGED_EXACT_DUPLICATE` | The same PDF bytes already have a ledger row. | Use a different file, or reset with `python rollback.py` if this is a test. |
| `FLAGGED_MISSING_PO` | No PO reference on the invoice. | Correct the invoice data; this is a hard business rule. |
| `FLAGGED_UNKNOWN_VENDOR` | Vendor is not in `vendor_master`. | Add/approve the vendor, or treat as a review item. |
| `FLAGGED_INACTIVE_VENDOR` | Vendor is marked inactive. | Review vendor status in `vendor_master`. |
| `FLAGGED_PROCESSING_ERROR` | Corrupt or unreadable PDF. | Inspect the file; the batch continues with the next invoice. |
| `no such table` from SQLite | Wrong `--db` path or empty file. | Create it with `python setup_db.py --db <path>`. |
| Rollback says `__rollback_N` | A file with the same name already exists in the inbox. | Expected; the original was not overwritten. |
| Two batch reports share a filename | Two batches completed in the same second. | Wait one second, or rename the reports. |
| `Address already in use` from `ollama serve` | Ollama is already running. | Continue; run `vision_llm.py --check` to confirm. |

---

## 13. Project files

| File / folder | Purpose |
|---|---|
| `process_invoice.py` | Single-PDF driver: Gates 1–5, normal persistence/routing or dry run. |
| `process_batch.py` | Sequential batch driver with per-file error isolation and audit report. |
| `batch_report.py` | Builds the JSON batch report and prints the stdout summary. |
| `gate1_duplicate_check.py` | Gate 1: SHA-256 exact-file duplicate check. |
| `gate2a_vendor_identity.py` | Gate 2.1: vendor identity and active-status check. |
| `gate2b_key_value_extract.py` | Gate 2.2: header field extraction and mandatory PO check. |
| `gate3_dedup_po_check.py` | Gate 3: history dedup, PO overdraw and re-issue checks. |
| `gate4_line_integrity.py` | Gate 4: line-item math, totals and currency. |
| `gate5_business_routing.py` | Gate 5: FX, spend threshold and dual-approval routing. |
| `history_sync.py` | Appends terminal invoices to `historic_invoices`. |
| `vision_llm.py` | Ollama client, model allowlist, health check and provenance. |
| `setup_db.py` | Builds/refreshes `ap_automation.db` from `data/`. |
| `rollback.py` | Restores `processed/` files to `invoices/` and resets the DB. |
| `requirements.txt` | Python dependencies (PyMuPDF). |
| `ap_automation.db` | Generated SQLite database with seed data and the results ledger; built by `setup_db.py`, not committed. |
| `README.md` | This guide. |
| `SAMPLE_OUTPUT.md` | Recorded sample run: commands, console output and per-invoice results for the 17 PDFs. |
| `sample_output/` | Sample-run artifacts: `batch_20261020_130914.json` report copy and `batch_console.txt` transcript. |
| `data/vendor_master.csv` | Vendor seed data (25 vendors). |
| `data/historic_invoices.csv` | Historic invoice seed data (120 rows). |
| `invoices/` | Reference input PDFs (17 files, read-only). |
| `processed/` | Generated routing tree; created on demand, gitignored. |
| `batch_reports/` | Generated JSON audit reports; created on demand, gitignored. |

---

## 14. Testing protocol

Never point experiments at production state. Use a temporary database, a
temporary inbox and a temporary processed tree.

```powershell
$test = "$env:TEMP\ap-test"
New-Item -ItemType Directory -Path "$test\inbox", "$test\db" -Force | Out-Null
Copy-Item invoices\INV-2025-03701_V001_EuroFuel.pdf "$test\inbox\"

python setup_db.py --db "$test\db\test.db"

# Dry run: DB is read-only; no PDF moves.
python process_batch.py `
  --input "$test\inbox" `
  --db "$test\db\test.db" `
  --no-move `
  --no-llm `
  --processed-root "$test\processed"

# Normal run: writes to the temp DB and stages under the temp processed tree.
python process_batch.py `
  --input "$test\inbox" `
  --db "$test\db\test.db" `
  --no-llm `
  --processed-root "$test\processed"

# Restore files and reset the temp DB.
python rollback.py `
  --db "$test\db\test.db" `
  --inbox "$test\inbox" `
  --processed "$test\processed"
```

Key expectations:

* A dry run leaves `processed_invoices` at 0 and `historic_invoices` at 120.
* A normal run on a new terminal invoice writes one ledger row and one history
  row.
* `rollback.py` restores the PDF and returns the DB to 25/120/0.
* A collision in the inbox produces `__rollback_1`, then `__rollback_2`, and
  never overwrites the original.

Production state at ship is intended to be:

```text
vendor_master:      25
historic_invoices: 120
processed_invoices:  0
invoices/*.pdf:     17
processed/:         absent
```

---

## 15. Known limitations

* **Report filename collision:** `batch_<YYYYMMDD_HHMMSS>.json` has
  second-granularity timestamps. Two batches finishing in the same second reuse
  a filename.
* **Dry runs do not seed duplicates:** repeated `--no-move` runs are
  intentionally identical because they never write to the ledger. A file that a
  real run already ledgered is still reported `FLAGGED_EXACT_DUPLICATE` in a
  dry run.
* **Corrupt PDFs in batch mode:** a `FLAGGED_PROCESSING_ERROR` file stays in the
  inbox for visibility; it is recorded in the ledger and report. A single-file
  run routes its error case to `processed/flagged_processing_error/`.
* **FX fallback:** if the daily rate API is unavailable, Gate 5 uses a static
  table (`GBP 1.17 / USD 0.92 / CHF 1.06`). The rate source is recorded in
  `details_json`.
* **No PO budgets:** `po_master` is empty in the case-study dataset, so Gate 3
  overdraw checks are skipped with a note until ERP data is loaded.
* **LLM policy is fail-closed:** an enabled-but-unusable LLM does not silently
  degrade to text-only. Use `--no-llm` when text-only is intentional.
* **No automatic backup:** `rollback.py` and `setup_db.py --reset` discard
  ledger/history data. Copy `ap_automation.db` first if you need it.

---

## 16. Notes

* **Deterministic dedup:** Gate 1 keys on file bytes. Re-submitting a PDF that
  was already processed is caught before any extraction, and the original
  ledger row remains the single audit record.
* **Fail-fast:** Gate 1 runs before any PDF extraction. Gates 2.1/2.2 do the
  deterministic text pass before calling the vision model, and line-item math is
  deferred to Gate 4.
* **Local processing:** invoice content stays on the machine. The optional FX
  lookup sends only a currency-rate request, not invoice data.
* **Seed data:** `data/` makes the repository self-contained. `setup_db.py`
  also accepts `--vendor-csv` and `--historic-csv`, and falls back to
  `../ap-automation-assessment/` when the local CSVs are absent.
* **`--processed-root`:** normal-mode routing can be redirected for tests.
  `--no-move` ignores it because no folder is created.
