"""Stable, privacy-preserving natural-person identity contracts."""

import pytest

from app.config import Settings
from app.domain.identity import derive_person_identity


def test_same_normalized_certificate_produces_same_key():
    left = derive_person_identity(
        "身份证", " AB 123 ", "FAKE-E-1", secret="test-secret"
    )
    right = derive_person_identity(
        "居民身份证", "ab123", "FAKE-E-2", secret="test-secret"
    )

    assert left.person_key == right.person_key
    assert left.confidence == "certificate"
    assert left.namespace == "certificate"


def test_certificate_identity_does_not_depend_on_employee_number():
    left = derive_person_identity(
        "护照", " fake-passport-1 ", "FAKE-E-1", secret="test-secret"
    )
    right = derive_person_identity(
        "护照", "FAKE-PASSPORT-1", "FAKE-E-9", secret="test-secret"
    )

    assert left.person_key == right.person_key


def test_missing_certificate_uses_namespaced_employee_fallback():
    value = derive_person_identity(
        None, None, " fake-e-1 ", secret="test-secret", key_version="v2"
    )

    assert value.confidence == "employee_no_fallback"
    assert value.namespace == "employee_no"
    assert value.key_version == "v2"


def test_nan_certificate_uses_employee_fallback():
    value = derive_person_identity(
        float("nan"), float("nan"), "FAKE-E-1", secret="test-secret"
    )

    assert value.confidence == "employee_no_fallback"
    assert value.namespace == "employee_no"


def test_missing_certificate_and_employee_number_is_rejected():
    with pytest.raises(ValueError, match="stable identity"):
        derive_person_identity(None, None, None, secret="test-secret")


def test_empty_secret_is_rejected():
    with pytest.raises(ValueError, match="PERSON_KEY_SECRET"):
        derive_person_identity("身份证", "FAKE-1", "FAKE-E-1", secret="")


def test_different_secrets_produce_different_keys():
    left = derive_person_identity(
        "身份证", "FAKE-1", "FAKE-E-1", secret="test-secret-a"
    )
    right = derive_person_identity(
        "身份证", "FAKE-1", "FAKE-E-1", secret="test-secret-b"
    )

    assert left.person_key != right.person_key


def test_production_settings_require_person_key_secret():
    with pytest.raises(ValueError, match="person_key_secret"):
        Settings(
            app_env="prod",
            mysql_password="fake-password",
            redis_password="fake-password",
        )


def test_development_settings_allow_missing_person_key_secret():
    configured = Settings(app_env="dev", person_key_secret="")

    assert configured.person_key_secret == ""
    assert configured.person_key_version == "v1"
