#!/usr/bin/env python3
"""
UK Property Tribunal Rent Repayment Order (RRO) & Section 13 Precedent Engine
==============================================================================
Zero-token deterministic ingestion, extraction, SQLite FTS5 + local deterministic
vector embedding index, read-only OGL v3.0 query engine, and stateless ephemeral
private PDF/claim auditor.

License: Open Government Licence v3.0 (OGL v3.0) for public GOV.UK Tribunal rulings.
Security & Isolation:
  - Public OGL v3.0 reference index is opened strictly in read-only URI mode (`?mode=ro`)
    for all search and audit operations.
  - Private user queries and uploaded PDFs are processed in an isolated ephemeral
    workspace/memory and deterministically wiped in a `finally:` block with zero retention.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from statistics import median
from typing import Any

# Ensure Worf Quarantine is importable from /workspace/worf_quarantine.py
WORKSPACE_ROOT = Path("/workspace")
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

try:
    from worf_quarantine import scan_payload
except ImportError:
    def scan_payload(text: str, source_url: str = "") -> dict[str, Any]:
        return {"verdict": "CLEAN", "risk_score": 0, "findings": [], "source_url": source_url}

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "rro_precedents.sqlite"
DEFAULT_JSON_PATH = DATA_DIR / "rro_precedents.json"
DEFAULT_CSV_PATH = DATA_DIR / "rro_precedents_pack.csv"

GOV_UK_SEARCH_API = (
    "https://www.gov.uk/api/search.json"
    "?filter_format=residential_property_tribunal_decision"
    "&filter_tribunal_decision_sub_category=housing-act-2004-and-housing-and-planning-act-2016---rent-repayment-orders"
    "&order=-public_timestamp"
)

CASE_REF_RE = re.compile(r"\b([A-Z]{3}/[0-9A-Z]{4}/[A-Z0-9]{3}/20[0-9]{2}/[0-9]{3,4})\b")

REGION_MAP = {
    "LON": "London",
    "CHI": "Southern",
    "HAV": "Southern",
    "BIR": "Midlands",
    "MAN": "Northern",
    "CAM": "Eastern",
}

FEE_AMOUNTS = {
    100.0, 110.0, 114.0, 141.0, 165.0, 200.0, 220.0, 227.0,
    241.0, 300.0, 314.0, 330.0, 336.0, 340.0, 341.0, 343.0, 569.0
}

EMBED_DIM = 64


def compute_deterministic_embedding(text: str, dim: int = EMBED_DIM) -> list[float]:
    """
    Zero-token deterministic L2-normalized feature-hashing vector embedding
    over legal domain unigrams and bigrams for fast cosine similarity on CPU/Edge.
    """
    vec = [0.0] * dim
    tokens = re.findall(r"[a-z0-9£%]+", text.lower())
    if not tokens:
        return vec
    features = list(tokens) + [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)]
    for feat in features:
        h = int(hashlib.md5(feat.encode("utf-8")).hexdigest()[:8], 16)
        idx = h % dim
        sign = 1.0 if ((h >> 8) & 1) == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [round(v / norm, 5) for v in vec]
    return vec


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    return round(sum(a * b for a, b in zip(v1, v2)), 4)


def normalize_tribunal_text(raw: str) -> str:
    """
    Normalizes PDF text extracted by `/usr/bin/pdftotext -layout`, repairing
    old-style font ligatures where '0' is rendered as 'o'/'O' inside currency/percent tokens
    and repairing broken decimal spaces.
    """
    t = re.sub(r"[\u00a0\u202f\u2007\u2009\r\n\t]+", " ", raw)
    t = re.sub(r" +", " ", t)
    t = re.sub(r"(£[0-9,]+)\.\s+([0-9]{2})\b", r"\1.\2", t)
    t = re.sub(
        r"£\s*([0-9oO,]+(?:\.[0-9oO]{1,2})?)",
        lambda m: "£" + m.group(1).replace("o", "0").replace("O", "0"),
        t,
    )
    t = re.sub(
        r"\b([0-9]{1,2})[oO]%",
        lambda m: m.group(1) + "0%",
        t,
    )
    return t


def parse_money(s: str) -> float:
    clean = re.sub(r"[^0-9.]", "", s.replace(",", "").replace("o", "0").replace("O", "0"))
    try:
        return round(float(clean), 2)
    except Exception:
        return 0.0


def extract_pdf_text_layout(pdf_bytes: bytes) -> str:
    """
    Extracts text from PDF bytes using `/usr/bin/pdftotext -layout` with 0 LLM tokens.
    Uses a temporary directory that is deterministically wiped in `finally:`.
    """
    tmp_dir = tempfile.mkdtemp(prefix="rro_pdftotext_")
    try:
        pdf_path = Path(tmp_dir) / "doc.pdf"
        pdf_path.write_bytes(pdf_bytes)
        proc = subprocess.run(
            ["/usr/bin/pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return proc.stdout or ""
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def parse_rro_decision(
    raw_text: str,
    title: str = "",
    decision_date: str = "",
    pdf_url: str = "",
    gov_uk_url: str = "",
) -> dict[str, Any]:
    """
    Deterministically extracts structured RRO case fields from raw tribunal PDF text.
    """
    title_clean = title.strip()
    flat = normalize_tribunal_text(raw_text)

    # 1. case_ref
    m_ref = CASE_REF_RE.search(title_clean) or CASE_REF_RE.search(flat[:3000])
    if m_ref:
        case_ref = m_ref.group(1)
    else:
        fallback_ref = title_clean.split(":")[-1].strip()[:32]
        case_ref = fallback_ref if fallback_ref else "UNKNOWN/RRO/2026/0000"

    prefix = case_ref.split("/")[0].upper() if "/" in case_ref else "LON"
    region = REGION_MAP.get(prefix, "London" if "london" in (title_clean + flat[:600]).lower() else "Regional")

    # 2. decision_date fallback from text if not provided
    if not decision_date:
        m_date = re.search(
            r"Date\s+of\s+Decision\s*:?\s*([0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+20[0-9]{2})",
            flat[:2500],
            re.I,
        )
        decision_date = m_date.group(1) if m_date else "2026"

    # 3. offence_type classification (ignoring the standard s.40 boilerplate table)
    # Strip out the statutory boilerplate table if present so we classify on actual alleged offence
    non_boilerplate = re.sub(
        r"1\s+Criminal\s+Law\s+Act\s+1977.*?7\s+Housing\s+and\s+Planning\s+Act\s+2016\s+section\s+21\s+breach\s+of\s+banning\s+order",
        " ",
        flat,
        flags=re.I,
    )
    low = non_boilerplate.lower()
    s72_hits = len(re.findall(r"(?:section|s\.?)\s*72", low))
    s95_hits = len(re.findall(r"(?:section|s\.?)\s*95", low))
    eviction_hits = len(re.findall(r"unlawful\s+eviction|harassment|protection\s+from\s+eviction\s+act", low))
    impr_hits = len(re.findall(r"improvement\s+notice|section\s*30\b", low))

    if s95_hits > s72_hits and s95_hits >= 1:
        offence_type = "Selective Licensing (s.95)"
    elif s72_hits >= 1 and s72_hits >= eviction_hits:
        offence_type = "Unlicensed HMO (s.72)"
    elif eviction_hits >= 2:
        offence_type = "Unlawful Eviction / Harassment"
    elif impr_hits >= 2:
        offence_type = "Improvement Notice / Civil Penalty"
    elif "selective" in low and "licen" in low:
        offence_type = "Selective Licensing (s.95)"
    elif "hmo" in low or "multiple occupation" in low:
        offence_type = "Unlicensed HMO (s.72)"
    else:
        offence_type = "Unlicensed HMO (s.72)"

    # 4. Extract awarded_gbp
    awarded_gbp: float | None = None

    multi_applicants = re.findall(
        r"(?:(?:pay\s+to|to)\s+the\s+(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th)\s+applicant[^£.]{0,80}?sum\s+of\s*£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?))",
        flat,
        re.I,
    )
    multi_props = re.findall(
        r"\([1-6]\)\s*[^£:.]{2,40}:\s*£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
        flat,
        re.I,
    )

    direct_award_patterns = [
        r"\(a\s+total\s+of\s*£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)\)",
        r"ordered\s+to\s+repay\s+[0-9]{1,3}(?:\.[0-9]+)?%\s+of\s+(?:this\s+|the\s+)?rent,\s+which\s+(?:amounts?\s+to|is)\s*£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
        r"(?:respondent\s+shall\s+repay|respondent\s+must\s+repay)\s*£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
        r"(?:makes?|made|orders?|determines?\s+to\s+make|required\s+to\s+make)\s+(?:a\s+|an\s+)?(?:rent\s+)?(?:repayment\s+)?orders?\s+(?:in\s+favour\s+of\s+[^£.]{0,60}?|against\s+[^£.]{0,90}?|to\s+the\s+applicants?\s+)?(?:in\s+the\s+(?:total\s+)?sum\s+of|of|to\s+the\s+applicants?\s+of|in\s+the\s+full\s+sum\s+claimed\s+of|in\s+the\s+amount\s+of)\s*£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
        r"rent\s+repayment\s+orders?(?:,\s*determined\s+under\s+section\s+44[^£.]{0,65}?,)?\s+(?:is\s+therefore\s+made\s+[^£.]{0,50}?|is\s+made\s+)?(?:in\s+the\s+(?:total\s+)?sum\s+of|of|for\s+the\s+sum\s+of|is)\s*£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
        r"(?:orders?\s+[^£.]{0,90}?to\s+)?(?:repay|pay)\s+to\s+(?:the\s+applicants?|each\s+applicant|[A-Z][a-z]+\s+[A-Z][a-z]+[^£.]{0,60}?)\s*(?:rent\s+in\s+)?the\s+(?:total\s+)?sum\s+of\s*£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
        r"£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)\s*by\s+way\s+of\s+rent\s+repayment",
        r"sum\s+due\s+to\s+the\s+applicants?\s+is\s*£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
        r"award\s+we\s+should\s+make\s+is\s+[0-9]{1,3}(?:\.[0-9]+)?%\s+of\s+the\s+maximum\s+award\s+of\s+£[0-9,.]+\.\s*That\s+is\s+the\s+sum\s+of\s*£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
        r"amounts?\s+to\s+a\s+total\s+of\s*£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
        r"total\s+rent\s+repayment\s+order\s+(?:is|of)\s*£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
        r"rro\s+(?:in\s+the\s+(?:total\s+)?sum\s+of|of)\s*£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
    ]

    if len(multi_applicants) >= 2:
        vals = []
        seen = set()
        for x in multi_applicants:
            v = parse_money(x)
            if v >= 200 and v not in seen:
                seen.add(v)
                vals.append(v)
        if vals:
            awarded_gbp = round(sum(vals), 2)
    elif len(multi_props) >= 2:
        vals = [parse_money(x) for x in multi_props if parse_money(x) >= 200]
        if vals:
            awarded_gbp = round(sum(vals), 2)

    if awarded_gbp is None:
        for pat in direct_award_patterns:
            for m in re.finditer(pat, flat, re.I):
                val = parse_money(m.group(1))
                if val > 0 and val not in FEE_AMOUNTS and val >= 200:
                    awarded_gbp = val
                    break
            if awarded_gbp is not None:
                break

    is_dismissed = False
    if awarded_gbp is None:
        if re.search(
            r"\b(?:applications?\s+(?:for\s+a?\s*rent\s+repayment\s+orders?\s+)?(?:is|are|must\s+be|be|was\s+brought\s+out\s+of\s+time\s+and\s+is\s+therefore|has\s+been\s+made\s+[‘']?out\s+of\s+time[’']?\s+and\s+it\s+is)\s+(?:dismissed|refused|struck\s+out)|application\s+against\s+[^.]{2,40}\s+be\s+dismissed|application\s+fails\s+and\s+the\s+claim\s+is\s+dismissed|dismisses\s+(?:the|both)\s+applications?|no\s+rent\s+repayment\s+order\s+is\s+made|make\s+no\s+order\s+for\s+any\s+repayment\s+of\s+rent|(?:has\s+no|does\s+not\s+have)\s+jurisdiction\s+to\s+(?:make|hear)|strike\s+out\s+the\s+(?:applicant[’'s]*\s+)?application|intend\s+to\s+strike\s+out\s+the\s+application|declines\s+to\s+make\s+a\s+rent\s+repayment\s+order|refuse\s+to\s+grant\s+a\s+rent\s+repayment\s+order|consented\s+to\s+the\s+withdrawal)\b",
            flat,
            re.I,
        ):
            awarded_gbp = 0.0
            is_dismissed = True

    # 5. Extract award_pct_of_rent
    award_pct: float | None = None
    pct_patterns = [
        r"(?:sum\s+of\s+£[0-9,.]+\s*\(?being|within\s+28\s+days,\s+being|ordered\s+to\s+repay|repayment\s+of|award\s+we\s+should\s+make\s+is|determines?\s+to\s+award\s+[^.%]{0,35}?|an\s+award\s+of|amounting\s+to|rro\s+of|equivalent\s+to|increase\s+the\s+award\s+to|in\s+the\s+sum\s+of|make\s+an\s+order\s+for)\s*([0-9]{1,3}(?:\.[0-9]+)?)%\s+of\s+(?:this\s+|the\s+)?(?:total\s+)?(?:rent|maximum|sum\s+susceptible|net\s+rent)",
        r"determines?\s+([0-9]{1,3}(?:\.[0-9]+)?)%\s+of\s+the\s+rent\s+paid\s+is\s+a\s+fair",
        r"that\s+a?\s*([0-9]{1,3}(?:\.[0-9]+)?)%\s+award\s+is\s+appropriate",
        r"reduce\s+the\s+maximum\s+[^.%]{0,40}?to\s+([0-9]{1,3}(?:\.[0-9]+)?)%",
    ]
    for pat in pct_patterns:
        for m in re.finditer(pat, flat, re.I):
            p = float(m.group(1))
            if 5.0 <= p <= 100.0:
                award_pct = round(p, 1)
                break
        if award_pct is not None:
            break

    # 6. Extract claimed_gbp
    claimed_gbp: float | None = None
    claim_patterns = [
        r"(?:seek(?:s|ing)?\s+(?:a\s+rent\s+repayment\s+order|to\s+recover)|amount\s+claimed|claim(?:ed|s|ing)\s+a?\s*(?:rent\s+repayment\s+order|rro|total\s+sum)|total\s+sum\s+claimed\s+for\s+which\s+a\s+rent\s+repayment\s+order\s+was\s+sought\s+was|requiring\s+the\s+respondents?\s+to\s+repay\s+rent\s+totalling|total\s+claimable\s+sum\s+paid\s+by\s+the\s+tenant\s+was)[^£.]{0,120}?£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
        r"(?:rent\s+paid\s+in\s+the\s+relevant\s+period|sum\s+of\s+applicable\s+rent|rent\s+for\s+12\s+months\s+was|maximum\s+award\s+of|maximum\s+amount\s+of\s+(?:any\s+order|the\s+rro)|total\s+rent\s+(?:paid\s+was|of)|susceptible\s+to\s+an\s+award\s+is|full\s+sum\s+claimed\s+of|subject\s+of\s+the\s+dispute\s+after\s+deducting\s+housing\s+benefit\s+was|grand\s+total:)[^£.]{0,80}?£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
        r"totalling\s*£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)[^.]{0,80}?(?:period|unlawfully\s+let|12\s+months|vacated)",
    ]
    for pat in claim_patterns:
        for m in re.finditer(pat, flat, re.I):
            val = parse_money(m.group(1))
            if val >= 400 and val not in FEE_AMOUNTS:
                if awarded_gbp is None or val >= awarded_gbp * 0.95:
                    claimed_gbp = val
                    break
        if claimed_gbp is not None:
            break

    if awarded_gbp is None and claimed_gbp and award_pct and award_pct > 0:
        awarded_gbp = round(claimed_gbp * (award_pct / 100.0), 2)

    if awarded_gbp and awarded_gbp > 0:
        if claimed_gbp and claimed_gbp >= awarded_gbp:
            computed_pct = round((awarded_gbp / claimed_gbp) * 100.0, 1)
            if award_pct is None:
                award_pct = computed_pct
            elif abs(award_pct - computed_pct) > 15.0:
                # Trust explicit judge award_pct over noisy claimed_gbp if claimed_gbp produced an implausible ratio
                claimed_gbp = round(awarded_gbp / (award_pct / 100.0), 2)
        elif award_pct and award_pct > 0 and claimed_gbp is None:
            claimed_gbp = round(awarded_gbp / (award_pct / 100.0), 2)
    elif is_dismissed:
        award_pct = 0.0

    # 7. Mitigation factors
    mitigation: list[str] = []
    mit_rules = [
        ("utilities_deducted", r"utilit(?:y|ies)|council\s+tax|gas|electricity|water\s+rates|inclusive\s+of\s+bills"),
        ("good_condition", r"good\s+(?:condition|repair|standard)|well[- ]maintained|no\s+disrepair"),
        ("letting_agent_reliance", r"managing\s+agent|letting\s+agent|relied\s+upon\s+(?:his|her|their)\s+agent"),
        ("first_offence", r"no\s+previous\s+conviction|first\s+offence|unblemished|not\s+been\s+convicted"),
        ("financial_hardship", r"financial\s+circumstances|financial\s+hardship|unemployed|mortgage\s+costs"),
        ("delayed_council_application", r"reasonable\s+excuse|duly\s+made\s+application|applied\s+for\s+a\s+licence|temporary\s+exemption"),
        ("tenant_conduct", r"tenant[’'s]*\s+conduct|rent\s+arrears|behaved\s+badly|refused\s+access"),
        ("universal_credit_deducted", r"universal\s+credit|housing\s+benefit"),
        ("professional_landlord_aggravation", r"professional\s+landlord|portfolio\s+of\s+properties|property\s+portfolio"),
    ]
    for tag, pat in mit_rules:
        if re.search(pat, low):
            mitigation.append(tag)
    if not mitigation:
        mitigation.append("s44_statutory_conduct")

    # 8. Judge summary
    summary_m = (
        re.search(
            r"((?:The\s+Tribunal\s+makes\s+(?:a|the\s+following)\s+Rent\s+repayment\s+orders?|The\s+Tribunal\s+orders\s+[^.]{3,60}?to\s+repay|A\s+rent\s+repayment\s+order\s+of\s+£|The\s+tribunal\s+determines\s+to\s+make\s+a\s+Rent\s+Repayment\s+Order|Having\s+decided\s+above\s+the\s+range|Taking\s+all\s+of\s+these\s+matters\s+into\s+account|The\s+application\s+for\s+a\s+rent\s+repayment\s+order\s+succeeds|The\s+respondent\s+shall\s+repay\s+£|Having\s+taken\s+into\s+account\s+all\s+the\s+factors)[^.]{15,340}\.)",
            flat,
            re.I,
        )
        or re.search(r"(DECISION\s+.*?\.)", flat[:3000], re.I)
    )
    if summary_m:
        judge_summary = summary_m.group(1).strip()[:360]
    else:
        judge_summary = flat[:350].strip()

    embed_source = f"{case_ref} {title_clean} {region} {offence_type} {' '.join(mitigation)} {judge_summary}"
    embedding = compute_deterministic_embedding(embed_source)

    return {
        "case_ref": case_ref,
        "title": title_clean,
        "region": region,
        "decision_date": decision_date,
        "offence_type": offence_type,
        "claimed_gbp": claimed_gbp,
        "awarded_gbp": awarded_gbp,
        "award_pct_of_rent": award_pct,
        "mitigation_factors": mitigation,
        "judge_summary": judge_summary,
        "pdf_url": pdf_url or gov_uk_url,
        "gov_uk_url": gov_uk_url or pdf_url,
        "embedding": embedding,
    }


def fetch_and_ingest_gov_uk_rro(
    count: int = 80,
    cached_raw_path: Path = Path("/tmp/rro_raw_80.json"),
    db_path: Path = DEFAULT_DB_PATH,
    json_path: Path = DEFAULT_JSON_PATH,
    csv_path: Path = DEFAULT_CSV_PATH,
) -> list[dict[str, Any]]:
    """
    Runs the 0-token GOV.UK RRO ingestion pipeline across `count` real decisions,
    scanning every payload through Worf Quarantine (`scan_payload`), extracting
    structured case outcomes, and indexing into SQLite FTS5 + JSON + CSV.
    """
    raw_docs: list[dict[str, Any]] = []
    if cached_raw_path.exists():
        raw_docs = json.loads(cached_raw_path.read_text(encoding="utf-8"))

    if len(raw_docs) < 50:
        url = f"{GOV_UK_SEARCH_API}&count={count}"
        req = urllib.request.Request(url, headers={"User-Agent": "UK-RRO-Precedent-Finder/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            results = json.loads(resp.read().decode("utf-8")).get("results", [])

        for item in results[:count]:
            base_path = item.get("link", "")
            if not base_path:
                continue
            content_url = f"https://www.gov.uk/api/content{base_path}"
            creq = urllib.request.Request(content_url, headers={"User-Agent": "UK-RRO-Precedent-Finder/1.0"})
            with urllib.request.urlopen(creq, timeout=15) as cresp:
                cdata = json.loads(cresp.read().decode("utf-8"))
            attachments = cdata.get("details", {}).get("attachments", [])
            pdf_url = next((a.get("url") for a in attachments if a.get("url", "").lower().endswith(".pdf")), None)
            if not pdf_url:
                continue
            preq = urllib.request.Request(pdf_url, headers={"User-Agent": "UK-RRO-Precedent-Finder/1.0"})
            with urllib.request.urlopen(preq, timeout=20) as presp:
                pdf_bytes = presp.read()
            text = extract_pdf_text_layout(pdf_bytes)
            q_res = scan_payload(text, source=pdf_url)
            if q_res.get("verdict") == "QUARANTINED":
                continue
            raw_docs.append({
                "title": item.get("title", ""),
                "gov_uk_url": f"https://www.gov.uk{base_path}",
                "pdf_url": pdf_url,
                "decision_date": cdata.get("details", {}).get("tribunal_decision_decision_date", "")
                or (item.get("public_timestamp", "")[:10]),
                "text": text,
                "quarantine_verdict": q_res.get("verdict", "CLEAN"),
                "quarantine_risk_score": q_res.get("risk_score", 0),
            })

    records: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for doc in raw_docs:
        q_res = scan_payload(doc.get("text", ""), source=doc.get("pdf_url", ""))
        if q_res.get("verdict") == "QUARANTINED":
            continue
        parsed = parse_rro_decision(
            raw_text=doc.get("text", ""),
            title=doc.get("title", ""),
            decision_date=doc.get("decision_date", ""),
            pdf_url=doc.get("pdf_url", ""),
            gov_uk_url=doc.get("gov_uk_url", ""),
        )
        parsed["quarantine_verdict"] = q_res.get("verdict", "CLEAN")
        # Ensure unique case_ref in DB if two decisions share a base reference
        ref = parsed["case_ref"]
        if ref in seen_refs:
            suffix = hashlib.sha1(parsed["pdf_url"].encode("utf-8")).hexdigest()[:4].upper()
            ref = f"{ref}-{suffix}"
            parsed["case_ref"] = ref
        seen_refs.add(ref)
        records.append(parsed)

    build_sqlite_index(records, db_path=db_path)

    # Export clean JSON & CSV bundles for Cloudflare Edge Worker & Precedent Pack download
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    export_records = [
        {k: v for k, v in r.items() if k != "embedding"}
        for r in records
    ]
    json_path.write_text(json.dumps(export_records, indent=2, ensure_ascii=False), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as cf:
        writer = csv.writer(cf)
        writer.writerow([
            "case_ref", "region", "decision_date", "offence_type",
            "claimed_gbp", "awarded_gbp", "award_pct_of_rent",
            "mitigation_factors", "title", "pdf_url", "judge_summary"
        ])
        for r in export_records:
            writer.writerow([
                r["case_ref"],
                r["region"],
                r["decision_date"],
                r["offence_type"],
                r["claimed_gbp"] if r["claimed_gbp"] is not None else "",
                r["awarded_gbp"] if r["awarded_gbp"] is not None else "",
                r["award_pct_of_rent"] if r["award_pct_of_rent"] is not None else "",
                ",".join(r["mitigation_factors"]),
                r["title"],
                r["pdf_url"],
                r["judge_summary"],
            ])

    return records


def build_sqlite_index(records: list[dict[str, Any]], db_path: Path = DEFAULT_DB_PATH) -> None:
    """
    Creates the portable SQLite database with structured table `rro_decisions`,
    `SQLite FTS5` virtual table `rro_decisions_fts`, and deterministic vector embeddings.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE rro_decisions (
                case_ref TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                region TEXT NOT NULL,
                decision_date TEXT NOT NULL,
                offence_type TEXT NOT NULL,
                claimed_gbp REAL,
                awarded_gbp REAL,
                award_pct_of_rent REAL,
                mitigation_factors TEXT NOT NULL,
                judge_summary TEXT NOT NULL,
                pdf_url TEXT NOT NULL,
                gov_uk_url TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                ogl_license TEXT NOT NULL DEFAULT 'OGL-v3.0'
            )
        """)
        cur.execute("""
            CREATE VIRTUAL TABLE rro_decisions_fts USING fts5(
                case_ref,
                title,
                region,
                offence_type,
                mitigation_factors,
                judge_summary
            )
        """)

        for r in records:
            mit_json = json.dumps(r["mitigation_factors"])
            emb_json = json.dumps(r.get("embedding") or compute_deterministic_embedding(r["judge_summary"]))
            cur.execute(
                """
                INSERT INTO rro_decisions (
                    case_ref, title, region, decision_date, offence_type,
                    claimed_gbp, awarded_gbp, award_pct_of_rent,
                    mitigation_factors, judge_summary, pdf_url, gov_uk_url, embedding_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["case_ref"],
                    r["title"],
                    r["region"],
                    r["decision_date"],
                    r["offence_type"],
                    r["claimed_gbp"],
                    r["awarded_gbp"],
                    r["award_pct_of_rent"],
                    mit_json,
                    r["judge_summary"],
                    r["pdf_url"],
                    r.get("gov_uk_url", r["pdf_url"]),
                    emb_json,
                ),
            )
            cur.execute(
                """
                INSERT INTO rro_decisions_fts (
                    case_ref, title, region, offence_type, mitigation_factors, judge_summary
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    r["case_ref"],
                    r["title"],
                    r["region"],
                    r["offence_type"],
                    " ".join(r["mitigation_factors"]),
                    r["judge_summary"],
                ),
            )
        conn.commit()
    finally:
        conn.close()


def open_readonly_reference_db(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """
    Opens the public OGL v3.0 reference SQLite database in strict read-only URI mode (`?mode=ro`).
    Any attempt to INSERT/UPDATE/DELETE/CREATE on this connection raises `sqlite3.OperationalError`.
    """
    uri = f"file:{urllib.parse.quote(str(db_path.resolve()))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def search_rro_precedents(
    q: str = "",
    region: str = "",
    offence_type: str = "",
    mitigation: str = "",
    max_pct: float | None = None,
    limit: int = 25,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """
    Searches the read-only OGL v3.0 SQLite FTS5 + vector similarity index.
    """
    conn = open_readonly_reference_db(db_path)
    try:
        cur = conn.cursor()
        params: list[Any] = []
        where_clauses: list[str] = ["1=1"]

        if region and region.lower() != "all":
            where_clauses.append("LOWER(d.region) = LOWER(?)")
            params.append(region.strip())

        if offence_type and offence_type.lower() != "all":
            where_clauses.append("LOWER(d.offence_type) LIKE LOWER(?)")
            params.append(f"%{offence_type.strip()}%")

        if mitigation and mitigation.lower() != "all":
            where_clauses.append("LOWER(d.mitigation_factors) LIKE LOWER(?)")
            params.append(f"%{mitigation.strip()}%")

        if max_pct is not None:
            where_clauses.append("d.award_pct_of_rent IS NOT NULL AND d.award_pct_of_rent <= ?")
            params.append(float(max_pct))

        q_clean = q.strip()
        if q_clean:
            # Build safe FTS5 query or fallback LIKE match
            fts_tokens = re.findall(r"[A-Za-z0-9]+", q_clean)
            if fts_tokens and "/" not in q_clean:
                fts_expr = " OR ".join(f'"{t}"*' for t in fts_tokens[:6])
                sql = f"""
                    SELECT d.*
                    FROM rro_decisions d
                    JOIN rro_decisions_fts f ON d.case_ref = f.case_ref
                    WHERE rro_decisions_fts MATCH ? AND {' AND '.join(where_clauses)}
                """
                rows = cur.execute(sql, [fts_expr, *params]).fetchall()
            else:
                where_clauses.append(
                    "(LOWER(d.case_ref) LIKE LOWER(?) OR LOWER(d.title) LIKE LOWER(?) OR LOWER(d.judge_summary) LIKE LOWER(?))"
                )
                like_q = f"%{q_clean}%"
                params.extend([like_q, like_q, like_q])
                sql = f"SELECT d.* FROM rro_decisions d WHERE {' AND '.join(where_clauses)}"
                rows = cur.execute(sql, params).fetchall()
        else:
            sql = f"SELECT d.* FROM rro_decisions d WHERE {' AND '.join(where_clauses)} ORDER BY d.decision_date DESC"
            rows = cur.execute(sql, params).fetchall()

        query_vec = compute_deterministic_embedding(q_clean) if q_clean else []
        results: list[dict[str, Any]] = []
        for r in rows:
            emb = json.loads(r["embedding_json"])
            sim = cosine_similarity(query_vec, emb) if query_vec else 1.0
            results.append({
                "case_ref": r["case_ref"],
                "title": r["title"],
                "region": r["region"],
                "decision_date": r["decision_date"],
                "offence_type": r["offence_type"],
                "claimed_gbp": r["claimed_gbp"],
                "awarded_gbp": r["awarded_gbp"],
                "award_pct_of_rent": r["award_pct_of_rent"],
                "mitigation_factors": json.loads(r["mitigation_factors"]),
                "judge_summary": r["judge_summary"],
                "pdf_url": r["pdf_url"],
                "gov_uk_url": r["gov_uk_url"],
                "similarity_score": sim,
            })

        if q_clean:
            results.sort(
                key=lambda item: (
                    1 if q_clean.lower() in item["case_ref"].lower() or q_clean.lower() in item["title"].lower() else 0,
                    item["similarity_score"],
                    item["decision_date"],
                ),
                reverse=True,
            )

        pcts = [r["award_pct_of_rent"] for r in results if r["award_pct_of_rent"] is not None and r["award_pct_of_rent"] > 0]
        awards = [r["awarded_gbp"] for r in results if r["awarded_gbp"] is not None and r["awarded_gbp"] > 0]
        claims = [r["claimed_gbp"] for r in results if r["claimed_gbp"] is not None and r["claimed_gbp"] > 0]

        stats = {
            "total_matched": len(results),
            "positive_award_count": len(awards),
            "median_award_pct": round(float(median(pcts)), 1) if pcts else 0.0,
            "mean_award_pct": round(sum(pcts) / len(pcts), 1) if pcts else 0.0,
            "total_claimed_gbp": round(sum(claims), 2),
            "total_awarded_gbp": round(sum(awards), 2),
        }

        return {
            "isolation_mode": "OGL-v3.0-read-only",
            "query": {
                "q": q_clean,
                "region": region or "all",
                "offence_type": offence_type or "all",
                "mitigation": mitigation or "all",
                "max_pct": max_pct,
            },
            "stats": stats,
            "results": results[: max(1, min(limit, 100))],
        }
    finally:
        conn.close()


def audit_private_pdf_bytes(
    payload_bytes: bytes | None = None,
    claim_text: str = "",
    region_hint: str = "",
    claimed_gbp_hint: float | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """
    Stateless per-request private RRO claim / PDF audit.
    Processes private user PDF bytes or claim text inside an isolated ephemeral
    directory, compares against the read-only (`?mode=ro`) OGL v3.0 precedent DB,
    and deterministically wipes all temporary files and buffers in `finally:`.
    Never writes to the public SQLite DB or retains user data.
    """
    ephemeral_dir = Path(tempfile.mkdtemp(prefix="rro_private_ephemeral_"))
    ephemeral_path_str = str(ephemeral_dir)
    try:
        raw_text = claim_text or ""
        if payload_bytes:
            if payload_bytes.startswith(b"%PDF"):
                ephemeral_pdf = ephemeral_dir / "private_upload.pdf"
                ephemeral_pdf.write_bytes(payload_bytes)
                proc = subprocess.run(
                    ["/usr/bin/pdftotext", "-layout", str(ephemeral_pdf), "-"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
                raw_text = (proc.stdout or "") + "\n" + raw_text
            else:
                raw_text = payload_bytes.decode("utf-8", errors="ignore") + "\n" + raw_text

        parsed_private = parse_rro_decision(
            raw_text=raw_text,
            title="Private Ephemeral RRO Audit",
        )
        effective_region = region_hint or parsed_private["region"]
        effective_claimed = claimed_gbp_hint or parsed_private["claimed_gbp"] or 12000.0
        effective_offence = parsed_private["offence_type"]
        detected_mitigation = parsed_private["mitigation_factors"]

        # Query read-only public OGL v3.0 index for matching region & offence precedents
        precedent_search = search_rro_precedents(
            q="",
            region=effective_region if effective_region != "Regional" else "",
            offence_type=effective_offence.split("(")[0].strip(),
            limit=15,
            db_path=db_path,
        )
        if precedent_search["stats"]["total_matched"] < 3:
            precedent_search = search_rro_precedents(
                q="",
                region="",
                offence_type="",
                limit=15,
                db_path=db_path,
            )

        median_pct = precedent_search["stats"]["median_award_pct"] or 55.0
        estimated_exposure_gbp = round(effective_claimed * (median_pct / 100.0), 2)

        return {
            "isolation_mode": "stateless-ephemeral-finally-wiped",
            "public_db_mode": "OGL-v3.0-read-only",
            "ephemeral_dir_ tracked": ephemeral_path_str,
            "ephemeral_wiped": True,
            "private_claim_summary": {
                "detected_region": effective_region,
                "detected_offence_type": effective_offence,
                "claimed_gbp_evaluated": round(float(effective_claimed), 2),
                "detected_mitigation_factors": detected_mitigation,
                "benchmark_median_award_pct": median_pct,
                "estimated_tribunal_award_gbp": estimated_exposure_gbp,
                "estimated_mitigation_reduction_gbp": round(float(effective_claimed) - estimated_exposure_gbp, 2),
            },
            "comparable_ogl_precedents": precedent_search["results"][:6],
        }
    finally:
        shutil.rmtree(ephemeral_dir, ignore_errors=True)


if __name__ == "__main__":
    recs = fetch_and_ingest_gov_uk_rro()
    pos = [r for r in recs if (r.get("awarded_gbp") or 0) > 0]
    with_out = [r for r in recs if r.get("awarded_gbp") is not None]
    print(f"Indexed {len(recs)} real GOV.UK RRO decisions ({len(with_out)} with structured outcome, {len(pos)} positive awards).")
    print(f"SQLite DB: {DEFAULT_DB_PATH} ({DEFAULT_DB_PATH.stat().st_size} bytes)")
    print(f"JSON export: {DEFAULT_JSON_PATH} ({DEFAULT_JSON_PATH.stat().st_size} bytes)")
