from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
from pathlib import Path

from build_seo_pages import (
    INDEXNOW_KEY_PATH,
    LLMS_TXT_PATH,
    ROBOTS_TXT_PATH,
    SEO_PAGES_JSON_PATH,
    SITEMAP_XML_PATH,
    build_all_seo_artifacts,
)
from seo_router import get_indexnow_key, get_robots_txt, get_seo_page, get_sitemap_xml, render_seo_page_html


def test_build_seo_pages_contains_all_required_boroughs_regions_and_schema() -> None:
    payload = build_all_seo_artifacts()
    assert payload["status"] == "ok"
    assert payload["isolation_mode"] == "OGL-v3.0-read-only"
    assert payload["total_seo_pages"] >= 50
    assert SEO_PAGES_JSON_PATH.exists()
    assert SITEMAP_XML_PATH.exists()
    assert ROBOTS_TXT_PATH.exists()
    assert LLMS_TXT_PATH.exists()
    assert INDEXNOW_KEY_PATH.exists()

    required_slugs = [
        "london",
        "ealing",
        "tower-hamlets",
        "camden",
        "islington",
        "lambeth",
        "hackney",
        "southwark",
        "newham",
        "brent",
        "haringey",
        "waltham-forest",
        "bristol",
        "birmingham",
        "manchester",
        "liverpool",
        "nottingham",
        "leeds",
        "newcastle",
        "unlicensed-hmo-s72",
        "selective-licensing-s95",
        "unlawful-eviction",
    ]
    pages = payload["pages"]
    for slug in required_slugs:
        assert slug in pages, f"Missing required SEO slug: {slug}"
        p = pages[slug]
        assert p["url"] == f"https://parish.technoplusit.co.uk/rro/{slug}"
        assert p["case_count"] >= 1
        assert isinstance(p["top_deduction_factors"], dict)
        assert len(p["notable_cases"]) >= 1
        nc0 = p["notable_cases"][0]
        for k in ("case_ref", "address", "offence", "claimed_gbp", "awarded_gbp", "award_pct", "judge", "decision_date", "gov_uk_pdf_url", "snippet"):
            assert k in nc0
        graph = p["schema_org_json_ld"]["@graph"]
        types = {node["@type"] for node in graph}
        assert "Dataset" in types
        assert "FAQPage" in types
        dataset_node = next(node for node in graph if node["@type"] == "Dataset")
        assert dataset_node["license"] == "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"


def test_seo_router_renders_valid_html_and_discovery_files() -> None:
    html_out = render_seo_page_html("tower-hamlets")
    assert html_out is not None
    assert "application/ld+json" in html_out
    assert "Tower Hamlets" in html_out
    assert "Open Government Licence v3.0" in html_out

    sitemap = get_sitemap_xml()
    assert "https://parish.technoplusit.co.uk/rro/tower-hamlets" in sitemap
    assert "https://parish.technoplusit.co.uk/rro/ealing" in sitemap

    robots = get_robots_txt()
    assert "Sitemap: https://parish.technoplusit.co.uk/sitemap.xml" in robots
    assert "PerplexityBot" in robots

    key = get_indexnow_key()
    assert len(key) == 32
