#!/usr/bin/env python3
"""
Standalone Modular SEO & AI-Agent Discovery Router for UK Property Tribunal RRO Finder.
Serves:
  - /rro/<slug> (HTML with Schema.org Dataset + FAQPage JSON-LD, or JSON when ?format=json)
  - /sitemap.xml
  - /robots.txt
  - /llms.txt
  - /<indexnow_key>.txt
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from build_seo_pages import (
    INDEXNOW_KEY_PATH,
    LLMS_TXT_PATH,
    ROBOTS_TXT_PATH,
    SEO_PAGES_JSON_PATH,
    SITEMAP_XML_PATH,
    build_all_seo_artifacts,
)


def load_seo_bundle(seo_json_path: Path = SEO_PAGES_JSON_PATH) -> dict[str, Any]:
    if not seo_json_path.exists():
        return build_all_seo_artifacts()
    return json.loads(seo_json_path.read_text(encoding="utf-8"))


def get_seo_page(slug: str, seo_json_path: Path = SEO_PAGES_JSON_PATH) -> dict[str, Any] | None:
    clean_slug = (slug or "").strip().lower().strip("/")
    if clean_slug.startswith("rro/"):
        clean_slug = clean_slug[4:].strip("/")
    bundle = load_seo_bundle(seo_json_path)
    return bundle.get("pages", {}).get(clean_slug)


def render_seo_page_html(slug: str, seo_json_path: Path = SEO_PAGES_JSON_PATH) -> str | None:
    page = get_seo_page(slug, seo_json_path)
    if not page:
        return None

    title = html.escape(page["title"])
    meta_desc = html.escape(page["meta_description"])
    h1 = html.escape(page["h1"])
    url = html.escape(page["url"])
    csv_url = html.escape(page["csv_download_url"])
    json_url = html.escape(page["json_api_url"])
    json_ld_str = json.dumps(page["schema_org_json_ld"], ensure_ascii=False)

    ded_badges = []
    for factor, count in page.get("top_deduction_factors", {}).items():
        ded_badges.append(
            f'<span style="display:inline-block;background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;padding:4px 10px;border-radius:999px;font-size:0.82rem;margin:3px;">'
            f'{html.escape(factor)}: <strong>{count}</strong></span>'
        )

    case_rows = []
    for c in page.get("notable_cases", []):
        c_gbp = f"£{c['claimed_gbp']:,.2f}" if c.get("claimed_gbp") is not None else "—"
        a_gbp = f"£{c['awarded_gbp']:,.2f}" if c.get("awarded_gbp") is not None else "—"
        pct = f"{c['award_pct']}%" if c.get("award_pct") is not None else "—"
        case_rows.append(
            f"<tr>"
            f"<td><strong>{html.escape(str(c['case_ref']))}</strong><br><small>{html.escape(str(c['decision_date']))}</small></td>"
            f"<td>{html.escape(str(c['address']))}<br><small style='color:#475569;'>{html.escape(str(c['judge']))}</small></td>"
            f"<td>{html.escape(str(c['offence']))}</td>"
            f"<td>{c_gbp}</td>"
            f"<td><strong>{a_gbp}</strong> ({pct})</td>"
            f"<td><small>{html.escape(str(c['snippet'])[:220])}</small></td>"
            f"<td><a href='{html.escape(str(c['gov_uk_pdf_url']))}' target='_blank' rel='noopener'>GOV.UK PDF</a></td>"
            f"</tr>"
        )

    faq_blocks = []
    for graph_node in page["schema_org_json_ld"].get("@graph", []):
        if graph_node.get("@type") == "FAQPage":
            for q_item in graph_node.get("mainEntity", []):
                q_text = html.escape(q_item.get("name", ""))
                a_text = html.escape(q_item.get("acceptedAnswer", {}).get("text", ""))
                faq_blocks.append(
                    f"<div style='margin-bottom:14px;padding:12px;background:#f8fafc;border-left:4px solid #0284c7;border-radius:6px;'>"
                    f"<h3 style='margin:0 0 6px 0;font-size:1rem;'>{q_text}</h3>"
                    f"<p style='margin:0;color:#334155;font-size:0.92rem;'>{a_text}</p></div>"
                )

    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <meta name="description" content="{meta_desc}" />
  <link rel="canonical" href="{url}" />
  <script type="application/ld+json">{json_ld_str}</script>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; color: #0f172a; background: #f8fafc; margin: 0; padding: 24px; line-height: 1.5; }}
    .wrap {{ max-width: 1120px; margin: 0 auto; background: #fff; padding: 28px; border-radius: 12px; border: 1px solid #e2e8f0; }}
    .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 18px 0; }}
    .kpi {{ background: #f1f5f9; padding: 14px; border-radius: 8px; }}
    .kpi .v {{ font-size: 1.45rem; font-weight: 800; color: #0369a1; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 0.9rem; }}
    th, td {{ border-bottom: 1px solid #e2e8f0; padding: 10px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f8fafc; font-weight: 700; }}
    .btn {{ display: inline-block; padding: 10px 16px; border-radius: 8px; text-decoration: none; font-weight: 700; margin-right: 10px; }}
    .btn-primary {{ background: #0284c7; color: #fff; }}
    .btn-secondary {{ background: #e2e8f0; color: #0f172a; }}
  </style>
</head>
<body>
  <div class="wrap">
    <p><a href="/rro">&larr; Back to National UK Property Tribunal RRO Search &amp; Calculator</a></p>
    <h1>{h1}</h1>
    <p>{meta_desc}</p>
    <div style="margin: 16px 0;">
      <a class="btn btn-primary" href="{csv_url}">Download {html.escape(page['area_name'])} Precedent Pack (CSV)</a>
      <a class="btn btn-secondary" href="{json_url}">Query JSON API</a>
      <a class="btn btn-secondary" href="/rro">Interactive Section 44 Calculator</a>
    </div>
    <div class="kpi-grid">
      <div class="kpi"><div>Indexed GOV.UK Rulings</div><div class="v">{page['case_count']}</div></div>
      <div class="kpi"><div>Positive RRO Awards</div><div class="v">{page['positive_award_count']}</div></div>
      <div class="kpi"><div>Median Tribunal Award %</div><div class="v">{page['median_award_pct']}%</div></div>
      <div class="kpi"><div>Award % Range</div><div class="v">{page['min_award_pct']}% – {page['max_award_pct']}%</div></div>
      <div class="kpi"><div>Median Award (£)</div><div class="v">£{page['median_award_gbp']:,.2f}</div></div>
      <div class="kpi"><div>Total RROs Awarded (£)</div><div class="v">£{page['total_awarded_gbp']:,.2f}</div></div>
    </div>
    <h2>Section 44 Statutory Deduction &amp; Mitigation Factors Cited</h2>
    <div>{"".join(ded_badges)}</div>
    <h2>Notable GOV.UK First-tier Tribunal Decisions ({html.escape(page['area_name'])})</h2>
    <table>
      <thead>
        <tr><th>Case Ref</th><th>Property &amp; Judge</th><th>Offence</th><th>Claimed</th><th>Awarded</th><th>Judicial Extract</th><th>Source</th></tr>
      </thead>
      <tbody>
        {"".join(case_rows)}
      </tbody>
    </table>
    <h2 style="margin-top:28px;">Frequently Asked Questions ({html.escape(page['area_name'])})</h2>
    {"".join(faq_blocks)}
    <p style="margin-top:24px;font-size:0.82rem;color:#64748b;">
      Licensed under the <a href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/">Open Government Licence v3.0 (OGL v3.0)</a>.
      Contains public sector information from GOV.UK Residential Property Tribunal Decisions.
    </p>
  </div>
</body>
</html>"""


def get_sitemap_xml(sitemap_path: Path = SITEMAP_XML_PATH) -> str:
    if not sitemap_path.exists():
        build_all_seo_artifacts()
    return sitemap_path.read_text(encoding="utf-8")


def get_robots_txt(robots_path: Path = ROBOTS_TXT_PATH) -> str:
    if not robots_path.exists():
        build_all_seo_artifacts()
    return robots_path.read_text(encoding="utf-8")


def get_llms_txt(llms_path: Path = LLMS_TXT_PATH) -> str:
    if not llms_path.exists():
        build_all_seo_artifacts()
    return llms_path.read_text(encoding="utf-8")


def get_indexnow_key(key_path: Path = INDEXNOW_KEY_PATH) -> str:
    if not key_path.exists():
        build_all_seo_artifacts()
    return key_path.read_text(encoding="utf-8").strip()
