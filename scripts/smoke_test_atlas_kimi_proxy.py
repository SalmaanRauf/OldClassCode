"""Smoke-test the local Atlas Kimi OpenCode proxy from a work laptop.

This script contacts the local proxy. If the proxy is running, the proxy will
contact Atlas, so do not run it from Codex or from non-work environments.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Kimi-K2.6-1")
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--api-version", default="")
    parser.add_argument(
        "--prompt",
        default="Reply with exactly: Hello from OpenCode",
    )
    args = parser.parse_args()

    url = (
        f"{args.base_url.rstrip('/')}/openai/deployments/"
        f"{args.model}/chat/completions"
    )
    if args.api_version:
        url = f"{url}?api-version={args.api_version}"
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": args.prompt}],
        "max_tokens": 64,
        "reasoningSummary": "auto",
        "stream": False,
    }

    response = httpx.post(url, json=payload, timeout=300)
    print("status:", response.status_code)
    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        print(response.text)

    return 0 if response.status_code < 400 else 1


if __name__ == "__main__":
    sys.exit(main())
