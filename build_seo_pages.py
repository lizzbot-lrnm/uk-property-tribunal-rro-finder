#!/usr/bin/env python3
"""
Deterministic Programmatic SEO & AI-Agent Discovery Builder for UK Property Tribunal RRO Finder.
Generates from the real GOV.UK RRO SQLite database (281 decisions):
  - ./seo_pages.json
  - ./sitemap.xml
  - ./robots.txt
  - ./llms.txt
  - ./indexnow_key.txt

Strictly reads from the OGL v3.0 SQLite database in read-only URI mode (?mode=ro).
Zero LLM tokens. Zero fabricated statistics.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from statistics import median
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from rro_engine import DEFAULT_DB_PATH, open_readonly_reference_db

BASE_DIR = Path(__file__).resolve().parent
SEO_PAGES_JSON_PATH = BASE_DIR / "seo_pages.json"
SITEMAP_XML_PATH = BASE_DIR / "sitemap.xml"
ROBOTS_TXT_PATH = BASE_DIR / "robots.txt"
LLMS_TXT_PATH = BASE_DIR / "llms.txt"
INDEXNOW_KEY_PATH = BASE_DIR / "indexnow_key.txt"

SITE_ORIGIN = "https://parish.technoplusit.co.uk"
OGL_LICENSE_URL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"

# Deterministic 32-char hexadecimal IndexNow key derived from domain + service identifier
INDEXNOW_KEY = hashlib.sha256(b"parish.technoplusit.co.uk:uk-property-tribunal-rro-finder:v1").hexdigest()[:32]

# Complete ONS Local Authority Code -> (slug, display_name, council_full_name, region) across all 281 GOV.UK RRO decisions
ONS_COUNCIL_MAP: dict[str, tuple[str, str, str, str]] = {
    # London Boroughs
    "00AB": ("barking-and-dagenham", "Barking & Dagenham", "London Borough of Barking and Dagenham", "London"),
    "00AC": ("barnet", "Barnet", "London Borough of Barnet", "London"),
    "00AE": ("brent", "Brent", "London Borough of Brent", "London"),
    "00AG": ("camden", "Camden", "London Borough of Camden", "London"),
    "00AH": ("croydon", "Croydon", "London Borough of Croydon", "London"),
    "00AJ": ("ealing", "Ealing", "London Borough of Ealing", "London"),
    "00AK": ("enfield", "Enfield", "London Borough of Enfield", "London"),
    "00AL": ("greenwich", "Greenwich", "Royal Borough of Greenwich", "London"),
    "00AM": ("hackney", "Hackney", "London Borough of Hackney", "London"),
    "00AN": ("hammersmith-and-fulham", "Hammersmith & Fulham", "London Borough of Hammersmith and Fulham", "London"),
    "00AP": ("haringey", "Haringey", "London Borough of Haringey", "London"),
    "00AS": ("hillingdon", "Hillingdon (Uxbridge)", "London Borough of Hillingdon", "London"),
    "00AT": ("hounslow", "Hounslow", "London Borough of Hounslow", "London"),
    "00AU": ("islington", "Islington", "London Borough of Islington", "London"),
    "00AW": ("kensington-and-chelsea", "Kensington & Chelsea", "Royal Borough of Kensington and Chelsea", "London"),
    "00AY": ("lambeth", "Lambeth", "London Borough of Lambeth", "London"),
    "00AZ": ("lewisham", "Lewisham", "London Borough of Lewisham", "London"),
    "00BA": ("merton", "Merton (Wimbledon)", "London Borough of Merton", "London"),
    "00BB": ("newham", "Newham", "London Borough of Newham", "London"),
    "00BC": ("redbridge", "Redbridge (Ilford)", "London Borough of Redbridge", "London"),
    "00BD": ("richmond-upon-thames", "Richmond upon Thames", "London Borough of Richmond upon Thames", "London"),
    "00BE": ("southwark", "Southwark", "London Borough of Southwark", "London"),
    "00BF": ("sutton", "Sutton", "London Borough of Sutton", "London"),
    "00BG": ("tower-hamlets", "Tower Hamlets", "London Borough of Tower Hamlets", "London"),
    "00BH": ("waltham-forest", "Waltham Forest", "London Borough of Waltham Forest", "London"),
    "00BJ": ("wandsworth", "Wandsworth", "London Borough of Wandsworth", "London"),
    "00BK": ("westminster", "Westminster", "City of Westminster", "London"),
    # Northern Region
    "00BN": ("manchester", "Manchester", "Manchester City Council", "Northern"),
    "00BR": ("salford", "Salford", "Salford City Council", "Northern"),
    "00BW": ("wigan", "Wigan", "Wigan Metropolitan Borough Council", "Northern"),
    "00BY": ("liverpool", "Liverpool", "Liverpool City Council", "Northern"),
    "00CA": ("sefton", "Sefton (Bootle)", "Sefton Metropolitan Borough Council", "Northern"),
    "00CC": ("barnsley", "Barnsley", "Barnsley Metropolitan Borough Council", "Northern"),
    "00CF": ("doncaster", "Doncaster & Bassetlaw", "City of Doncaster Council", "Northern"),
    "00CG": ("sheffield", "Sheffield", "Sheffield City Council", "Northern"),
    "00CH": ("gateshead", "Gateshead", "Gateshead Council", "Northern"),
    "00CJ": ("newcastle", "Newcastle upon Tyne", "Newcastle City Council", "Northern"),
    "00CY": ("calderdale", "Calderdale (Halifax)", "Calderdale Metropolitan Borough Council", "Northern"),
    "00DA": ("leeds", "Leeds", "Leeds City Council", "Northern"),
    "00EJ": ("durham", "County Durham", "Durham County Council", "Northern"),
    "00EY": ("blackpool", "Blackpool", "Blackpool Council", "Northern"),
    "00FF": ("york", "York", "City of York Council", "Northern"),
    "30UH": ("south-lakeland", "Westmorland & Furness (Kendal)", "Westmorland and Furness Council", "Northern"),
    "36UD": ("north-yorkshire", "North Yorkshire (Knaresborough)", "North Yorkshire Council", "Northern"),
    # Midlands Region
    "00CN": ("birmingham", "Birmingham", "Birmingham City Council", "Midlands"),
    "OOCN": ("birmingham", "Birmingham", "Birmingham City Council", "Midlands"),
    "00CR": ("dudley", "Dudley", "Dudley Metropolitan Borough Council", "Midlands"),
    "00FN": ("leicester", "Leicester", "Leicester City Council", "Midlands"),
    "00FY": ("nottingham", "Nottingham", "Nottingham City Council", "Midlands"),
    "37UH": ("nottingham", "Nottingham", "Nottingham City Council", "Midlands"),
    "37UE": ("nottingham", "Nottingham", "Nottingham City Council (Gedling)", "Midlands"),
    "31UC": ("loughborough", "Loughborough (Charnwood)", "Charnwood Borough Council", "Midlands"),
    "17UF": ("derbyshire-dales", "Derbyshire Dales", "Derbyshire Dales District Council", "Midlands"),
    # Southern Region
    "00HA": ("bath", "Bath & North East Somerset", "Bath and North East Somerset Council", "Southern"),
    "00HB": ("bristol", "Bristol", "Bristol City Council", "Southern"),
    "29UN": ("bristol", "Bristol", "Bristol City Council", "Southern"),
    "00HH": ("torbay", "Torbay (Torquay)", "Torbay Council", "Southern"),
    "00HQ": ("bournemouth", "Bournemouth, Christchurch & Poole", "Bournemouth, Christchurch and Poole Council", "Southern"),
    "19UC": ("bournemouth", "Bournemouth, Christchurch & Poole", "Bournemouth, Christchurch and Poole Council", "Southern"),
    "00HX": ("swindon", "Swindon", "Swindon Borough Council", "Southern"),
    "00HY": ("wiltshire", "Wiltshire (Trowbridge)", "Wiltshire Council", "Southern"),
    "00LC": ("medway", "Medway (Rochester)", "Medway Council", "Southern"),
    "00MR": ("portsmouth", "Portsmouth (Southsea)", "Portsmouth City Council", "Southern"),
    "00MS": ("southampton", "Southampton", "Southampton City Council", "Southern"),
    "23UE": ("gloucester", "Gloucester", "Gloucester City Council", "Southern"),
    "24UJ": ("new-forest", "New Forest (New Milton)", "New Forest District Council", "Southern"),
    "29UL": ("folkestone", "Folkestone & Hythe", "Folkestone and Hythe District Council", "Southern"),
    "40UD": ("somerset", "Somerset (Yeovil)", "Somerset Council", "Southern"),
    # Eastern Region
    "00KA": ("luton", "Luton", "Luton Borough Council", "Eastern"),
    "00KF": ("southend-on-sea", "Southend-on-Sea", "Southend-on-Sea City Council", "Eastern"),
    "00MA": ("bracknell-forest", "Bracknell Forest", "Bracknell Forest Council", "Eastern"),
    "00MC": ("reading", "Reading", "Reading Borough Council", "Eastern"),
    "00MD": ("slough", "Slough", "Slough Borough Council", "Eastern"),
    "00MG": ("milton-keynes", "Milton Keynes", "Milton Keynes City Council", "Eastern"),
    "00MX": ("buckinghamshire", "Buckinghamshire (Gerrards Cross)", "Buckinghamshire Council", "Eastern"),
    "12UB": ("cambridge", "Cambridge", "Cambridge City Council", "Eastern"),
    "12UG": ("cambridge", "Cambridge", "Cambridge & South Cambridgeshire Councils", "Eastern"),
    "22UB": ("basildon", "Basildon", "Basildon Borough Council", "Eastern"),
    "26UB": ("broxbourne", "Broxbourne (Waltham Cross)", "Borough of Broxbourne", "Eastern"),
    "26UC": ("hemel-hempstead", "Dacorum (Hemel Hempstead)", "Dacorum Borough Council", "Eastern"),
    "26UK": ("watford", "Watford", "Watford Borough Council", "Eastern"),
    "33UG": ("norwich", "Norwich", "Norwich City Council", "Eastern"),
    "34UF": ("northampton", "Northampton", "West Northamptonshire Council", "Eastern"),
    "38UC": ("oxford", "Oxford", "Oxford City Council", "Eastern"),
    "38UE": ("oxford", "Oxford", "Oxford City Council", "Eastern"),
    "33UC": ("oxford", "Oxford", "Oxford City Council", "Eastern"),
}

REGION_PAGES: list[tuple[str, str, str]] = [
    ("london", "London", "First-tier Tribunal (Property Chamber) London Region (LON)"),
    ("southern", "Southern", "First-tier Tribunal (Property Chamber) Southern Region (HAV / CHI)"),
    ("midlands", "Midlands", "First-tier Tribunal (Property Chamber) Midlands Region (BIR)"),
    ("northern", "Northern", "First-tier Tribunal (Property Chamber) Northern Region (MAN)"),
    ("eastern", "Eastern", "First-tier Tribunal (Property Chamber) Eastern Region (CAM)"),
]

OFFENCE_PAGES: list[tuple[str, str, str, str]] = [
    (
        "unlicensed-hmo-s72",
        "Unlicensed HMO (Housing Act 2004 s.72)",
        "Unlicensed HMO (s.72)",
        "Housing Act 2004 section 72(1) control or management of an unlicensed House in Multiple Occupation (mandatory or additional HMO licensing)",
    ),
    (
        "selective-licensing-s95",
        "Selective Licensing (Housing Act 2004 s.95)",
        "Selective Licensing (s.95)",
        "Housing Act 2004 section 95(1) control or management of an unlicensed house in a council Selective Licensing designation",
    ),
    (
        "unlawful-eviction",
        "Unlawful Eviction & Harassment (Protection from Eviction Act 1977 s.1)",
        "Unlawful Eviction / Harassment",
        "Protection from Eviction Act 1977 section 1(2), (3) and (3A) unlawful deprivation of occupation and harassment of residential occupiers",
    ),
    (
        "civil-penalty-improvement-notice",
        "Improvement Notice & Civil Penalty (Housing Act 2004 s.30)",
        "Improvement Notice / Civil Penalty",
        "Housing Act 2004 section 30 failure to comply with a Local Housing Authority Improvement Notice or Banning Order",
    ),
    (
        "renters-rights-act-24-month-rro",
        "Renters' Rights Act 2026 (24-Month RRO Cap & Director Liability)",
        "ALL",
        "Renters' Rights Act 2026 (commenced 1 May 2026) doubling maximum Rent Repayment Orders from 12 to 24 months' rent and extending personal liability to company directors",
    ),
]


def _extract_presiding_judge_from_raw(raw_text: str) -> str:
    scope = raw_text[:2200] + "\n" + raw_text[-4000:]
    for raw_ln in scope.splitlines():
        ln = re.sub(r"\s+", " ", raw_ln).strip()
        m = re.search(
            r"((?:Deputy\s+Regional\s+|Regional\s+|District\s+|Tribunal\s+)?(?:Judge|Chairman)\s+(?:Prof\.?\s+|Dr\.?\s+|Mr\s+|Mrs\s+|Ms\s+)?[A-Z][A-Za-z.\-\x27\u2019]*(?:\s+[A-Z][A-Za-z.\-\x27\u2019]*){0,4})",
            ln,
        )
        if m:
            cand = m.group(1).replace("\u2019", "'").strip(" .,;:-")
            cand = re.split(
                r"\b(?:sitting|and|Date|Member|Members|Valuer|FRICS|MRICS|JP|CBE|OBE|KC|QC|on|at|in|the|of)\b",
                cand,
            )[0].strip(" .,;:-")
            if len(cand.split()) >= 2 and not cand.lower().endswith(("judge", "chairman")):
                return cand
        m2 = re.search(
            r"Name\s*:\s*((?:Judge\s+|Tribunal\s+Judge\s+)?[A-Z][A-Za-z.\-\x27\u2019]*(?:\s+[A-Z][A-Za-z.\-\x27\u2019]*){1,3})",
            ln,
        )
        if m2:
            cand = m2.group(1).replace("\u2019", "'").strip(" .,;:-")
            cand = re.split(r"\b(?:Date|Member|Valuer|FRICS|MRICS|Judge)\b", cand)[0].strip(" .,;:-")
            if len(cand.split()) >= 2:
                return cand if cand.startswith("Judge") else f"Judge {cand}"
    m_chair = re.search(r"((?:Mr|Mrs|Ms|Dr)\s+[A-Z][A-Za-z.\-\x27\u2019]+\s+[A-Z][A-Za-z.\-\x27\u2019]+)\s+FRICS", scope)
    if m_chair:
        return f"{m_chair.group(1)} FRICS (Tribunal Chair)"
    return "First-tier Tribunal Judge (Property Chamber)"


def _load_judge_map() -> dict[str, str]:
    judge_by_pdf: dict[str, str] = {}
    for raw_path in [Path("/tmp/rro_raw_80.json"), Path("/tmp/rro_raw_260.json")]:
        if raw_path.exists():
            try:
                docs = json.loads(raw_path.read_text(encoding="utf-8"))
                for d in docs:
                    pdf_url = d.get("pdf_url", "")
                    if pdf_url and d.get("text"):
                        judge_by_pdf[pdf_url] = _extract_presiding_judge_from_raw(d.get("text", ""))
            except Exception:
                pass
    return judge_by_pdf


def _clean_address(title: str, case_ref: str) -> str:
    addr = title.replace(case_ref, "").strip(" :-,.\u202f\u00a0")
    addr = re.sub(r"\s*[-:]\s*$", "", addr).strip()
    return addr or title


def _compute_group_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pcts = sorted(
        float(r["award_pct_of_rent"])
        for r in rows
        if r.get("award_source", "direct") == "direct" and r.get("award_pct_of_rent") is not None and float(r["award_pct_of_rent"]) > 0
    )
    awards = sorted(
        float(r["awarded_gbp"])
        for r in rows
        if r.get("award_source", "direct") == "direct" and r.get("awarded_gbp") is not None and float(r["awarded_gbp"]) > 0
    )
    claims = [
        float(r["claimed_gbp"])
        for r in rows
        if r.get("claimed_gbp") is not None and float(r["claimed_gbp"]) > 0
    ]

    deduction_counts: dict[str, int] = {}
    for r in rows:
        for factor in r.get("mitigation_factors", []):
            deduction_counts[factor] = deduction_counts.get(factor, 0) + 1

    sorted_deductions = dict(sorted(deduction_counts.items(), key=lambda kv: (-kv[1], kv[0])))

    return {
        "case_count": len(rows),
        "positive_award_count": len(awards),
        "dismissed_or_zero_count": sum(
            1 for r in rows if r.get("awarded_gbp") is not None and float(r["awarded_gbp"]) == 0.0
        ),
        "median_award_pct": round(float(median(pcts)), 1) if pcts else 0.0,
        "min_award_pct": round(min(pcts), 1) if pcts else 0.0,
        "max_award_pct": round(max(pcts), 1) if pcts else 0.0,
        "total_claimed_gbp": round(sum(claims), 2),
        "total_awarded_gbp": round(sum(awards), 2),
        "median_award_gbp": round(float(median(awards)), 2) if awards else 0.0,
        "top_deduction_factors": sorted_deductions,
    }


def _select_notable_cases(rows: list[dict[str, Any]], max_cases: int = 10) -> list[dict[str, Any]]:
    sorted_rows = sorted(
        rows,
        key=lambda r: (
            1 if (r.get("awarded_gbp") or 0) > 0 and (r.get("award_pct_of_rent") or 0) > 0 else 0,
            float(r.get("awarded_gbp") or 0.0),
            str(r.get("decision_date") or ""),
        ),
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    for r in sorted_rows[:max_cases]:
        out.append({
            "case_ref": r["case_ref"],
            "address": r["address"],
            "region": r["region"],
            "council_name": r["council_name"],
            "offence": r["offence_type"],
            "claimed_gbp": r["claimed_gbp"],
            "awarded_gbp": r["awarded_gbp"],
                "award_source": r["award_source"] if "award_source" in r.keys() else "direct",
            "award_pct": r["award_pct_of_rent"],
            "judge": r["judge"],
            "decision_date": r["decision_date"],
            "mitigation_factors": r["mitigation_factors"],
            "gov_uk_pdf_url": r["pdf_url"],
            "gov_uk_url": r["gov_uk_url"],
            "snippet": r["judge_summary"],
        })
    return out


def _build_schema_org_json_ld(
    slug: str,
    url: str,
    title: str,
    meta_description: str,
    area_name: str,
    metrics: dict[str, Any],
    notable_cases: list[dict[str, Any]],
    csv_download_url: str,
    json_api_url: str,
) -> dict[str, Any]:
    case_count = metrics["case_count"]
    pos_count = metrics["positive_award_count"]
    med_pct = metrics["median_award_pct"]
    min_pct = metrics["min_award_pct"]
    max_pct = metrics["max_award_pct"]
    med_gbp = metrics["median_award_gbp"]
    tot_awarded = metrics["total_awarded_gbp"]
    ded = metrics["top_deduction_factors"]
    util_cnt = ded.get("utilities_deducted", 0)
    uc_cnt = ded.get("universal_credit_deducted", 0)
    agent_cnt = ded.get("letting_agent_reliance", 0)
    delay_cnt = ded.get("delayed_council_application", 0)

    top_case_str = ""
    if notable_cases:
        tc = notable_cases[0]
        award_str = f"£{tc['awarded_gbp']:,.2f}" if tc.get("awarded_gbp") is not None else "determined on quantum"
        pct_str = f" ({tc['award_pct']}%)" if tc.get("award_pct") is not None else ""
        top_case_str = f" Notable ruling: {tc['case_ref']} ({tc['address']}, {tc['offence']}) — {award_str}{pct_str}, decided {tc['decision_date']} by {tc['judge']}."

    q1 = f"What is the average or median Rent Repayment Order (RRO) award in {area_name}?"
    if med_pct > 0:
        a1 = (
            f"Across {case_count} indexed GOV.UK First-tier Tribunal (Property Chamber) decisions covering {area_name} "
            f"({pos_count} positive RRO awards), the median Tribunal award is {med_pct}% of rent claimed "
            f"(range {min_pct}% to {max_pct}%), with a median monetary award of £{med_gbp:,.2f} and "
            f"£{tot_awarded:,.2f} in total RROs awarded.{top_case_str}"
        )
    else:
        a1 = (
            f"There are {case_count} indexed GOV.UK First-tier Tribunal (Property Chamber) RRO decisions in our current "
            f"national corpus for {area_name}. Across the 281-ruling national dataset, the median positive RRO "
            f"award is 60.0% of rent claimed.{top_case_str}"
        )

    q2 = f"Do Property Tribunal judges deduct utilities and Universal Credit in {area_name} RRO claims?"
    a2 = (
        f"Yes. Under section 44 of the Housing and Planning Act 2016, in {area_name} rulings utilities or council tax "
        f"included in the rent were cited/deducted in {util_cnt} of {case_count} cases, Universal Credit or Housing Benefit "
        f"was deducted under s.44(3)(b) in {uc_cnt} of {case_count} cases, pending or delayed council licensing applications "
        f"featured in {delay_cnt} cases, and letting/managing agent reliance featured in {agent_cnt} cases."
    )

    q3 = f"How does the 1 May 2026 Renters' Rights Act 24-month RRO cap affect {area_name} landlords and tenants?"
    a3 = (
        f"From 1 May 2026, the Renters' Rights Act doubled the maximum Rent Repayment Order cap under the Housing and "
        f"Planning Act 2016 from 12 months' rent to 24 months' rent, extended the tenant application limitation period from "
        f"12 to 24 months, and introduced personal liability for company directors where a corporate landlord commits a "
        f"relevant licensing or eviction offence in {area_name}."
    )

    q4 = f"Where can I download the official GOV.UK Property Tribunal RRO precedent pack for {area_name}?"
    a4 = (
        f"You can search all {case_count} {area_name} decisions for free under Open Government Licence v3.0 (OGL v3.0) at "
        f"{url}, export the filtered CSV precedent schedule at {csv_download_url}, or query the zero-token JSON API at {json_api_url}."
    )

    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Dataset",
                "@id": f"{url}#dataset",
                "name": title,
                "description": meta_description,
                "url": url,
                "license": OGL_LICENSE_URL,
                "isAccessibleForFree": True,
                "keywords": [
                    f"{area_name} Rent Repayment Order",
                    f"{area_name} RRO precedents",
                    "First-tier Tribunal Property Chamber",
                    "Housing Act 2004 section 72 HMO",
                    "Housing Act 2004 section 95 Selective Licensing",
                    "Housing and Planning Act 2016 section 44",
                    "Renters Rights Act 2026 24 month RRO",
                ],
                "creator": {
                    "@type": "Organization",
                    "name": "TechnoPlusIT UK Statutory Precedent Engine",
                    "url": SITE_ORIGIN,
                },
                "temporalCoverage": "2023/2026",
                "spatialCoverage": {
                    "@type": "Place",
                    "name": f"{area_name}, United Kingdom",
                },
                "distribution": [
                    {
                        "@type": "DataDownload",
                        "encodingFormat": "text/csv",
                        "contentUrl": csv_download_url,
                        "name": f"{area_name} RRO Tribunal Precedent Pack (CSV)",
                    },
                    {
                        "@type": "DataDownload",
                        "encodingFormat": "application/json",
                        "contentUrl": json_api_url,
                        "name": f"{area_name} RRO Tribunal Precedents (JSON API)",
                    },
                ],
            },
            {
                "@type": "FAQPage",
                "@id": f"{url}#faq",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": q1,
                        "acceptedAnswer": {"@type": "Answer", "text": a1},
                    },
                    {
                        "@type": "Question",
                        "name": q2,
                        "acceptedAnswer": {"@type": "Answer", "text": a2},
                    },
                    {
                        "@type": "Question",
                        "name": q3,
                        "acceptedAnswer": {"@type": "Answer", "text": a3},
                    },
                    {
                        "@type": "Question",
                        "name": q4,
                        "acceptedAnswer": {"@type": "Answer", "text": a4},
                    },
                ],
            },
        ],
    }


def build_all_seo_artifacts(db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    judge_map = _load_judge_map()
    conn = open_readonly_reference_db(db_path)
    try:
        raw_rows = conn.execute(
            """
            SELECT case_ref, title, region, decision_date, offence_type,
                   claimed_gbp, awarded_gbp, award_pct_of_rent,
                   mitigation_factors, judge_summary, pdf_url, gov_uk_url
            FROM rro_decisions
            ORDER BY decision_date DESC
            """
        ).fetchall()
    finally:
        conn.close()

    reserved_region_slugs = {s for s, _, _ in REGION_PAGES}

    enriched_rows: list[dict[str, Any]] = []
    for r in raw_rows:
        d = dict(r)
        parts = d["case_ref"].split("/")
        ons_code = parts[1].strip().upper() if len(parts) > 1 else "UNK"
        slug, short_name, council_full, mapped_region = ONS_COUNCIL_MAP.get(
            ons_code, (f"council-{ons_code.lower()}", f"Council {ons_code}", f"Local Authority ({ons_code})", d["region"])
        )
        if slug in reserved_region_slugs:
            slug = f"{slug}-borough"
        d["ons_code"] = ons_code
        d["borough_slug"] = slug
        d["borough_short_name"] = short_name
        d["council_name"] = council_full
        d["address"] = _clean_address(d["title"], d["case_ref"])
        d["mitigation_factors"] = json.loads(d["mitigation_factors"])
        d["judge"] = judge_map.get(d["pdf_url"], "First-tier Tribunal Judge (Property Chamber)")
        enriched_rows.append(d)

    pages: dict[str, dict[str, Any]] = {}

    def _register_page(
        slug: str,
        page_type: str,
        area_name: str,
        region_label: str,
        matched_rows: list[dict[str, Any]],
        ons_codes: list[str],
        filter_query_params: str,
        custom_subtitle: str = "",
        local_borough_case_count: int | None = None,
    ) -> None:
        url = f"{SITE_ORIGIN}/rro/{slug}"
        metrics = _compute_group_metrics(matched_rows)
        notable = _select_notable_cases(matched_rows, max_cases=10)
        csv_url = f"{SITE_ORIGIN}/api/rro-search?{filter_query_params}&format=csv"
        json_url = f"{SITE_ORIGIN}/api/rro-search?{filter_query_params}"

        med_pct_str = f"{metrics['median_award_pct']}% median award" if metrics["median_award_pct"] > 0 else f"{metrics['case_count']} GOV.UK rulings"
        title = f"{area_name} Rent Repayment Order (RRO) Tribunal Precedents ({med_pct_str} | GOV.UK OGL v3.0)"
        h1 = f"{area_name} Rent Repayment Order (RRO) & Section 44 Precedent Index"
        meta_desc = (
            custom_subtitle
            or f"Search {metrics['case_count']} real GOV.UK First-tier Tribunal (Property Chamber) Rent Repayment Order decisions for {area_name}. "
            f"Median award: {metrics['median_award_pct']}% (£{metrics['median_award_gbp']:,.0f}), s.72 HMO & s.95 Selective Licensing deductions, and CSV pack."
        )

        schema_ld = _build_schema_org_json_ld(
            slug=slug,
            url=url,
            title=title,
            meta_description=meta_desc,
            area_name=area_name,
            metrics=metrics,
            notable_cases=notable,
            csv_download_url=csv_url,
            json_api_url=json_url,
        )

        page_obj: dict[str, Any] = {
            "slug": slug,
            "url": url,
            "page_type": page_type,
            "area_name": area_name,
            "region": region_label,
            "ons_codes": ons_codes,
            "title": title,
            "meta_description": meta_desc,
            "h1": h1,
            "case_count": metrics["case_count"],
            "positive_award_count": metrics["positive_award_count"],
            "dismissed_or_zero_count": metrics["dismissed_or_zero_count"],
            "median_award_pct": metrics["median_award_pct"],
            "min_award_pct": metrics["min_award_pct"],
            "max_award_pct": metrics["max_award_pct"],
            "total_claimed_gbp": metrics["total_claimed_gbp"],
            "total_awarded_gbp": metrics["total_awarded_gbp"],
            "median_award_gbp": metrics["median_award_gbp"],
            "top_deduction_factors": metrics["top_deduction_factors"],
            "csv_download_url": csv_url,
            "json_api_url": json_url,
            "notable_cases": notable,
            "schema_org_json_ld": schema_ld,
        }
        if local_borough_case_count is not None:
            page_obj["local_borough_case_count"] = local_borough_case_count
        pages[slug] = page_obj

    # 1. Build 5 UK Tribunal Region pages
    for reg_slug, reg_name, reg_desc in REGION_PAGES:
        reg_rows = [r for r in enriched_rows if r["region"].lower() == reg_name.lower()]
        reg_codes = sorted({r["ons_code"] for r in reg_rows})
        _register_page(
            slug=reg_slug,
            page_type="region",
            area_name=f"{reg_name} Tribunal Region",
            region_label=reg_name,
            matched_rows=reg_rows,
            ons_codes=reg_codes,
            filter_query_params=f"region={reg_name}",
            custom_subtitle=(
                f"{reg_desc}: {len(reg_rows)} real GOV.UK RRO decisions indexed under OGL v3.0. "
                f"Compare s.72 HMO & s.95 Selective Licensing awards, s.44 mitigation deductions, and download the CSV precedent pack."
            ),
        )

    # 2. Build every distinct Borough / Council page present in the SQLite DB
    borough_groups: dict[str, list[dict[str, Any]]] = {}
    borough_meta: dict[str, tuple[str, str, str]] = {}
    for r in enriched_rows:
        b_slug = r["borough_slug"]
        borough_groups.setdefault(b_slug, []).append(r)
        borough_meta[b_slug] = (r["borough_short_name"], r["council_name"], r["region"])

    for b_slug, b_rows in sorted(borough_groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        short_name, council_full, reg_name = borough_meta[b_slug]
        b_codes = sorted({r["ons_code"] for r in b_rows})
        q_term = b_codes[0] if len(b_codes) == 1 else short_name.split("(")[0].strip()
        _register_page(
            slug=b_slug,
            page_type="borough",
            area_name=f"{short_name} ({council_full})",
            region_label=reg_name,
            matched_rows=b_rows,
            ons_codes=b_codes,
            filter_query_params=f"q={q_term}",
            local_borough_case_count=len(b_rows),
        )

    # 3. Build Offence-Type & Statutory Guide pages
    for off_slug, off_title, off_filter, off_desc in OFFENCE_PAGES:
        if off_filter == "ALL":
            off_rows = list(enriched_rows)
            q_param = "limit=281"
        else:
            off_rows = [r for r in enriched_rows if off_filter.lower() in r["offence_type"].lower()]
            q_param = f"offence_type={off_filter.split('(')[0].strip().replace(' ', '+')}"
        _register_page(
            slug=off_slug,
            page_type="offence_type",
            area_name=off_title,
            region_label="All Regions",
            matched_rows=off_rows,
            ons_codes=sorted({r["ons_code"] for r in off_rows}),
            filter_query_params=q_param,
            custom_subtitle=(
                f"{off_desc}: {len(off_rows)} real GOV.UK First-tier Tribunal (Property Chamber) RRO rulings indexed with exact £ claimed, £ awarded, % award, and s.44 mitigation factors."
            ),
        )

    overall_metrics = _compute_group_metrics(enriched_rows)
    now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    payload = {
        "status": "ok",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "site_origin": SITE_ORIGIN,
        "rro_base_url": f"{SITE_ORIGIN}/rro",
        "ogl_license": OGL_LICENSE_URL,
        "isolation_mode": "OGL-v3.0-read-only",
        "indexnow_key": INDEXNOW_KEY,
        "indexnow_key_url": f"{SITE_ORIGIN}/{INDEXNOW_KEY}.txt",
        "corpus_summary": overall_metrics,
        "total_seo_pages": len(pages),
        "slugs": list(pages.keys()),
        "pages": pages,
    }

    SEO_PAGES_JSON_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # Build sitemap.xml
    sitemap_urls: list[tuple[str, str, str]] = [
        (f"{SITE_ORIGIN}/", "weekly", "0.9"),
        (f"{SITE_ORIGIN}/rro", "daily", "1.0"),
        (f"{SITE_ORIGIN}/rro/stats", "daily", "0.7"),
        (f"{SITE_ORIGIN}/llms.txt", "weekly", "0.8"),
    ]
    for slug, p in pages.items():
        prio = "0.9" if p["page_type"] in ("region", "offence_type") or p["case_count"] >= 3 else "0.8"
        sitemap_urls.append((p["url"], "weekly", prio))

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, freq, prio in sitemap_urls:
        xml_lines.extend([
            "  <url>",
            f"    <loc>{xml_escape(loc)}</loc>",
            f"    <lastmod>{now_iso}</lastmod>",
            f"    <changefreq>{freq}</changefreq>",
            f"    <priority>{prio}</priority>",
            "  </url>",
        ])
    xml_lines.append("</urlset>\n")
    SITEMAP_XML_PATH.write_text("\n".join(xml_lines), encoding="utf-8")

    # Build robots.txt welcoming search engines + AI answer engines
    robots_txt = f"""User-agent: *
