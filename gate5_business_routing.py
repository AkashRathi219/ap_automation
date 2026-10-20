#!/usr/bin/env python3
"""
Gate 5 - Business Rules & Routing (no extraction, pure rules).

Validation 1 (FX conversion):   Non-EUR totals are converted to EUR using the
            daily FX rate API (open.er-api.com); a static fallback table keeps
            the pipeline working offline.
Validation 2 (Approval routing): requires_dual_approval = TRUE -> Dual
            Approval Queue, regardless of amount.
Validation 3 (Spend thresholds): EUR total > vendor spend_threshold_eur
                                 -> FLAG (Threshold Breach). A dual-approval
            vendor above threshold stays in the Dual Approval Queue and the
            threshold breach is recorded as an additional reason.

Standalone: python gate5_business_routing.py <invoice.pdf>
            (re-runs Gate 2 extraction to obtain metadata/vendor context)
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from gate2a_vendor_identity import match_vendor
from gate2b_key_value_extract import extract_metadata

FX_API_URL = "https://open.er-api.com/v6/latest/{currency}"
FX_TIMEOUT_SECONDS = 4
FALLBACK_FX_TO_EUR = {"EUR": 1.0, "GBP": 1.17, "USD": 0.92, "CHF": 1.06}

FLAG_THRESHOLD_BREACH = "SPEND_THRESHOLD_BREACH"

STATUS_CLEARED = "CLEARED_STANDARD"
STATUS_DUAL_APPROVAL = "DUAL_APPROVAL"
STATUS_THRESHOLD_BREACH = "FLAGGED_THRESHOLD_BREACH"

QUEUE_STANDARD = "Standard Approval Queue"
QUEUE_DUAL = "Dual Approval Queue"
QUEUE_REVIEW = "AP Review Queue"


def get_fx_rate_to_eur(currency: str) -> tuple:
    """Return (rate, source) for currency->EUR. Live API first, static fallback."""
    currency = (currency or "EUR").upper()
    if currency == "EUR":
        return 1.0, "identity"
    try:
        with urllib.request.urlopen(
                FX_API_URL.format(currency=currency),
                timeout=FX_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rate = data.get("rates", {}).get("EUR")
        if rate:
            return float(rate), "open.er-api.com"
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        pass
    return FALLBACK_FX_TO_EUR.get(currency, 1.0), "fallback_table"


def run(pdf_path, vendor=None, metadata=None) -> dict:
    """Return the final routing verdict for the invoice."""
    result = {"gate": "gate5_business_routing", "passed": True, "flag": None,
              "reason": None, "status": STATUS_CLEARED, "routed_to": QUEUE_STANDARD}

    if metadata is None:
        metadata = extract_metadata(pdf_path)
    if vendor is None:
        vendor = match_vendor(pdf_path)["vendor"]
    if vendor is None or metadata.get("total_amount") is None:
        result.update({"passed": False, "flag": "MISSING_CONTEXT",
                       "status": "FLAGGED_PROCESSING_ERROR",
                       "routed_to": QUEUE_REVIEW,
                       "reason": "vendor or total amount unavailable - run Gate 2 first"})
        return result

    currency = (metadata.get("currency") or vendor["approved_currency"]).upper()

    # Validation 1: FX conversion to EUR ----------------------------------
    rate, rate_source = get_fx_rate_to_eur(currency)
    amount_eur = round(metadata["total_amount"] * rate, 2)
    result.update({"amount_eur": amount_eur, "fx_rate": round(rate, 6),
                   "fx_source": rate_source})

    # Validation 2: approval routing (dual approval is checked first, because
    # the vendor requires it regardless of amount) -------------------------
    threshold = vendor["spend_threshold_eur"]
    over_threshold = amount_eur > threshold
    dual_required = bool(vendor["requires_dual_approval"])
    result.update({"dual_required": dual_required,
                   "threshold_breached": over_threshold})

    if dual_required:
        if over_threshold:
            result.update({
                "passed": False,
                "flag": FLAG_THRESHOLD_BREACH,
                "status": STATUS_DUAL_APPROVAL,
                "routed_to": QUEUE_DUAL,
                "reason": (f"vendor {vendor['vendor_id']} requires dual approval "
                           f"regardless of amount; {amount_eur} EUR also exceeds "
                           f"threshold {threshold} EUR"),
            })
        else:
            result.update({
                "status": STATUS_DUAL_APPROVAL,
                "routed_to": QUEUE_DUAL,
                "reason": (f"vendor {vendor['vendor_id']} requires dual "
                           f"approval; {amount_eur} EUR <= threshold "
                           f"{threshold} EUR"),
            })
        return result

    # Validation 3: spend threshold ---------------------------------------
    if over_threshold:
        result.update({"passed": False, "flag": FLAG_THRESHOLD_BREACH,
                       "status": STATUS_THRESHOLD_BREACH,
                       "routed_to": QUEUE_REVIEW,
                       "reason": (f"{amount_eur} EUR exceeds threshold "
                                  f"{threshold} EUR for {vendor['vendor_id']}")})
        return result

    result["reason"] = (f"{amount_eur} EUR (rate {rate} from {rate_source}) "
                        f"<= threshold {threshold} EUR; single approval")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python gate5_business_routing.py <invoice.pdf>")
    print(json.dumps(run(sys.argv[1]), indent=2, default=str))
