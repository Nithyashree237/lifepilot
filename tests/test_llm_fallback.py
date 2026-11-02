"""LLM fallback schema validation, privacy and merging tests."""

from __future__ import annotations

import json

import pytest

from lifepilot.pipeline import llm_fallback
from lifepilot.pipeline.extract import ExtractedField
from lifepilot.pipeline.llm_fallback import (
    LLMSchemaError,
    extract_with_llm,
    merge_llm_result,
    validate_llm_response,
)

VALID_RESPONSE = {
    "doc_type": "bill",
    "fields": [
        {"name": "amount_total", "value": "Rs. 2,158.75", "confidence": 0.91},
        {"name": "due_date", "value": "06/11/2026", "confidence": 0.88},
        {"name": "vendor", "value": "BESCOM", "confidence": 0.9},
    ],
    "obligations": [
        {"text": "Pay the bill by 06/11/2026.", "due_date": "06/11/2026", "type": "payment"}
    ],
    "notes": "Parsed from bill",
}


def test_valid_response_is_normalised() -> None:
    result = validate_llm_response(VALID_RESPONSE)
    assert result.doc_type == "bill"
    fields = {item.name: item.value for item in result.fields}
    assert fields["amount_total"] == "2158.75"
    assert fields["due_date"] == "2026-11-06"
    assert result.obligations[0].due_date == "2026-11-06"


def test_aliases_and_type_aliases() -> None:
    payload = {
        "doc_type": "invoice",
        "fields": [{"name": "total_amount", "value": "500", "confidence": 0.7}],
    }
    result = validate_llm_response(payload)
    assert result.doc_type == "bill"
    assert result.fields[0].name == "amount_total"


@pytest.mark.parametrize(
    "payload",
    [
        ["not", "an", "object"],
        {"doc_type": "spaceship", "fields": []},
        {"doc_type": "bill", "fields": {}, "extra": 1},
        {"doc_type": "bill", "fields": [{"name": "unknown_field", "value": "x"}]},
        {"doc_type": "bill", "fields": [{"name": "amount_total", "value": "x"}]},
        {"doc_type": "bill", "fields": [{"name": "amount_total", "value": "100", "confidence": 2}]},
        {"doc_type": "bill", "fields": [{"name": "due_date", "value": "not-a-date"}]},
        {"doc_type": "bill", "fields": [], "obligations": [{"due_date": "2026-01-01"}]},
    ],
)
def test_invalid_payloads_raise_schema_error(payload) -> None:
    with pytest.raises(LLMSchemaError):
        validate_llm_response(payload)


def test_disabled_llm_never_calls_network(monkeypatch) -> None:
    monkeypatch.setattr(llm_fallback.config, "LLM_API_KEY", "test-key")
    called = {"count": 0}

    def fake_call(payload):
        called["count"] += 1
        return json.dumps(VALID_RESPONSE)

    result = extract_with_llm(
        "some document text", enabled=False, missing_fields=["amount_total"], http_call=fake_call
    )
    assert result is None
    assert called["count"] == 0


def test_missing_api_key_skips_call(monkeypatch) -> None:
    monkeypatch.setattr(llm_fallback.config, "LLM_API_KEY", "")
    called = {"count": 0}

    def fake_call(payload):
        called["count"] += 1
        return json.dumps(VALID_RESPONSE)

    assert extract_with_llm("text", enabled=True, http_call=fake_call) is None
    assert called["count"] == 0


def test_enabled_llm_validates_json(monkeypatch) -> None:
    monkeypatch.setattr(llm_fallback.config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_fallback.config, "LLM_MODEL", "test-model")
    prompts = {}

    def fake_call(payload):
        prompts.update(payload)
        return "```json\n" + json.dumps(VALID_RESPONSE) + "\n```"

    result = extract_with_llm(
        "Total Amount Due: Rs. 2158.75",
        enabled=True,
        doc_type="bill",
        missing_fields=["amount_total"],
        http_call=fake_call,
    )
    assert result is not None
    assert result.model == "test-model"
    assert result.fields[0].name == "amount_total"
    assert prompts["temperature"] == 0
    assert "untrusted data" in prompts["messages"][0]["content"]


def test_malformed_llm_json_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(llm_fallback.config, "LLM_API_KEY", "test-key")
    assert (
        extract_with_llm("text", enabled=True, http_call=lambda payload: "not json")
        is None
    )
    assert (
        extract_with_llm(
            "text",
            enabled=True,
            http_call=lambda payload: json.dumps({"doc_type": "alien", "fields": []}),
        )
        is None
    )


def test_merge_only_replaces_missing_or_low_confidence_fields() -> None:
    existing = [
        ExtractedField("vendor", "BESCOM", "text", 0.9),
        ExtractedField("amount_total", "100", "money", 0.4),
    ]
    result = validate_llm_response(VALID_RESPONSE)
    merged = merge_llm_result(existing, result, review_threshold=0.6)
    values = {item.field_name: item for item in merged}
    assert values["vendor"].value == "BESCOM"
    assert values["vendor"].source != "llm"
    assert values["amount_total"].value == "2158.75"
    assert values["amount_total"].source == "llm"
    assert values["due_date"].source == "llm"
    assert all(item.confidence <= 0.82 for item in merged if item.source == "llm")


def test_connection_without_key(monkeypatch) -> None:
    monkeypatch.setattr(llm_fallback.config, "LLM_API_KEY", "")
    ok, message = llm_fallback.test_connection()
    assert ok is False
    assert "No API key" in message


def test_connection_success(monkeypatch) -> None:
    monkeypatch.setattr(llm_fallback.config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_fallback.config, "LLM_MODEL", "test-model")
    monkeypatch.setattr(
        llm_fallback, "_default_http_call", lambda payload: json.dumps({"ok": True})
    )
    ok, message = llm_fallback.test_connection()
    assert ok is True
    assert "test-model" in message


def test_connection_handles_non_json(monkeypatch) -> None:
    monkeypatch.setattr(llm_fallback.config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_fallback, "_default_http_call", lambda payload: "hello")
    ok, message = llm_fallback.test_connection()
    assert ok is False
    assert "Connection failed" in message
