#!/usr/bin/env python3
"""
Gate 2.2 - Document-Level Key-Value Extraction (low compute, no line items).

Action:     Locate header labels across the page and extract Invoice Number,
            Invoice Date, PO Reference and Total Amount (subtotal + VAT for the
            later integrity cross-check). No line-item table parsing here.
            The local vision LLM (vision_llm.py) independently reads the same
            fields on EVERY invoice; both extractions are cross-checked:
              - both present and disagree -> FLAG (Extraction Mismatch)
              - text missing, vision has it -> adopted (noted in the verdict);
                a PO is only adopted this way for image-only scans, never when
                the text layer shows an explicit blank PO field.
Validation: PO_Number must be present.
Fail-fast:  Missing PO -> FLAG (Missing Mandatory PO) and terminate.
            LLM enabled but unusable -> FLAG (LLM Unavailable / LLM Error).
            LLM switched off -> text-only path, recorded as disabled.

Standalone: python gate2b_key_value_extract.py <invoice.pdf>
"""

import json
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

import vision_llm

FLAG_MISSING_PO = "MISSING_MANDATORY_PO"
FLAG_EXTRACTION_MISMATCH = "EXTRACTION_MISMATCH"

SCAN_TEXT_CHARS = 50   # fewer chars than this == image-only scan (no text layer)
NUMBER_TOLERANCE = 0.01

_NUMBER = r"\d[\d,]*(?:\.\d+)?"

# Fields where a text/vision disagreement fails the gate
STRICT_FIELDS = ("invoice_number", "invoice_date", "po_number",
                 "total_amount", "currency")
# Fields where a disagreement is only noted (Gate 4 re-verifies the math)
NOTE_FIELDS = ("subtotal", "vat_percent", "vat_amount")


def parse_amount(text: str):
    """'EUR 42,121.24' -> 42121.24 (currency symbols stripped)."""
    if text is None:
        return None
    cleaned = re.sub(r"[^\d,.\-]", "", str(text)).replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _join_wrap(whole: str, tail) -> str:
    """Some PDFs wrap long totals across lines ('10,010.4' + '6' -> '10,010.46',
    or '4' + '2,121.24' -> '42,121.24'). Re-join only when the first fragment is
    clearly truncated (no decimals or a single decimal digit)."""
    if not tail:
        return whole
    decimals = whole.split(".", 1)[1] if "." in whole else None
    return whole + tail if decimals is None or len(decimals) == 1 else whole


def extract_metadata(pdf_path) -> dict:
    """Extract header key-values from the full text layer."""
    with fitz.open(pdf_path) as doc:
        text = "\n".join(page.get_text() for page in doc)

    def find(pattern, default=None):
        m = re.search(pattern, text)
        return m.group(1) if m else default

    def labeled_amount(label_pattern):
        m = re.search(rf"{label_pattern}[^0-9]*?({_NUMBER})(?:\r?\n({_NUMBER}))?", text)
        if not m:
            return None
        return parse_amount(_join_wrap(m.group(1), m.group(2)))

    invoice_number = find(r"Invoice\s*(?:Number|No)\.?\s*[:#]?\s*([A-Za-z0-9][\w\-/\.]*)")
    invoice_date = find(r"(?:Invoice\s*)?Date\s*:\s*(\d{4}-\d{2}-\d{2})")
    po_number = find(r"PO\s*(?:Reference|Ref|No)\.?\s*:\s*(PO-\d+)")
    total = labeled_amount(r"TOTAL")
    subtotal = labeled_amount(r"Subtotal")
    m_vat = re.search(
        rf"VAT[^0-9]*?(\d+(?:\.\d+)?)\s*%[^0-9]*?({_NUMBER})(?:\r?\n({_NUMBER}))?", text)
    vat_pct = float(m_vat.group(1)) if m_vat else None
    vat_amount = (parse_amount(_join_wrap(m_vat.group(2), m_vat.group(3)))
                  if m_vat else None)
    currency = find(r"\b(EUR|GBP|USD|CHF)\b")

    return {"invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "po_number": po_number,
            "total_amount": total,
            "subtotal": subtotal,
            "vat_percent": vat_pct,
            "vat_amount": vat_amount,
            "currency": currency,
            "text_chars": len(text)}


