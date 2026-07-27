#!/usr/bin/env python3
"""Wait for the single-user deployment's full readiness contract."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any


REQUIRED_FLAGS = ("mysql", "redis", "migration", "output", "config")


def is_ready_payload(payload: Mapping[str, Any]) -> bool:
    return payload.get("status") == "ready" and all(
        payload.get(flag) is True for flag in REQUIRED_FLAGS
    )


def fetch_payload(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("readiness response must be a JSON object")
    return data


def wait_until_ready(
    url: str, *, attempts: int, interval: float, timeout: float
) -> bool:
    last_error = "no response"
    for attempt in range(1, attempts + 1):
        try:
            payload = fetch_payload(url, timeout)
            if is_ready_payload(payload):
                print(f"ready: {url}")
                return True
            last_error = f"not ready: {payload}"
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        print(f"attempt {attempt}/{attempts}: {last_error}", file=sys.stderr)
        if attempt < attempts:
            time.sleep(interval)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.getenv(
            "HR_AGENT_READY_URL", "http://127.0.0.1:8080/api/ready"
        ),
    )
    parser.add_argument("--attempts", type=int, default=30)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    return 0 if wait_until_ready(
        args.url,
        attempts=args.attempts,
        interval=args.interval,
        timeout=args.timeout,
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
