"""Parsing the Claude CLI's JSON envelope (no real CLI in tests)."""

import json

import pytest

from blattwerk.claude_cli import ClaudeError, parse_result


def envelope(**kw: object) -> str:
    return json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.12, "duration_ms": 31000,
                       "modelUsage": {"claude-sonnet-x": {}}, **kw})  # fmt: skip


def test_structured_output_is_used() -> None:
    answer, info = parse_result(envelope(structured_output={"summary": "ok"}), 0, "")
    assert answer == {"summary": "ok"}
    assert info == {"cost_usd": 0.12, "duration_ms": 31000, "model": "claude-sonnet-x"}


def test_falls_back_to_json_in_result_text() -> None:
    answer, _ = parse_result(envelope(result=json.dumps({"summary": "ok"})), 0, "")
    assert answer == {"summary": "ok"}


@pytest.mark.parametrize(
    ("stdout", "code", "stderr", "fragment"),
    [
        ("not json", 1, "Invalid API key · Please run /login (auth)", "Token"),
        (envelope(is_error=True, subtype="error_max_budget_usd"), 1, "", "Kostenlimit"),
        (envelope(is_error=True, result="Invalid API key · Please run /login"), 1, "", "Token"),
        (envelope(is_error=True, subtype="error_during_execution"), 1, "", "Fehler"),
        (envelope(result="Hier ist dein Plan: ..."), 0, "", "kein gültiges JSON"),
    ],
)
def test_errors_become_german_messages(stdout: str, code: int, stderr: str, fragment: str) -> None:
    with pytest.raises(ClaudeError, match=fragment):
        parse_result(stdout, code, stderr)
