#!/usr/bin/env python3
"""
Gate 2.1 - Ultra-Light Vendor Identity Check (low compute, pre-LLM).

Action:     Extract text from the top 20% of page 1 (vendor header block only)
            to get Vendor Name, Country and VAT ID - no line-item parsing.
            The local vision LLM (vision_llm.py) independently reads the same
            letterhead on EVERY invoice; both extractions are cross-checked.
Validation: Fuzzy-match the name against vendor_master (exact, then
            Levenshtein-style ratio with legal-entity suffixes stripped).
Fail-fast:  Unknown vendor            -> FLAG (Unknown Vendor)
            vendor status = INACTIVE  -> FLAG (Inactive Vendor)
            text vs vision disagree   -> FLAG (Extraction Mismatch, review)
            LLM enabled but unusable  -> FLAG (LLM Unavailable / LLM Error)
            LLM switched off          -> text-only path, recorded as disabled

Standalone: python gate2a_vendor_identity.py <invoice.pdf>
"""

import json
import re
import sqlite3
import sys
from difflib import SequenceMatcher
from pathlib import Path

import fitz  # PyMuPDF

import vision_llm

DB_PATH = Path(__file__).resolve().parent / "ap_automation.db"

HEADER_FRACTION = 0.20          # only read the top 20% of the page
MATCH_THRESHOLD = 0.70          # fuzzy score below this == unknown vendor
VISION_AGREE_THRESHOLD = 0.75   # text-name vs vision-name similarity floor

# Legal-entity tokens ignored when comparing names ("AutoServ S.R.L." == "AutoServ")
LEGAL_TOKENS = {"gmbh", "ag", "bv", "nv", "sa", "srl", "ltd", "limited", "plc",
                "ou", "aps", "sas", "kg", "se", "co", "inc", "corp", "s", "a",
                "r", "l", "z", "oo", "sp", "b", "v", "sarlu", "spa", "sarl"}

FLAG_UNKNOWN_VENDOR = "UNKNOWN_VENDOR"
FLAG_INACTIVE_VENDOR = "INACTIVE_VENDOR"
FLAG_EXTRACTION_MISMATCH = "EXTRACTION_MISMATCH"


def _norm_id(value) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _header_text(pdf_path) -> str:
    """Text layer of the top 20% of page 1 (vendor letterhead)."""
    with fitz.open(pdf_path) as doc:
        page = doc[0]
        clip = fitz.Rect(0, 0, page.rect.width, page.rect.height * HEADER_FRACTION)
        return page.get_text(clip=clip)