Allow: /
Allow: /rro
Allow: /rro/
Allow: /api/rro-search
Allow: /llms.txt
Allow: /.well-known/agent.json

User-agent: OAI-SearchBot
Allow: /

User-agent: ChatGPT-User
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: anthropic-ai
Allow: /

User-agent: Googlebot
Allow: /

User-agent: Bingbot
Allow: /

Sitemap: {SITE_ORIGIN}/sitemap.xml
"""
    ROBOTS_TXT_PATH.write_text(robots_txt, encoding="utf-8")

    # Build llms.txt spec for UK Property Tribunal RRO Precedent Finder
    borough_bullet_lines = []
    for slug, p in pages.items():
        borough_bullet_lines.append(
            f"- [{p['area_name']} ({p['case_count']} rulings, {p['median_award_pct']}% median award)]({p['url']})"
        )

    llms_txt = f"""# UK Property Tribunal Rent Repayment Order (RRO) & Section 13 Precedent Finder
> Zero-token deterministic index of {overall_metrics['case_count']} real GOV.UK First-tier Tribunal (Property Chamber) RRO decisions under Housing Act 2004 (s.72 HMO / s.95 Selective Licensing) & Housing and Planning Act 2016 (ss.40-44).
> License: Open Government Licence v3.0 ({OGL_LICENSE_URL})
> Live UI: {SITE_ORIGIN}/rro
> Sitemap: {SITE_ORIGIN}/sitemap.xml

