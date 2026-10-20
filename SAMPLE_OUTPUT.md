# Sample output — run on the 17 provided invoices

This file is the submission sample: the exact commands used, the verbatim
console output of a complete batch run over the 17 reference PDFs in
`invoices/`, and the resulting per-invoice statuses.

* **Batch ID:** `batch_20261020_130914`
* **Machine-readable report (copy included for submission):**
  [`sample_output/batch_20261020_130914.json`](sample_output/batch_20261020_130914.json)
  (original written to `batch_reports/batch_20261020_130914.json`)
* **Console transcript also kept as plain text:**
  [`sample_output/batch_console.txt`](sample_output/batch_console.txt)

> **Note:** local machine paths were removed from this published capture; the report path is repo-relative.

---

## 1. Environment

| Item | Value |
|---|---|
| Date / time | 2026-10-20, 13:02:55 → 13:09:14 (379.0 s total) |
| Platform | Windows (win32) |
| Python | 3.13.13 |
| Ollama | 0.40.6, `http://127.0.0.1:11434` |
| Vision models | `llama3.2-vision:latest` (primary, installed) · `qwen2.5vl:3b` (approved fallback) |
| Input | `invoices/` — 17 PDFs, all processed |
| Mode | **dry run** (`--no-move`): read-only DB, no PDF moved, no ledger/history write |

---

## 2. Commands executed

All commands are run from the repository root (see `README.md` for setup).

```powershell
# 1) Start Ollama (skip if the service is already running)
ollama serve

# 2) Health check of the vision LLM — does not run inference
python vision_llm.py --check

# 3) The sample batch run: all 17 PDFs, vision LLM enabled, no state changes
python process_batch.py --input invoices --no-move
```

### 2.1 Output of `python vision_llm.py --check`

```json
{
  "enabled": true,
  "ok": true,
  "status": "ready",
  "server": "http://127.0.0.1:11434",
  "checked_at": "2026-10-20T13:28:23",
  "model": "llama3.2-vision:latest",
  "model_digest": "6f2f9757ae97e8a3f8ea33d6adb2b11d93d9a35bef277cd2c0b1b5af8e8d0b1e",
  "fallback_models": [
    "qwen2.5vl:3b"
  ],
  "installed_models": [
    "llama3.2-vision:latest",
    "qwen2.5vl:3b"
  ],
  "using_fallback": false,
  "fallback_ready": true,
  "detail": null
}
```

---

## 3. Console output of `python process_batch.py --input invoices --no-move`

Verbatim capture (identical to `sample_output/batch_console.txt`, with the
trailing padding spaces on the gate lines trimmed and the final report path
shown repo-relative), exit code `0`, 379.0 seconds wall clock. A console
encoding artifact changed one character; the vendor name in the line for file
16 is `QuickFix OÜ`, shown here in its correct form.

