"""Scan artifacts for configured sensitive values without echoing matches."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Collection, Iterable, Mapping


_IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "venv",
}
_MAX_FILE_BYTES = 32 * 1024 * 1024
_BUILTIN_PATTERNS = {
    "private_key": re.compile(
        rb"-{5}BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-{5}"
    ),
    "api_key": re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    "credential_url": re.compile(
        rb"(?:mysql|redis)(?:\+[A-Za-z0-9_]+)?://[^\s:/]+:[^\s@]+@"
    ),
}


@dataclass(frozen=True)
class Finding:
    path: Path
    rule: str
    message: str


def _files(paths: Iterable[Path]) -> Iterable[Path]:
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (
                candidate
                for candidate in path.rglob("*")
                if candidate.is_file()
                and not any(
                    part in _IGNORED_DIRECTORIES
                    for part in candidate.relative_to(path).parts
                )
            )


def scan_paths(
    paths: Iterable[Path],
    *,
    sensitive_values: Mapping[str, Collection[str]] | None = None,
) -> list[Finding]:
    """Return file/rule findings; matched values never enter result objects."""
    encoded_rules = {
        rule: tuple(value.encode("utf-8") for value in values if value)
        for rule, values in (sensitive_values or {}).items()
    }
    findings: list[Finding] = []
    for path in _files(paths):
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            content = path.read_bytes()
        except OSError:
            continue
        for rule, pattern in _BUILTIN_PATTERNS.items():
            if pattern.search(content):
                findings.append(
                    Finding(
                        path=path,
                        rule=rule,
                        message=f"high-confidence sensitive pattern matched rule {rule}",
                    )
                )
        for rule, values in encoded_rules.items():
            if values and any(value in content for value in values):
                findings.append(
                    Finding(
                        path=path,
                        rule=rule,
                        message=f"configured sensitive value matched rule {rule}",
                    )
                )
    return findings


def _load_sensitive_values(path: Path | None) -> dict[str, list[str]]:
    if path is None:
        return {}
    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or any(
        not isinstance(rule, str)
        or not isinstance(values, list)
        or any(not isinstance(value, str) for value in values)
        for rule, values in payload.items()
    ):
        raise ValueError("sensitive values file must be a JSON object of string lists")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan release artifacts without echoing matched values."
    )
    parser.add_argument("paths", nargs="*", type=Path, default=[Path(".")])
    parser.add_argument("--sensitive-values-file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        values = _load_sensitive_values(args.sensitive_values_file)
        findings = scan_paths(args.paths, sensitive_values=values)
    except (OSError, ValueError, json.JSONDecodeError):
        print("privacy scan BLOCKED configuration_error")
        return 2
    if not findings:
        print("privacy scan PASS findings=0")
        return 0
    for finding in findings:
        print(f"{finding.path}: {finding.rule}: {finding.message}")
    print(f"privacy scan FAIL findings={len(findings)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
