"""
Apify Actor entrypoint for UK Property Tribunal Rent Repayment Order (RRO)
Precedent Finder & Section 44 Award Calculator.
Runs in <1 second with 0 LLM tokens against the bundled read-only (`?mode=ro`)
SQLite FTS5 + 64-dim vector index of 281 real GOV.UK Tribunal decisions.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rro_engine import (
    audit_private_pdf_bytes,
    calculate_rro_award_and_schedule,
    get_rro_usage_stats,
    search_rro_precedents,
)


def execute_rro_actor(actor_input: dict[str, Any]) -> list[dict[str, Any]]:
    action = str(actor_input.get("action") or "calculate_and_search").strip()
    query = str(actor_input.get("query") or "").strip()
    region = str(actor_input.get("region") or "London").strip()
    offence_type = str(actor_input.get("offence_type") or "Unlicensed HMO (s.72)").strip()
    party_role = str(actor_input.get("party_role") or "landlord_defence").strip()
    monthly_rent_gbp = float(actor_input.get("monthly_rent_gbp") or 1800.0)
    months_unlicensed = int(actor_input.get("months_unlicensed") or 12)
    universal_credit_housing_gbp = float(actor_input.get("universal_credit_housing_gbp") or 0.0)
    utilities_included_monthly_gbp = float(actor_input.get("utilities_included_monthly_gbp") or 200.0)
    mitigation_factors = actor_input.get("mitigation_factors") or "utilities_deducted,first_offence,good_condition"
    limit = int(actor_input.get("limit") or 15)

    usage_stats = get_rro_usage_stats()
    corpus_size = usage_stats.get("corpus_size", 281)

    if action == "audit_private_claim":
        claim_text = str(actor_input.get("claim_text") or query or "Draft RRO claim in London for £18,000 under s.72(1).")
        audit_res = audit_private_pdf_bytes(
            claim_text=claim_text,
            region_hint=region if region != "all" else "London",
            claimed_gbp_hint=monthly_rent_gbp * months_unlicensed,
            record_usage=False,
        )
        return [{
            "status": "ok",
            "isolation_mode": audit_res["isolation_mode"],
            "corpus_size": corpus_size,
            "calculation": audit_res["private_claim_summary"],
            "comparable_precedents": audit_res["comparable_ogl_precedents"],
            "search_stats": {"total_matched": len(audit_res["comparable_ogl_precedents"])},
            "matched_precedents": audit_res["comparable_ogl_precedents"],
            "schedule_markdown": "",
        }]

    calc_res = calculate_rro_award_and_schedule(
        monthly_rent_gbp=monthly_rent_gbp,
        months_unlicensed=months_unlicensed,
        universal_credit_housing_gbp=universal_credit_housing_gbp,
        utilities_included_monthly_gbp=utilities_included_monthly_gbp,
        region=region,
        offence_type=offence_type,
        party_role=party_role,
        mitigation_factors=mitigation_factors,
        record_usage=False,
    )

    search_res = search_rro_precedents(
        q=query if action != "calculate_rro_schedule" else "",
        region=region,
        offence_type=offence_type.split("(")[0].strip() if offence_type != "all" else "",
        limit=limit,
        record_usage=False,
    )
    if search_res["stats"]["total_matched"] == 0 and query:
        search_res = search_rro_precedents(
            q="",
            region=region,
            offence_type=offence_type.split("(")[0].strip() if offence_type != "all" else "",
            limit=limit,
            record_usage=False,
        )

    return [{
        "status": "ok",
        "isolation_mode": "OGL-v3.0-read-only",
        "corpus_size": corpus_size,
        "inputs": calc_res["inputs"],
        "calculation": calc_res["calculation"],
        "comparable_precedents": calc_res["comparable_precedents"],
        "search_stats": search_res["stats"],
        "matched_precedents": search_res["results"],
        "schedule_markdown": calc_res["schedule_markdown"],
        "schedule_csv": calc_res["schedule_csv"],
    }]


async def main() -> None:
    try:
        from apify import Actor

        async with Actor:
            actor_input = await Actor.get_input() or {}
            Actor.log.info(f"Running UK Property Tribunal RRO Finder & Calculator with input: {actor_input}")
            items = execute_rro_actor(actor_input)
            for item in items:
                await Actor.push_data({k: v for k, v in item.items() if v is not None})
            await Actor.set_value("OUTPUT", items[0] if len(items) == 1 else items)
            if items and items[0].get("schedule_markdown"):
                await Actor.set_value("SCHEDULE.md", items[0]["schedule_markdown"], content_type="text/markdown")
            if items and items[0].get("schedule_csv"):
                await Actor.set_value("SCHEDULE.csv", items[0]["schedule_csv"], content_type="text/csv")
            Actor.log.info(f"Successfully pushed {len(items)} RRO precedent & schedule report(s).")
    except ImportError:
        raw_input = os.environ.get("ACTOR_INPUT", "{}")
        actor_input = json.loads(raw_input) if raw_input else {}
        items = execute_rro_actor(actor_input)
        print(json.dumps(items, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