```text
Found 17 PDFs to process
Vision LLM: ready (llama3.2-vision:latest)
  fallback ready: qwen2.5vl:3b
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V001 (EuroFuel GmbH) score=1.0
[Gate 2.2 key-values      ] PASS
[Gate 3   dedup / PO      ] PASS  no historical duplicates; not on file - overdraw check skipped
[Gate 4   integrity       ] PASS  3 line items OK; subtotal+VAT==total; currency EUR approved
[Gate 5   routing         ] PASS  8551.67 EUR (rate 1.0 from identity) <= threshold 45000.0 EUR; single approval
[1/17] INV-2025-03701_V001_EuroFuel.pdf -> CLEARED_STANDARD - complete (25.4s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V004 (FleetMech GmbH) score=1.0
[Gate 2.2 key-values      ] PASS
[Gate 3   dedup / PO      ] PASS  no historical duplicates; not on file - overdraw check skipped
[Gate 4   integrity       ] PASS  3 line items OK; subtotal+VAT==total; currency EUR approved
[Gate 5   routing         ] PASS  6799.99 EUR (rate 1.0 from identity) <= threshold 30000.0 EUR; single approval
[2/17] INV-2025-03712_V004_FleetMech.pdf -> CLEARED_STANDARD - complete (25.3s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V005 (AutoServ S.R.L.) score=1.0
[Gate 2.2 key-values      ] PASS
[Gate 3   dedup / PO      ] PASS  no historical duplicates; not on file - overdraw check skipped
[Gate 4   integrity       ] PASS  3 line items OK; subtotal+VAT==total; currency EUR approved
[Gate 5   routing         ] PASS  5400.01 EUR (rate 1.0 from identity) <= threshold 25000.0 EUR; single approval
[3/17] INV-2025-03719_V005_AutoServ.pdf -> CLEARED_STANDARD - complete (25.9s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V006 (BritTech Solutions Ltd) score=1.0
[Gate 2.2 key-values      ] PASS
[Gate 3   dedup / PO      ] PASS  no historical duplicates; not on file - overdraw check skipped
[Gate 4   integrity       ] PASS  3 line items OK; subtotal+VAT==total; currency GBP approved
[Gate 5   routing         ] PASS  5932.48 EUR (rate 1.186971 from open.er-api.com) <= threshold 20000.0 EUR; single approval
[4/17] INV-2025-03731_V006_BritTech_GBP.pdf -> CLEARED_STANDARD - complete (24.9s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V008 (CleanStation S.A.) score=1.0
[Gate 2.2 key-values      ] PASS
[Gate 3   dedup / PO      ] PASS  no historical duplicates; not on file - overdraw check skipped
[Gate 4   integrity       ] PASS  3 line items OK; subtotal+VAT==total; currency EUR approved
[Gate 5   routing         ] PASS  3199.99 EUR (rate 1.0 from identity) <= threshold 8000.0 EUR; single approval
[5/17] INV-2025-03744_V008_CleanStation.pdf -> CLEARED_STANDARD - complete (25.0s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V009 (SparkIT BV) score=1.0
[Gate 2.2 key-values      ] FAIL  no PO reference found on the invoice (mandatory field)
[6/17] INV-2025-03752_V009_SparkIT_NoPO.pdf -> FLAGGED_MISSING_PO - gate2.2 (23.9s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V010 (StationOps GmbH) score=1.0
[Gate 2.2 key-values      ] PASS
[Gate 3   dedup / PO      ] PASS  no historical duplicates; not on file - overdraw check skipped
[Gate 4   integrity       ] PASS  3 line items OK; subtotal+VAT==total; currency EUR approved
[Gate 5   routing         ] PASS  10010.46 EUR (rate 1.0 from identity) <= threshold 22000.0 EUR; single approval
[7/17] INV-2025-03760_V010_StationOps.pdf -> CLEARED_STANDARD - complete (22.9s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V012 (MediaBoost GmbH) score=1.0
[Gate 2.2 key-values      ] PASS
[Gate 3   dedup / PO      ] PASS  no historical duplicates; not on file - overdraw check skipped
[Gate 4   integrity       ] PASS  3 line items OK; subtotal+VAT==total; currency EUR approved
[Gate 5   routing         ] PASS  4512.02 EUR (rate 1.0 from identity) <= threshold 12000.0 EUR; single approval
[8/17] INV-2025-03771_V012_MediaBoost.pdf -> CLEARED_STANDARD - complete (24.3s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V013 (NordClean ApS) score=1.0
[Gate 2.2 key-values      ] PASS
[Gate 3   dedup / PO      ] PASS  no historical duplicates; not on file - overdraw check skipped
[Gate 4   integrity       ] PASS  3 line items OK; subtotal+VAT==total; currency EUR approved
[Gate 5   routing         ] PASS  2900.01 EUR (rate 1.0 from identity) <= threshold 7000.0 EUR; single approval
[9/17] INV-2025-03779_V013_NordClean.pdf -> CLEARED_STANDARD - complete (24.2s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V002 (AlpinaDiesel AG) score=1.0
[Gate 2.2 key-values      ] FAIL  extraction mismatch on total_amount: PDF text -> 42121.24 vs vision LLM -> 2121.24 - needs human review
[10/17] INV-2025-03788_V002_AlpinaDiesel.pdf -> FLAGGED_EXTRACTION_MISMATCH - gate2.2 (24.2s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V014 (IberMaint S.L.) score=1.0
[Gate 2.2 key-values      ] PASS
[Gate 3   dedup / PO      ] PASS  no historical duplicates; not on file - overdraw check skipped
[Gate 4   integrity       ] PASS  3 line items OK; subtotal+VAT==total; currency EUR approved
[Gate 5   routing         ] PASS  8200.0 EUR (rate 1.0 from identity) <= threshold 28000.0 EUR; single approval
[11/17] INV-2025-03791_V014_IberMaint.pdf -> CLEARED_STANDARD - complete (23.2s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V003 (TotalRoute S.A.) score=1.0
[Gate 2.2 key-values      ] PASS
[Gate 3   dedup / PO      ] PASS  no historical duplicates; not on file - overdraw check skipped
[Gate 4   integrity       ] PASS  3 line items OK; subtotal+VAT==total; currency EUR approved
[Gate 5   routing         ] PASS  5788.11 EUR (rate 1.0 from identity) <= threshold 40000.0 EUR; single approval
[12/17] INV-2025-03847_V003_TotalRoute.pdf -> CLEARED_STANDARD - complete (22.2s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] FAIL  vendor V018 (OldGuard Security NV) is INACTIVE
[13/17] INV-2025-03880_V018_OldGuard_INACTIVE.pdf -> FLAGGED_INACTIVE_VENDOR - gate2.1 (10.9s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V007 (SecureGuard AG) score=1.0
[Gate 2.2 key-values      ] PASS
[Gate 3   dedup / PO      ] PASS  no historical duplicates; not on file - overdraw check skipped
[Gate 4   integrity       ] PASS  2 line items OK; subtotal+VAT==total; currency EUR approved
[Gate 5   routing         ] PASS  vendor V007 requires dual approval; 18499.5 EUR <= threshold 35000.0 EUR
[14/17] INV-2025-03901_V007_SecureGuard.pdf -> DUAL_APPROVAL - complete (22.1s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] FAIL  no vendor_master match for 'LogiTrans Express SRL' (best: DataSphere SAS @ 0.4571 < 0.7)
[15/17] INV-2025-03955_UNKNOWN_LogiTrans.pdf -> FLAGGED_UNKNOWN_VENDOR - gate2.1 (10.7s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V015 (QuickFix OÜ) score=1.0
[Gate 2.2 key-values      ] PASS
[Gate 3   dedup / PO      ] PASS  no historical duplicates; not on file - overdraw check skipped
[Gate 4   integrity       ] PASS  3 line items OK; subtotal+VAT==total; currency EUR approved
[Gate 5   routing         ] PASS  1606.5 EUR (rate 1.0 from identity) <= threshold 10000.0 EUR; single approval
[16/17] INV-2025-SCAN-001_V015_QuickFix.pdf -> CLEARED_STANDARD - complete (21.9s)
[Gate 1   duplicate hash   ] PASS
[Gate 2.1 vendor identity ] PASS  matched V016 (PolyClean Sp.z.o.o.) score=1.0
[Gate 2.2 key-values      ] PASS
[Gate 3   dedup / PO      ] PASS  no historical duplicates; not on file - overdraw check skipped
[Gate 4   integrity       ] PASS  3 line items OK; subtotal+VAT==total; currency EUR approved
[Gate 5   routing         ] PASS  2058.7 EUR (rate 1.0 from identity) <= threshold 6000.0 EUR; single approval
[17/17] INV-2025-SCAN-002_V016_PolyClean.pdf -> CLEARED_STANDARD - complete (22.5s)
=== BATCH SUMMARY batch_20261020_130914 ===
start_time       : 2026-10-20T13:02:55
end_time         : 2026-10-20T13:09:14
duration_seconds : 379.0
dry_run          : True
total_processed  : 17
status_counts    : CLEARED_STANDARD=12, FLAGGED_MISSING_PO=1, FLAGGED_EXTRACTION_MISMATCH=1, FLAGGED_INACTIVE_VENDOR=1, DUAL_APPROVAL=1, FLAGGED_UNKNOWN_VENDOR=1
------------------------------------------------------------------------------------
file_name                                status                         llm
INV-2025-03701_V001_EuroFuel.pdf         CLEARED_STANDARD               ready
INV-2025-03712_V004_FleetMech.pdf        CLEARED_STANDARD               ready
INV-2025-03719_V005_AutoServ.pdf         CLEARED_STANDARD               ready
INV-2025-03731_V006_BritTech_GBP.pdf     CLEARED_STANDARD               ready
INV-2025-03744_V008_CleanStation.pdf     CLEARED_STANDARD               ready
INV-2025-03752_V009_SparkIT_NoPO.pdf     FLAGGED_MISSING_PO             ready
INV-2025-03760_V010_StationOps.pdf       CLEARED_STANDARD               ready
INV-2025-03771_V012_MediaBoost.pdf       CLEARED_STANDARD               ready
INV-2025-03779_V013_NordClean.pdf        CLEARED_STANDARD               ready
INV-2025-03788_V002_AlpinaDiesel.pdf     FLAGGED_EXTRACTION_MISMATCH    ready
INV-2025-03791_V014_IberMaint.pdf        CLEARED_STANDARD               ready
INV-2025-03847_V003_TotalRoute.pdf       CLEARED_STANDARD               ready
INV-2025-03880_V018_OldGuard_INACTIVE.pdf FLAGGED_INACTIVE_VENDOR        ready
INV-2025-03901_V007_SecureGuard.pdf      DUAL_APPROVAL                  ready
INV-2025-03955_UNKNOWN_LogiTrans.pdf     FLAGGED_UNKNOWN_VENDOR         ready
INV-2025-SCAN-001_V015_QuickFix.pdf      CLEARED_STANDARD               ready
INV-2025-SCAN-002_V016_PolyClean.pdf     CLEARED_STANDARD               ready
REPORT WRITTEN batch_reports\batch_20261020_130914.json
```

