# UK Property Tribunal Rent Repayment Order (`RRO`) & Section 13 Precedent Finder

Zero-token deterministic ingestion, extraction, SQLite FTS5 + local CPU vector similarity engine, and stateless private RRO claim auditor for official **GOV.UK First-tier Tribunal (Property Chamber — Residential Property)** Rent Repayment Order decisions (`Housing Act 2004 s.72 / s.95` & `Housing and Planning Act 2016 s.40–44`).

- **Live Web UI:** [`https://parish.technoplusit.co.uk/rro`](https://parish.technoplusit.co.uk/rro)
- **Live JSON Search API:** [`https://parish.technoplusit.co.uk/api/rro-search?q=Ealing`](https://parish.technoplusit.co.uk/api/rro-search?q=Ealing)
- **Live Ephemeral Claim/PDF Audit API:** `POST https://parish.technoplusit.co.uk/api/rro-audit-pdf`
- **Live North Star Usage & Privacy Telemetry API:** [`https://parish.technoplusit.co.uk/rro/stats`](https://parish.technoplusit.co.uk/rro/stats) & [`https://parish.technoplusit.co.uk/api/rro/stats`](https://parish.technoplusit.co.uk/api/rro/stats)
- **Data License:** Open Government Licence v3.0 (`OGL v3.0`) — Crown Copyright GOV.UK Residential Property Tribunal Decisions.

## Architecture & Security Isolation

1. **Zero-Token GOV.UK Ingestion (`rro_engine.py`):**
   - Queries the official GOV.UK Search & Content APIs (`filter_format=residential_property_tribunal_decision`, `housing-act-2004-and-housing-and-planning-act-2016---rent-repayment-orders`).
   - Downloads official tribunal PDF decisions and scans all extracted text through `/workspace/worf_quarantine.py` (`scan_payload`, `verdict: CLEAN`).
   - Extracts layout-preserved text via `/usr/bin/pdftotext -layout` (`0` LLM tokens) and normalizes PDF font ligatures (`£8,4oo` -> `£8,400`, `4o%` -> `40%`).
   - Deterministically extracts `case_ref`, `title`, `region`, `decision_date`, `offence_type`, `claimed_gbp`, `awarded_gbp`, `award_pct_of_rent`, `mitigation_factors`, `judge_summary`, and `pdf_url`.
2. **Read-Only Reference Index (`?mode=ro`):**
   - Public OGL v3.0 rulings are indexed in `data/rro_precedents.sqlite` (`SQLite FTS5` full-text index + 64-dim deterministic L2-normalized feature-hashing embeddings) and exported to `data/rro_precedents.json` and `data/rro_precedents_pack.csv`.
   - All search queries open the SQLite database via `file:...?mode=ro` URI connections, guaranteeing at the OS/SQLite level that public reference tables cannot be mutated.
3. **Stateless Ephemeral Private Claim / PDF Audit (`audit_private_pdf_bytes`):**
   - Private user claims or uploaded PDFs are processed inside an isolated `tempfile.mkdtemp(prefix="rro_private_ephemeral_")` directory and deterministically wiped in a `finally:` block (`ephemeral_wiped: true`), leaving zero residual files and zero rows in the public database.

## Running Tests

```bash
/workspace/revenue/uk-us-compliance-mcp-actor/.venv/bin/pytest -v tests/test_rro_engine.py
```
