#!/usr/bin/env python3
"""
Deterministic IndexNow Instant Indexing Verifier & Submitter for parish.technoplusit.co.uk.
Pushes all 93 URLs (root, /rro, /rro/stats, /llms.txt, /sitemap.xml, and all 88 programmatic /rro/<slug> pages)
to https://api.indexnow.org/indexnow (shared across Bing, DuckDuckGo, Yandex, Seznam, Naver).
Passes all external HTTP responses through /workspace/worf_quarantine.py.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, "/workspace")
from worf_quarantine import scan_payload

BASE_DIR = Path(__file__).resolve().parent
SEO_PAGES_JSON_PATH = BASE_DIR / "seo_pages.json"
INDEXNOW_KEY_PATH = BASE_DIR / "indexnow_key.txt"
INDEXNOW_PAYLOAD_PATH = BASE_DIR / "indexnow_payload.json"
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
HOST = "parish.technoplusit.co.uk"


def build_indexnow_payload() -> dict[str, Any]:
    key = INDEXNOW_KEY_PATH.read_text(encoding="utf-8").strip()
    seo_data = json.loads(SEO_PAGES_JSON_PATH.read_text(encoding="utf-8"))
    url_list = [
        f"https://{HOST}/",
        f"https://{HOST}/rro",
        f"https://{HOST}/rro/stats",
        f"https://{HOST}/llms.txt",
        f"https://{HOST}/sitemap.xml",
    ]
    for slug, page in seo_data.get("pages", {}).items():
        url_list.append(page["url"])

    payload = {
        "host": HOST,
        "key": key,
        "keyLocation": f"https://{HOST}/{key}.txt",
        "urlList": url_list,
    }
    INDEXNOW_PAYLOAD_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def check_live_edge_routes(key: str) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for path in [f"/{key}.txt", "/sitemap.xml", "/robots.txt", "/llms.txt", "/rro", "/rro/tower-hamlets"]:
        url = f"https://{HOST}{path}"
        req = urllib.request.Request(url, headers={"User-Agent": "Max-SEO-Verifier/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw_body = resp.read().decode("utf-8", errors="replace")
                worf = scan_payload(raw_body[:4000], source=url)
                checks[path] = {
                    "http_status": resp.status,
                    "content_type": resp.headers.get("Content-Type", ""),
                    "body_prefix": raw_body[:120].strip() if worf["quarantine_passed"] else "[QUARANTINED]",
                    "worf_verdict": worf["verdict"],
                }
        except urllib.error.HTTPError as e:
            checks[path] = {"http_status": e.code, "error": str(e.reason)}
        except Exception as e:
            checks[path] = {"http_status": 0, "error": str(e)}
    return checks


def submit_to_indexnow(payload: dict[str, Any]) -> dict[str, Any]:
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        INDEXNOW_ENDPOINT,
        data=data_bytes,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Max-SEO-Verifier/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_body = resp.read().decode("utf-8", errors="replace")
            worf = scan_payload(raw_body[:2000], source=INDEXNOW_ENDPOINT)
            return {
                "http_status": resp.status,
                "response": raw_body[:300] if worf["quarantine_passed"] else "[QUARANTINED]",
                "worf_verdict": worf["verdict"],
                "submitted_url_count": len(payload["urlList"]),
            }
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        worf = scan_payload(err_body[:2000], source=INDEXNOW_ENDPOINT)
        return {
            "http_status": e.code,
            "error": str(e.reason),
            "response": err_body[:300] if worf["quarantine_passed"] else "[QUARANTINED]",
            "worf_verdict": worf["verdict"],
            "submitted_url_count": len(payload["urlList"]),
        }
    except Exception as e:
        return {"http_status": 0, "error": str(e)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit", action="store_true", help="Force POST to api.indexnow.org/indexnow")
    args = parser.parse_args()

    payload = build_indexnow_payload()
    edge_status = check_live_edge_routes(payload["key"])
    key_path = f"/{payload['key']}.txt"
    key_live = (
        edge_status.get(key_path, {}).get("http_status") == 200
        and edge_status.get(key_path, {}).get("body_prefix") == payload["key"]
    )

    result: dict[str, Any] = {
        "indexnow_key": payload["key"],
        "key_location": payload["keyLocation"],
        "url_count": len(payload["urlList"]),
        "payload_file": str(INDEXNOW_PAYLOAD_PATH),
        "live_edge_status": edge_status,
        "key_live_on_edge": key_live,
    }
    if key_live or args.submit:
        result["indexnow_submission"] = submit_to_indexnow(payload)
    else:
        result["indexnow_submission"] = {
            "status": "staged_awaiting_edge_key_route",
            "note": f"Key file {key_path} currently returns status {edge_status.get(key_path, {}).get('http_status')} on edge. Run with --submit once worker.js serves {key_path}.",
        }
    print(json.dumps(result, indent=2))
