# UK Property Tribunal Rent Repayment Order (RRO) & Section 13 Precedent Finder (`rro_engine.py`)

Zero-token deterministic ingestion, SQLite FTS5 + 64-dim vector similarity index, **Instant RRO Award & Mitigation Calculator / Case Builder (1–24 Month Renters' Rights Act 2026 Cap)**, read-only (`?mode=ro`) Open Government Licence v3.0 (`OGL v3.0`) query engine, and stateless ephemeral (`finally: wiped`) private PDF/claim auditor for **281 real GOV.UK First-tier Tribunal (Property Chamber — Residential Property)** Rent Repayment Order decisions.

- **Live Web UI & Interactive Calculator:** [`https://parish.technoplusit.co.uk/rro`](https://parish.technoplusit.co.uk/rro)
- **Live Precedent Search API (JSON & CSV):** [`https://parish.technoplusit.co.uk/api/rro-search`](https://parish.technoplusit.co.uk/api/rro-search) | [`https://parish.technoplusit.co.uk/api/rro-search?format=csv`](https://parish.technoplusit.co.uk/api/rro-search?format=csv)
- **Live RRO Award & Schedule Calculator API (JSON, Markdown & CSV):** [`https://parish.technoplusit.co.uk/api/rro-calculate`](https://parish.technoplusit.co.uk/api/rro-calculate)
- **Live Ephemeral Claim/PDF Audit API:** `POST https://parish.technoplusit.co.uk/api/rro-audit-pdf`
- **Live North Star Usage & Privacy Telemetry API:** [`https://parish.technoplusit.co.uk/rro/stats`](https://parish.technoplusit.co.uk/rro/stats) & [`https://parish.technoplusit.co.uk/api/rro/stats`](https://parish.technoplusit.co.uk/api/rro/stats)
- **Apify Store Actor:** [`https://apify.com/technoplusit/uk-property-tribunal-rro-finder`](https://apify.com/technoplusit/uk-property-tribunal-rro-finder)

---

## 1. Corpus Summary (281 Real GOV.UK Tribunal Decisions)

All **281 decisions** are fetched directly from `https://www.gov.uk/api/search.json?filter_format=residential_property_tribunal_decision&filter_tribunal_decision_sub_category=housing-act-2004-and-housing-and-planning-act-2016---rent-repayment-orders`, scanned via Worf Quarantine (`scan_payload` -> `CLEAN`), and parsed deterministically via `/usr/bin/pdftotext -layout` with **0 LLM tokens**:

- **Total Indexed Decisions:** `281` across all 5 UK Tribunal Regions:
  - **London (`LON`):** `151` decisions
  - **Northern (`MAN`):** `47` decisions
  - **Southern (`CHI` / `HAV`):** `34` decisions
  - **Eastern (`CAM`):** `32` decisions
  - **Midlands (`BIR`):** `17` decisions
- **Decisions with Extracted Financial / Dismissal Outcome:** `221` (`156` positive RRO awards, `65` dismissed/struck out/withdrawn)
- **Empirical Median Tribunal Award % of Rent:** `60.0%` (Mean `60.6%`)
- **Total Rent Claimed Across Indexed Rulings:** `£1,665,078.12`
- **Total RRO Awarded Across Indexed Rulings:** `£1,011,905.38`
- **Benchmark Verification (`LON/00AJ/HMG/2025/0666` — Flat 9 Oxford Court, Ealing):**
  - Offence: `Selective Licensing (s.95)`
  - Claimed: `£21,000.00` | Awarded: `£8,400.00` (`40.0%` of rent)

---

## 2. Instant RRO Award & Mitigation Calculator / Case Builder (`calculate_rro_award_and_schedule`)

Supports both **Landlord Section 44 Defence** and **Tenant RRO Claim** schedules under Housing Act 2004 (ss.72/95), Housing and Planning Act 2016 (ss.40–44), *Acheampong v Roman* [2022] UKUT 239 (LC), and the **Renters' Rights Act 2026 (1-to-24-month cap)**:

1. Deducts Universal Credit housing element (`s.44(3)`) and landlord-paid utilities/services (*Acheampong* / *Vadamalayan*) from gross rent to establish **Net Eligible Rent**.
2. Queries the read-only (`?mode=ro`) 281-decision SQLite FTS5 corpus for the selected UK region and offence category.
3. Applies deterministic Section 44 mitigation/aggravation adjustments (`utilities_deducted`, `good_condition`, `first_offence`, `letting_agent_reliance`, `financial_hardship`, `delayed_council_application`, `tenant_conduct`, `professional_landlord_aggravation`, `director_liability`).
4. Outputs a ready-to-file **Scott Schedule / Skeleton Argument** in **Markdown** and **CSV** citing the 5 closest real GOV.UK Tribunal precedents with verbatim judicial reasoning and official PDF links.

---

## 3. Architecture & Strict Data-Boundary Isolation

1. **Public Reference Index (`OGL v3.0` Read-Only):**
   - Stored in `data/rro_precedents.sqlite` (`SQLite FTS5` + 64-dim L2-normalized feature-hashing embeddings).
   - Every search, calculation, and audit opens `data/rro_precedents.sqlite` via `open_readonly_reference_db()` using `file:...?mode=ro`. Any write attempt raises `sqlite3.OperationalError: attempt to write a readonly database`.
2. **Stateless Per-Request Ephemeral Private Claim/PDF Audit:**
   - `audit_private_pdf_bytes()` processes private user PDFs or claim text inside an isolated `tempfile.mkdtemp(prefix="rro_private_ephemeral_")` directory and deterministically wipes it in a `finally:` block (`shutil.rmtree(ephemeral_dir, ignore_errors=True)`).
3. **Privacy-Safe Aggregate Usage Telemetry (`Zero PII`):**
   - `record_rro_usage_event()` and `get_rro_usage_stats()` track only aggregate daily counts (`searches`, `pack_downloads`, `private_audits`) with zero IP addresses, zero search queries, and zero uploaded PDFs stored.