def _normalize(name: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", name.lower()).split())


def _strip_legal(name: str) -> str:
    tokens = [t for t in _normalize(name).split() if t not in LEGAL_TOKENS]
    return " ".join(tokens)


def _similarity(a: str, b: str) -> float:
    """Best of: raw-normalized ratio and legal-suffix-stripped ratio."""
    score = SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()
    score = max(score, SequenceMatcher(None, _strip_legal(a), _strip_legal(b)).ratio())
    return round(score, 4)


def extract_identity(pdf_path) -> dict:
    """Pull vendor name / VAT id / country out of the letterhead block."""
    lines = [ln.strip() for ln in _header_text(pdf_path).splitlines() if ln.strip()]
    vendor_name = lines[0] if lines else None
    header = "\n".join(lines)
    vat = re.search(r"\bVAT\s*:\s*([A-Z0-9\-\.]+)", header)
    # Address line like "80331 Munich, Germany" -> country after the last comma
    country = None
    for line in lines[1:5]:
        if "," in line and not line.upper().startswith("VAT"):
            country = line.rsplit(",", 1)[-1].strip()
            break
    return {"vendor_name_raw": vendor_name,
            "vat_id": vat.group(1) if vat else None,
            "invoice_country": country}


def match_vendor(pdf_path, conn=None, db_path=None, name_override=None) -> dict:
    """Identity extraction + vendor_master lookup.

    name_override: use this name instead of the PDF-text one (vision fallback
    for documents whose letterhead text could not be read).
    db_path:       database to open when no connection is supplied.
    """
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(DB_PATH if db_path is None else Path(db_path))
    conn.row_factory = sqlite3.Row
    try:
        identity = extract_identity(pdf_path)
        candidates = [dict(r) for r in conn.execute("SELECT * FROM vendor_master")]
    finally:
        if own_conn:
            conn.close()

    lookup_name = name_override or identity["vendor_name_raw"] or ""
    best, best_score = None, 0.0
    for cand in candidates:
        score = _similarity(lookup_name, cand["vendor_name"])
        if score > best_score:
            best, best_score = cand, score

    matched = best is not None and best_score >= MATCH_THRESHOLD
    return {"identity": identity, "vendor": best if matched else None,
            "lookup_name": lookup_name,
            "match_score": best_score if matched else None,
            "best_candidate": best["vendor_name"] if best else None,
            "best_candidate_score": best_score,
            "matched": matched}


def _attach_identity(result: dict, info: dict) -> dict:
    """Attach the text-path identity even when the LLM check fails."""
    result.update({"identity": info["identity"],
                   "lookup_name": info["lookup_name"],
                   "match_score": info["match_score"],
                   "best_candidate": info["best_candidate"],
                   "best_candidate_score": info["best_candidate_score"]})
    return result


def run(pdf_path, db_path=None) -> dict:
    """Return gate verdict with the matched vendor_master row attached."""
    db_path = DB_PATH if db_path is None else Path(db_path)
    result = {"gate": "gate2a_vendor_identity", "passed": True, "flag": None,
              "reason": None, "vendor": None, "cross_check": {}, "llm": None}
    if not db_path.exists():
        result["passed"] = False
        result["reason"] = "database missing - run setup_db.py first"
        return result

    info = match_vendor(pdf_path, db_path=db_path)

    # --- preflight check, then vision LLM extraction ----------------------
    llm = vision_llm.check_llm()
    result["llm"] = llm
    if not llm["enabled"]:
        vision = {"status": "disabled", "fields": None,
                  "detail": llm.get("detail") or "vision LLM switched off"}
    elif not llm["ok"]:
        detail = llm.get("detail") or f"vision LLM status={llm['status']}"
        flag = (vision_llm.FLAG_LLM_UNAVAILABLE
                if llm["status"] == "unavailable" else vision_llm.FLAG_LLM_ERROR)
        result.update({"vision": {"status": llm["status"], "fields": None,
                                  "detail": detail},
                       "passed": False, "flag": flag,
                       "reason": f"required vision LLM is not usable: {detail}"})
        return _attach_identity(result, info)
    else:
        try:
            vision = {"status": "ok", "fields": vision_llm.extract_identity(pdf_path)}
        except vision_llm.VisionUnavailable as exc:
            result.update({"vision": {"status": "unavailable", "fields": None,
                                      "detail": str(exc)},
                           "passed": False,
                           "flag": vision_llm.FLAG_LLM_UNAVAILABLE,
                           "reason": f"required vision LLM is not usable: {exc}"})
            return _attach_identity(result, info)
        except Exception as exc:
            result.update({"vision": {"status": "error", "fields": None,
                                      "detail": str(exc)},
                           "passed": False,
                           "flag": vision_llm.FLAG_LLM_ERROR,
                           "reason": f"required vision LLM failed: {exc}"})
            return _attach_identity(result, info)
    result["vision"] = vision

    # --- cross-check text extraction vs vision extraction -------------------
    cross = result["cross_check"]
    text_name = info["identity"]["vendor_name_raw"]
    vfields = vision["fields"] or {}
    vname = vfields.get("vendor_name") or None
    if vision["status"] == "ok":
        t_vat, v_vat = (_norm_id(info["identity"].get("vat_id")),
                        _norm_id(vfields.get("vat_id")))
        if t_vat and v_vat and t_vat != v_vat:
            cross["vat_note"] = (f"text {info['identity'].get('vat_id')} vs "
                                 f"vision {vfields.get('vat_id')}")
        t_country = (info["identity"].get("invoice_country") or "").strip().lower()
        v_country = (vfields.get("country") or "").strip().lower()
        if t_country and v_country and t_country != v_country:
            cross["country_note"] = (f"text {info['identity'].get('invoice_country')} "
                                     f"vs vision {vfields.get('country')}")
        if not text_name and vname:
            # letterhead unreadable as text (image-only scan): vision takes over
            info = match_vendor(pdf_path, db_path=db_path, name_override=vname)
            cross["name"] = f"adopted vision name '{vname}' (text unreadable)"
        elif text_name and vname:
            name_sim = _similarity(text_name, vname)
            cross["name_similarity"] = name_sim
            if name_sim < VISION_AGREE_THRESHOLD:
                result.update({"passed": False, "flag": FLAG_EXTRACTION_MISMATCH,
                               "reason": (f"extraction mismatch: PDF text says "
                                          f"'{text_name}' but vision LLM says "
                                          f"'{vname}' (similarity {name_sim}) - "
                                          f"needs human review")})
                return result

    _attach_identity(result, info)

    if not info["matched"]:
        result["passed"] = False
        result["flag"] = FLAG_UNKNOWN_VENDOR
        result["reason"] = (f"no vendor_master match for "
                            f"'{info['lookup_name']}' "
                            f"(best: {info['best_candidate']} "
                            f"@ {info['best_candidate_score']} < {MATCH_THRESHOLD})")
        return result

    vendor = info["vendor"]
    result["vendor"] = vendor
    if vendor["status"].upper() != "ACTIVE":
        result["passed"] = False
        result["flag"] = FLAG_INACTIVE_VENDOR
        result["reason"] = (f"vendor {vendor['vendor_id']} ({vendor['vendor_name']}) "
                            f"is {vendor['status']}")
    else:
        result["reason"] = (f"matched {vendor['vendor_id']} "
                            f"({vendor['vendor_name']}) score={info['match_score']}")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python gate2a_vendor_identity.py <invoice.pdf>")
    print(json.dumps(run(sys.argv[1]), indent=2, default=str))
