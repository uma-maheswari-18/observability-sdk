#!/usr/bin/env python3
"""
Observability Stack Setup Script
=================================
Run this ONCE after `docker-compose up -d` to:
    1. Wait for OpenSearch + Dashboards to be ready
    2. Find or create the Observability workspace
    3. Create the otel-v1-apm-span-* index pattern inside that workspace
    4. Fix the status.code mapping (keyword instead of integer)
    5. Save OPENSEARCH_WORKSPACE_ID to your .env file
    6. Print the clean dashboard URL

Usage:
    python scripts/setup_observability.py
"""

import os
import sys
import time
import requests
from pathlib import Path
from dotenv import load_dotenv, set_key

load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────────
OPENSEARCH_URL = os.getenv("OPENSEARCH_URL",             "http://localhost:9200")
DASHBOARDS_URL = os.getenv("OPENSEARCH_DASHBOARDS_URL",  "http://localhost:5601").rstrip("/")
OS_USER        = os.getenv("OPENSEARCH_USER", "admin")
OS_PASS        = os.getenv("OPENSEARCH_PASS") or os.getenv("OPENSEARCH_PASSWORD", "admin")
ENV_FILE       = Path(__file__).resolve().parent.parent / ".env"

HEADERS = {
    "osd-xsrf":     "true",
    "Content-Type": "application/json",
}


def log(msg):   print(f"   {msg}")
def ok(msg):    print(f"   ✅ {msg}")
def warn(msg):  print(f"   ⚠️  {msg}")
def err(msg):   print(f"   ❌ {msg}"); sys.exit(1)


# ── 1. Wait for services ─────────────────────────────────────────────────────

def wait_for(url: str, label: str, timeout: int = 120):
    print(f"\n⏳ Waiting for {label} ...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=5).status_code < 500:
                ok(f"{label} ready")
                return
        except Exception:
            pass
        time.sleep(3)
    err(f"{label} did not respond within {timeout}s — is Docker running?")


# ── 2. Fix index template ─────────────────────────────────────────────────────

def fix_index_template():
    print("\n🔧 Patching otel-v1-apm-span index template ...")
    r = requests.put(
        f"{OPENSEARCH_URL}/_index_template/otel-v1-apm-span-index-template",
        auth=(OS_USER, OS_PASS),
        json={
            "index_patterns": ["otel-v1-apm-span-*"],
            "template": {
                "mappings": {
                    "dynamic": True,
                    "properties": {
                        "status.code":     {"type": "keyword"},
                        "traceId":         {"type": "keyword"},
                        "spanId":          {"type": "keyword"},
                        "parentSpanId":    {"type": "keyword"},
                        "name":            {"type": "keyword"},
                        "kind":            {"type": "keyword"},
                        "startTime":       {"type": "date_nanos"},
                        "endTime":         {"type": "date_nanos"},
                        "durationInNanos": {"type": "long"},
                        "serviceName":     {"type": "keyword"},
                        "traceGroup":      {"type": "keyword"},
                        "traceGroupFields.statusCode": {"type": "keyword"},
                    }
                }
            }
        }
    )
    ok("Template patched") if r.ok else warn(f"Template patch: {r.status_code} {r.text[:80]}")


# ── 3. Find or create workspace ───────────────────────────────────────────────

def get_or_create_workspace() -> str:
    print("\n🏗️  Checking for Observability workspace ...")

    # List all workspaces and find one with use-case-observability
    r = requests.post(
        f"{DASHBOARDS_URL}/api/workspaces/_list",
        headers=HEADERS,
        json={},
    )
    if not r.ok:
        err(f"Could not list workspaces: {r.status_code} {r.text[:100]}")

    workspaces = r.json().get("result", {}).get("workspaces", [])

    # Find existing observability workspace
    for ws in workspaces:
        features = ws.get("features", [])
        if "use-case-observability" in features:
            ok(f"Found existing workspace: '{ws['name']}' (id={ws['id']})")
            return ws["id"]

    # None found — create one
    log("No observability workspace found — creating one ...")
    r = requests.post(
        f"{DASHBOARDS_URL}/api/workspaces",
        headers=HEADERS,
        json={
            "attributes": {
                "name":        "Observability Workspace",
                "description": "LLM Agent Traces — powered by observability-sdk",
                "features":    ["use-case-observability"],
                "color":       "#0277BD",
            }
        },
    )
    if not r.ok:
        err(f"Failed to create workspace: {r.status_code} {r.text[:200]}")

    ws_id = r.json()["result"]["id"]
    ok(f"Workspace created (id={ws_id})")
    return ws_id


# ── 4. Create index pattern ───────────────────────────────────────────────────

def ensure_index_pattern(workspace_id: str):
    print("\n📊 Checking index pattern otel-v1-apm-span-* ...")

    # Check if already exists
    r = requests.get(
        f"{DASHBOARDS_URL}/w/{workspace_id}/api/saved_objects/_find"
        f"?type=index-pattern&search_fields=title&search=otel-v1-apm-span",
        headers=HEADERS,
    )
    if r.ok and r.json().get("total", 0) > 0:
        ok("Index pattern already exists")
        return

    # Create it
    r = requests.post(
        f"{DASHBOARDS_URL}/w/{workspace_id}/api/saved_objects/index-pattern",
        headers=HEADERS,
        json={
            "attributes": {
                "title":         "otel-v1-apm-span-*",
                "timeFieldName": "endTime",
            }
        },
    )
    if r.ok:
        ok(f"Index pattern created (id={r.json()['id']})")
    elif r.status_code == 409:
        ok("Index pattern already exists")
    else:
        warn(f"Index pattern: {r.status_code} {r.text[:100]}")


# ── 5. Save to .env ───────────────────────────────────────────────────────────

def save_to_env(workspace_id: str):
    print(f"\n💾 Saving OPENSEARCH_WORKSPACE_ID to .env ...")
    env_path = str(ENV_FILE)
    if ENV_FILE.exists():
        set_key(env_path, "OPENSEARCH_WORKSPACE_ID", workspace_id)
        set_key(env_path, "OPENSEARCH_DASHBOARDS_URL", DASHBOARDS_URL)
        ok(f"Updated {ENV_FILE.name}")
    else:
        with open(env_path, "a") as f:
            f.write(f"\nOPENSEARCH_WORKSPACE_ID={workspace_id}\n")
            f.write(f"OPENSEARCH_DASHBOARDS_URL={DASHBOARDS_URL}\n")
        ok(f"Written to {ENV_FILE}")


# ── 6. Summary ────────────────────────────────────────────────────────────────

def print_summary(workspace_id: str):
    traces_url = f"{DASHBOARDS_URL}/w/{workspace_id}/app/agentTraces"
    print("\n" + "=" * 60)
    print("  ✅  OBSERVABILITY STACK READY")
    print("=" * 60)
    print(f"\n  OpenSearch   → {OPENSEARCH_URL}")
    print(f"  Dashboards   → {DASHBOARDS_URL}")
    print(f"  Agent Traces → {traces_url}")
    print(f"\n  👉  Bookmark this URL:")
    print(f"      {traces_url}")
    print("\n" + "=" * 60)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Observability Stack Setup")
    print("=" * 60)

    wait_for(f"{OPENSEARCH_URL}/_cluster/health", "OpenSearch")
    wait_for(f"{DASHBOARDS_URL}/api/status",      "OpenSearch Dashboards")

    fix_index_template()
    workspace_id = get_or_create_workspace()
    ensure_index_pattern(workspace_id)
    save_to_env(workspace_id)
    print_summary(workspace_id)


if __name__ == "__main__":
    main()