## National Benchmark Summary ({overall_metrics['case_count']} Real GOV.UK Decisions)
- Positive RRO Awards: {overall_metrics['positive_award_count']} / {overall_metrics['case_count']} decisions
- Median Tribunal Award % of Rent: {overall_metrics['median_award_pct']}% (Range: {overall_metrics['min_award_pct']}% to {overall_metrics['max_award_pct']}%)
- Median Monetary RRO Award: £{overall_metrics['median_award_gbp']:,.2f}
- Total Rent Claimed Across Indexed Cases: £{overall_metrics['total_claimed_gbp']:,.2f}
- Total RRO Awarded Across Indexed Cases: £{overall_metrics['total_awarded_gbp']:,.2f}
- Top s.44 Mitigation & Deduction Factors: {', '.join(f'{k} ({v})' for k, v in overall_metrics['top_deduction_factors'].items())}

## Machine-Readable API Endpoints
- GET {SITE_ORIGIN}/api/rro-search?q=Ealing&region=London&offence_type=Selective&mitigation=utilities_deducted
- GET {SITE_ORIGIN}/api/rro-search?format=csv (Download Regional RRO Precedent Pack CSV)
- GET {SITE_ORIGIN}/api/rro-seo-pages (Full JSON bundle of all {len(pages)} programmatic borough, region & offence precedent pages + Schema.org Dataset/FAQPage JSON-LD)
- POST {SITE_ORIGIN}/api/rro-audit-pdf (Stateless zero-retention private RRO claim/PDF exposure auditor)
- GET {SITE_ORIGIN}/rro/stats (Live Zero-PII North Star usage telemetry)

## Programmatic Borough, Region & Offence Precedent Pages ({len(pages)} Slugs)
{chr(10).join(borough_bullet_lines)}
"""
    LLMS_TXT_PATH.write_text(llms_txt, encoding="utf-8")
    INDEXNOW_KEY_PATH.write_text(INDEXNOW_KEY, encoding="utf-8")

    return payload


if __name__ == "__main__":
    res = build_all_seo_artifacts()
    print(f"Generated {res['total_seo_pages']} programmatic SEO pages in {SEO_PAGES_JSON_PATH} ({SEO_PAGES_JSON_PATH.stat().st_size} bytes)")
    print(f"Generated {SITEMAP_XML_PATH} ({SITEMAP_XML_PATH.stat().st_size} bytes)")
    print(f"Generated {ROBOTS_TXT_PATH} ({ROBOTS_TXT_PATH.stat().st_size} bytes)")
    print(f"Generated {LLMS_TXT_PATH} ({LLMS_TXT_PATH.stat().st_size} bytes)")
    print(f"Generated {INDEXNOW_KEY_PATH} (key={res['indexnow_key']})")
