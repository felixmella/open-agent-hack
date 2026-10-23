"""Run a Zetaris SQL file one statement at a time over REST (Zetaris accepts one statement per request).

Usage:  .venv\\Scripts\\python scripts\\zetaris_sql.py zetaris\\01_sources_create.sql [--dry-run] [--skip-exists]

Uses ZETARIS_ADMIN_API_KEY if set (CREATE statements are admin-only), else ZETARIS_API_KEY.
Replaces the YOUR_APP_NAME YOUR_CONTACT_EMAIL placeholder with ZETARIS_USER_AGENT, which must name
a contact e-mail. Never prints secret values.
"""
import argparse
import json
import os
import sys
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()

PLACEHOLDER = "YOUR_APP_NAME YOUR_CONTACT_EMAIL"


def statements(path):
    lines = [line for line in open(path, encoding="utf-8") if not line.lstrip().startswith("--")]
    for chunk in "".join(lines).split(";\n"):
        if chunk.strip():
            yield chunk.strip().rstrip(";")


def run(sql):
    key = os.environ.get("ZETARIS_ADMIN_API_KEY") or os.environ["ZETARIS_API_KEY"]
    response = httpx.post(
        os.environ["ZETARIS_REST_URL"].rstrip("/") + "/sql-editor/sqls/run",
        headers={
            "Authorization": "Bearer " + key,
            "X-Org-ID": os.environ["ZETARIS_ORG_ID"],
            "X-Request-ID": str(uuid.uuid4()),
        },
        json={"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": 10},
        timeout=180,
    )
    return response.status_code, response.text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-exists", action="store_true", help="continue past 'already exists' errors")
    args = parser.parse_args()

    for number, sql in enumerate(statements(args.file), 1):
        if PLACEHOLDER in sql:
            user_agent = os.environ.get("ZETARIS_USER_AGENT", "")
            if "@" not in user_agent:
                sys.exit("ZETARIS_USER_AGENT must name an app and a contact e-mail, e.g. 'FactSyncChile/0.1 (you@example.org)'")
            sql = sql.replace(PLACEHOLDER, user_agent)
        summary = " ".join(sql.split())[:110]
        if args.dry_run:
            print(f"[{number}] {summary}")
            continue
        status, text = run(sql)
        if status < 400:
            print(f"[{number}] OK   {summary}")
        elif args.skip_exists and "exist" in text.lower():
            print(f"[{number}] SKIP {summary} (already exists)")
        else:
            print(f"[{number}] FAIL {summary}\n     HTTP {status}: {text[:500]}")
            sys.exit(1)


if __name__ == "__main__":
    main()