---

## 4. Results per invoice

| # | File | Final status | Stopped at | Vendor | Amount (EUR) | Route / flag reason |
|---|---|---|---|---|---|---|
| 1 | INV-2025-03701_V001_EuroFuel.pdf | CLEARED_STANDARD | complete | V001 | 8551.67 | Standard Approval Queue |
| 2 | INV-2025-03712_V004_FleetMech.pdf | CLEARED_STANDARD | complete | V004 | 6799.99 | Standard Approval Queue |
| 3 | INV-2025-03719_V005_AutoServ.pdf | CLEARED_STANDARD | complete | V005 | 5400.01 | Standard Approval Queue |
| 4 | INV-2025-03731_V006_BritTech_GBP.pdf | CLEARED_STANDARD | complete | V006 | 5932.48 | Standard Approval Queue (GBP 5000.00 → EUR @ 1.186971) |
| 5 | INV-2025-03744_V008_CleanStation.pdf | CLEARED_STANDARD | complete | V008 | 3199.99 | Standard Approval Queue |
| 6 | INV-2025-03752_V009_SparkIT_NoPO.pdf | FLAGGED_MISSING_PO | gate2.2 | V009 | — | No PO reference found on the invoice (mandatory field) |
| 7 | INV-2025-03760_V010_StationOps.pdf | CLEARED_STANDARD | complete | V010 | 10010.46 | Standard Approval Queue |
| 8 | INV-2025-03771_V012_MediaBoost.pdf | CLEARED_STANDARD | complete | V012 | 4512.02 | Standard Approval Queue |
| 9 | INV-2025-03779_V013_NordClean.pdf | CLEARED_STANDARD | complete | V013 | 2900.01 | Standard Approval Queue |
| 10 | INV-2025-03788_V002_AlpinaDiesel.pdf | FLAGGED_EXTRACTION_MISMATCH | gate2.2 | V002 | — | PDF text total 42121.24 vs vision LLM total 2121.24 — needs human review |
| 11 | INV-2025-03791_V014_IberMaint.pdf | CLEARED_STANDARD | complete | V014 | 8200.00 | Standard Approval Queue |
| 12 | INV-2025-03847_V003_TotalRoute.pdf | CLEARED_STANDARD | complete | V003 | 5788.11 | Standard Approval Queue |
| 13 | INV-2025-03880_V018_OldGuard_INACTIVE.pdf | FLAGGED_INACTIVE_VENDOR | gate2.1 | V018 | — | Vendor V018 (OldGuard Security NV) is INACTIVE |
| 14 | INV-2025-03901_V007_SecureGuard.pdf | DUAL_APPROVAL | complete | V007 | 18499.50 | Dual Approval Queue (vendor requires two approvers) |
| 15 | INV-2025-03955_UNKNOWN_LogiTrans.pdf | FLAGGED_UNKNOWN_VENDOR | gate2.1 | — | — | No vendor_master match for 'LogiTrans Express SRL' (best: DataSphere SAS @ 0.4571 < 0.7) |
| 16 | INV-2025-SCAN-001_V015_QuickFix.pdf | CLEARED_STANDARD | complete | V015 | 1606.50 | Standard Approval Queue |
| 17 | INV-2025-SCAN-002_V016_PolyClean.pdf | CLEARED_STANDARD | complete | V016 | 2058.70 | Standard Approval Queue |

