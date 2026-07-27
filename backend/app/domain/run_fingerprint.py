"""Canonical report-Run fingerprints built from four sources and a baseline."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from app.models.runs import SourceType


class IncompleteSourceBundle(ValueError):
    def __init__(self, missing: list[str] | tuple[str, ...]):
        self.missing = tuple(sorted(missing))
        super().__init__(f"source bundle is missing: {', '.join(self.missing)}")


class UnexpectedSourceBundleKeys(ValueError):
    def __init__(self, unexpected: list[str] | tuple[str, ...]):
        self.unexpected = tuple(sorted(unexpected))
        super().__init__(
            f"source bundle contains unexpected keys: {', '.join(self.unexpected)}"
        )


def compute_source_bundle_hash(
    source_hashes: Mapping[str, str],
    baseline_report_id: str,
    baseline_sha256: str,
) -> str:
    """Hash a complete source/baseline bundle with stable key ordering."""
    required = {source.value for source in SourceType}
    supplied = set(source_hashes)
    missing = required - supplied
    if missing:
        raise IncompleteSourceBundle(tuple(missing))
    unexpected = supplied - required
    if unexpected:
        raise UnexpectedSourceBundleKeys(tuple(unexpected))

    payload = {
        "sources": {key: source_hashes[key] for key in sorted(required)},
        "baseline_report_id": baseline_report_id,
        "baseline_sha256": baseline_sha256,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
