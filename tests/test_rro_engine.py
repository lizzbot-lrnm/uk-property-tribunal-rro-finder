"""
Automated test suite for UK Property Tribunal Rent Repayment Order (RRO) Precedent Engine.
Verifies:
  1. Real GOV.UK RRO extraction accuracy (`LON/00AJ/HMG/2025/0666` and >=50 real GOV.UK rulings in DB).
  2. Strict read-only (`?mode=ro`) isolation of the public OGL v3.0 reference index.
  3. Stateless per-request isolation for any private user query or uploaded PDF (`audit_private_pdf_bytes`),
     wiped deterministically in `finally:` with zero cross-tenant leakage.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rro_engine import (
    DEFAULT_CSV_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_JSON_PATH,
    audit_private_pdf_bytes,
    open_readonly_reference_db,
    parse_rro_decision,
    search_rro_precedents,
)


def test_real_gov_uk_rro_index_populated_and_accurate() -> None:
    """Verify at least 50-80 real GOV.UK RRO rulings are indexed with structured fields."""
    assert DEFAULT_DB_PATH.exists(), "SQLite FTS5 reference database must exist"
    assert DEFAULT_JSON_PATH.exists(), "JSON precedent dataset bundle must exist"
    assert DEFAULT_CSV_PATH.exists(), "CSV regional precedent pack must exist"

    all_res = search_rro_precedents(limit=100)
    assert all_res["isolation_mode"] == "OGL-v3.0-read-only"
    assert all_res["stats"]["total_matched"] >= 50
    assert all_res["stats"]["positive_award_count"] >= 45
    assert 35.0 <= all_res["stats"]["median_award_pct"] <= 85.0

    # Verify benchmark real ruling LON/00AJ/HMG/2025/0666 (Flat 9 Oxford Court, Ealing)
    ealing_res = search_rro_precedents(q="LON/00AJ/HMG/2025/0666")
    assert len(ealing_res["results"]) >= 1
    case = ealing_res["results"][0]
    assert case["case_ref"] == "LON/00AJ/HMG/2025/0666"
    assert case["region"] == "London"
    assert case["offence_type"] == "Selective Licensing (s.95)"
    assert case["claimed_gbp"] == 21000.0
    assert case["awarded_gbp"] == 8400.0
    assert case["award_pct_of_rent"] == 40.0
    assert "utilities_deducted" in case["mitigation_factors"]
    assert "assets.publishing.service.gov.uk" in case["pdf_url"]


def test_regional_and_mitigation_filtering() -> None:
    """Verify FTS5 + structured filtering by region, offence_type, mitigation, and max_pct."""
    london_res = search_rro_precedents(region="London", limit=100)
    assert london_res["stats"]["total_matched"] >= 30
    assert all(r["region"] == "London" for r in london_res["results"])

    midlands_res = search_rro_precedents(region="Midlands", limit=50)
    assert midlands_res["stats"]["total_matched"] >= 3
    assert all(r["region"] == "Midlands" for r in midlands_res["results"])

    mit_res = search_rro_precedents(mitigation="utilities_deducted", max_pct=65.0, limit=50)
    assert mit_res["stats"]["total_matched"] >= 10
    for r in mit_res["results"]:
        assert "utilities_deducted" in r["mitigation_factors"]
        assert r["award_pct_of_rent"] is not None and r["award_pct_of_rent"] <= 65.0


def test_ogl_reference_db_strict_readonly_isolation() -> None:
    """
    Verify that the public OGL v3.0 reference connection is opened with `?mode=ro`
    and any write/insert/drop attempt raises `sqlite3.OperationalError: attempt to write a readonly database`.
    """
    conn = open_readonly_reference_db(DEFAULT_DB_PATH)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute(
                "INSERT INTO rro_decisions VALUES ('FAKE/1', 't', 'London', '2026', 'HMO', 1, 1, 100, '[]', 's', 'u', 'u', '[]', 'OGL')"
            )
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM rro_decisions")
    finally:
        conn.close()


def test_stateless_ephemeral_private_pdf_audit_zero_leakage() -> None:
    """
    Verify that private user queries and uploaded PDFs are processed in an isolated
    ephemeral workspace that is deterministically wiped in `finally:`, leaving zero
    residual files on disk and zero rows written to the public OGL reference index.
    """
    conn = open_readonly_reference_db(DEFAULT_DB_PATH)
    before_count = conn.execute("SELECT COUNT(*) FROM rro_decisions").fetchone()[0]
    conn.close()

    secret_marker = "PRIVATE_TENANT_CONFIDENTIAL_REF_998877"
    sample_claim = (
        f"Case reference: LON/00AJ/HMG/2026/9999 ({secret_marker}). "
        "Application for a rent repayment order under section 72(1) unlicensed HMO in Ealing, London. "
        "The amount claimed is £18,000.00 for 12 months rent inclusive of utilities and council tax. "
        "The landlord had no previous convictions and relied upon a managing agent."
    )

    audit_res = audit_private_pdf_bytes(
        payload_bytes=sample_claim.encode("utf-8"),
        region_hint="London",
        claimed_gbp_hint=18000.0,
    )

    assert audit_res["isolation_mode"] == "stateless-ephemeral-finally-wiped"
    assert audit_res["public_db_mode"] == "OGL-v3.0-read-only"
    assert audit_res["ephemeral_wiped"] is True

    # Confirm the ephemeral directory was wiped in `finally:`
    ephemeral_dir = Path(audit_res["ephemeral_dir_ tracked"])
    assert not ephemeral_dir.exists(), "Ephemeral workspace must be deleted in finally block"

    # Confirm zero leakage into the public OGL reference database
    conn = open_readonly_reference_db(DEFAULT_DB_PATH)
    after_count = conn.execute("SELECT COUNT(*) FROM rro_decisions").fetchone()[0]
    leak_check = conn.execute(
        "SELECT COUNT(*) FROM rro_decisions WHERE title LIKE ? OR judge_summary LIKE ?",
        (f"%{secret_marker}%", f"%{secret_marker}%"),
    ).fetchone()[0]
    conn.close()

    assert after_count == before_count
    assert leak_check == 0

    # Confirm structured audit output has mitigation factors and comparable OGL precedents
    summary = audit_res["private_claim_summary"]
    assert summary["detected_region"] == "London"
    assert summary["claimed_gbp_evaluated"] == 18000.0
    assert "utilities_deducted" in summary["detected_mitigation_factors"]
    assert len(audit_res["comparable_ogl_precedents"]) >= 3


def test_ocr_ligature_parser_unit() -> None:
    """Verify parser handles old-style PDF font ligatures ('£8,4oo', '4o%') cleanly."""
    sample_text = (
        "FIRST-TIER TRIBUNAL PROPERTY CHAMBER Case Reference: LON/00AJ/HMG/2025/0666 "
        "The Tribunal makes a Rent repayment order in the sum of £8,4oo (being 4o% of the rent paid). "
        "The Applicants seek a rent repayment order in the sum of £21,ooo.oo under section 95(1) Housing Act 2004."
    )
    parsed = parse_rro_decision(sample_text, title="Flat 9 Oxford Court: LON/00AJ/HMG/2025/0666")
    assert parsed["case_ref"] == "LON/00AJ/HMG/2025/0666"
    assert parsed["claimed_gbp"] == 21000.0
    assert parsed["awarded_gbp"] == 8400.0
    assert parsed["award_pct_of_rent"] == 40.0
    assert parsed["offence_type"] == "Selective Licensing (s.95)"