`—` means the invoice stopped before Gate 5, so no EUR-normalized amount is
computed (flags never reach routing).

### Status counts

| Status | Count |
|---|---|
| CLEARED_STANDARD | 12 |
| DUAL_APPROVAL | 1 |
| FLAGGED_MISSING_PO | 1 |
| FLAGGED_EXTRACTION_MISMATCH | 1 |
| FLAGGED_INACTIVE_VENDOR | 1 |
| FLAGGED_UNKNOWN_VENDOR | 1 |
| **Total** | **17** |

Every scenario in the reference data is exercised: a clean pass, a missing PO,
an inactive vendor, an unknown vendor, a text-vs-vision total mismatch, a
dual-approval vendor and a foreign-currency (GBP) invoice.

---

## 5. Machine-readable report

The batch report JSON contains the same result plus SHA-256 fingerprints and
LLM provenance per file. A copy is included with this submission:

```text
sample_output/batch_20261020_130914.json   (copy, committed)
batch_reports/batch_20261020_130914.json   (original, written by the run, not committed)
```

Top level:

```json
{
  "batch_id": "batch_20261020_130914",
  "start_time": "2026-10-20T13:02:55",
  "end_time": "2026-10-20T13:09:14",
  "duration_seconds": 379.0,
  "dry_run": true,
  "total_processed": 17,
  "status_counts": {
    "CLEARED_STANDARD": 12,
    "FLAGGED_MISSING_PO": 1,
    "FLAGGED_EXTRACTION_MISMATCH": 1,
    "FLAGGED_INACTIVE_VENDOR": 1,
    "DUAL_APPROVAL": 1,
    "FLAGGED_UNKNOWN_VENDOR": 1
  }
}
```

