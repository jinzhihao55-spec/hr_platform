"""Stable natural-person identity without persisting source identifiers."""

from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass


_CERTIFICATE_TYPE_ALIASES = {
    "身份证": "resident_identity_card",
    "居民身份证": "resident_identity_card",
    "中华人民共和国居民身份证": "resident_identity_card",
}


@dataclass(frozen=True)
class DerivedIdentity:
    person_key: str
    key_version: str
    confidence: str
    namespace: str


def _normalize_token(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return "".join(str(value).split()).casefold()


def _normalize_certificate_type(value: object | None) -> str:
    normalized = _normalize_token(value)
    if not normalized:
        return "unknown"
    return _CERTIFICATE_TYPE_ALIASES.get(normalized, normalized)


def derive_person_identity(
    certificate_type: object | None,
    certificate_number: object | None,
    employee_no: object | None,
    *,
    secret: str,
    key_version: str = "v1",
) -> DerivedIdentity:
    """Derive an opaque, stable identity key from the strongest available ID."""
    if not secret:
        raise ValueError("PERSON_KEY_SECRET is required")

    certificate_token = _normalize_token(certificate_number)
    if certificate_token:
        namespace = "certificate"
        identity = f"{_normalize_certificate_type(certificate_type)}:{certificate_token}"
        confidence = "certificate"
    else:
        employee_token = _normalize_token(employee_no)
        if not employee_token:
            raise ValueError(
                "stable identity requires a certificate number or employee number"
            )
        namespace = "employee_no"
        identity = f"employee:{employee_token}"
        confidence = "employee_no_fallback"

    digest = hmac.new(
        secret.encode("utf-8"), identity.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return DerivedIdentity(
        person_key=digest,
        key_version=key_version,
        confidence=confidence,
        namespace=namespace,
    )