def _disagree(field: str, text_value, vision_value) -> bool:
    if field in ("total_amount", "subtotal", "vat_percent", "vat_amount"):
        try:
            return abs(_as_number(text_value) - _as_number(vision_value)) > NUMBER_TOLERANCE
        except (TypeError, ValueError):
            return True
    return str(text_value).strip() != str(vision_value).strip()


def _as_number(value):
    if isinstance(value, (int, float)):
        return float(value)
    return parse_amount(str(value))


def run(pdf_path) -> dict:
    """Return gate verdict with extracted metadata attached."""
    meta = extract_metadata(pdf_path)
    result = {"gate": "gate2b_key_value_extract", "passed": True, "flag": None,
              "reason": None, "metadata": meta, "cross_check": {}, "llm": None}
    cross = result["cross_check"]

    # --- preflight check, then vision LLM extraction ----------------------
    llm = vision_llm.check_llm()
    result["llm"] = llm
    if not llm["enabled"]:
        vfields = {}
        result["vision"] = {"status": "disabled", "fields": None,
                            "detail": llm.get("detail") or "vision LLM switched off"}
    elif not llm["ok"]:
        detail = llm.get("detail") or f"vision LLM status={llm['status']}"
        flag = (vision_llm.FLAG_LLM_UNAVAILABLE
                if llm["status"] == "unavailable" else vision_llm.FLAG_LLM_ERROR)
        result.update({"vision": {"status": llm["status"], "fields": None,
                                  "detail": detail},
                       "passed": False, "flag": flag,
                       "reason": f"required vision LLM is not usable: {detail}"})
        return result
    else:
        try:
            vfields = vision_llm.extract_metadata(pdf_path) or {}
            result["vision"] = {"status": "ok", "fields": vfields}
        except vision_llm.VisionUnavailable as exc:
            result.update({"vision": {"status": "unavailable", "fields": None,
                                      "detail": str(exc)},
                           "passed": False,
                           "flag": vision_llm.FLAG_LLM_UNAVAILABLE,
                           "reason": f"required vision LLM is not usable: {exc}"})
            return result
        except Exception as exc:
            result.update({"vision": {"status": "error", "fields": None,
                                      "detail": str(exc)},
                           "passed": False,
                           "flag": vision_llm.FLAG_LLM_ERROR,
                           "reason": f"required vision LLM failed: {exc}"})
            return result

    # --- cross-check text extraction vs vision extraction -------------------
    if vfields:
        for field in STRICT_FIELDS:
            text_value, vision_value = meta.get(field), vfields.get(field)
            has_vision = vision_value not in (None, "")
            if text_value is None and has_vision:
                if field == "po_number" and meta.get("text_chars", 0) >= SCAN_TEXT_CHARS:
                    # Text layer exists and its PO field is blank: do not let the
                    # LLM fill a mandatory field - surface it for the reviewer.
                    cross["po_not_adopted"] = (f"vision LLM reported '{vision_value}' "
                                               f"but the document's PO field is blank "
                                               f"in the text layer - verify manually")
                else:
                    meta[field] = (_as_number(vision_value)
                                   if field == "total_amount" else vision_value)
                    meta[f"{field}_source"] = "vision"
                    cross[f"{field}_adopted"] = vision_value
            elif text_value is not None and has_vision and _disagree(field, text_value, vision_value):
                result.update({"passed": False, "flag": FLAG_EXTRACTION_MISMATCH,
                               "reason": (f"extraction mismatch on {field}: PDF text -> "
                                          f"{text_value!r} vs vision LLM -> "
                                          f"{vision_value!r} - needs human review")})
                return result
        for field in NOTE_FIELDS:
            text_value, vision_value = meta.get(field), vfields.get(field)
            has_vision = vision_value not in (None, "")
            if text_value is None and has_vision:
                meta[field] = _as_number(vision_value) if field != "vat_percent" else vision_value
                meta[f"{field}_source"] = "vision"
            elif text_value is not None and has_vision and _disagree(field, text_value, vision_value):
                cross[f"{field}_note"] = f"text {text_value} vs vision {vision_value}"

    missing = [k for k, v in meta.items() if v is None and k != "po_number"]
    if missing:
        result["reason"] = "note: could not extract " + ", ".join(missing)

    if not meta["po_number"]:
        result["passed"] = False
        result["flag"] = FLAG_MISSING_PO
        result["reason"] = "no PO reference found on the invoice (mandatory field)"
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python gate2b_key_value_extract.py <invoice.pdf>")
    print(json.dumps(run(sys.argv[1]), indent=2, default=str))