Example record (first file):

```json
{
  "file_name": "INV-2025-03701_V001_EuroFuel.pdf",
  "sha256": "0c7201a2a566d2e80f5c5d6baef2ec1fe855be8e7b1c9eb5818b0b9418ca5bc8",
  "status": "CLEARED_STANDARD",
  "gate_reached": "complete",
  "flag_reason": null,
  "routed_to": "Standard Approval Queue",
  "llm_status": "ready",
  "llm_model": "qwen2.5vl:3b",
  "invoice_id": "INV-2025-03701",
  "vendor_id": "V001",
  "amount_eur": 8551.67,
  "dry_run": true
}
```

---

## 6. Notes on this run

* **Dry run on purpose.** `--no-move` makes the database read-only and leaves
  the PDFs in place, so the sample can be reproduced without touching state.
  Verified after the run: `vendor_master` = 25 rows, `historic_invoices` = 120
  rows, `processed_invoices` = 0 rows, no `processed/` folder, 17 PDFs still in
  `invoices/`.
* **Which vision model actually ran.** The health check reports the primary
  model `llama3.2-vision:latest` as installed, but the per-invoice provenance
  records `qwen2.5vl:3b`. The Ollama build used for this run cannot load the
  primary model (its `mllama` architecture is unsupported by that build), so
  the approved fallback answered every invoice.

  `vision_llm.py ask()` treats that specific "cannot load here" error as a
  signal to move to the next approved candidate and records the model that
  actually answered. The behaviour is deterministic and auditable: the model
  name is stored per invoice (`llm_model`), and if no approved model can answer,
  the pipeline fails closed to `FLAGGED_LLM_UNAVAILABLE` instead of silently
  degrading to text-only.
* **FX rate source:** the GBP invoice used the live daily rate
  (`1.186971 from open.er-api.com`); all other invoices are EUR (rate 1.0 from
  the vendor master). Offline runs fall back to the static table.
* **Timing:** 21.9–25.9 s per invoice for the 14 invoices that reached the
  vision model, 10.7–10.9 s for the three that failed at Gate 2.1 (no vision
  call), 379.0 s for the batch.
* **Reproduce:**

  ```powershell
  python vision_llm.py --check
  python process_batch.py --input invoices --no-move
  ```

  A new report appears in `batch_reports/` with the current timestamp.
