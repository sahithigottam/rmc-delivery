"""Template advice must preserve the calculated risk classification."""
from types import SimpleNamespace

import pytest

from app.services.llm_analyzer import LLMAnalyzer


@pytest.mark.parametrize("risk,expected", [
    ("low", "Dispatch now."),
    ("moderate", "Dispatch with caution."),
    ("high", "Consider delaying dispatch"),
    ("critical", "Do NOT dispatch."),
])
def test_individual_and_comparison_advice_are_consistent(risk, expected):
    prediction = SimpleNamespace(
        risk_level=risk, success_probability=0.5, time_buffer_minutes=10,
        risk_factors=[], route_trips=0, confidence="low",
    )
    analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
    individual = analyzer._template_analysis(prediction)
    comparison = analyzer._template_comparison([{
        "plant_name": "Test plant", "remaining_life": 10,
        "success_prob": 0.5, "risk_level": risk,
    }])
    assert individual["recommendation"] == comparison["dispatch_advice"]
    assert comparison["dispatch_advice"].startswith(expected)
    assert comparison["source"] == "template"
    assert comparison["best_plant"] == "Test plant"
    assert comparison["alternative"] == "N/A"


def test_unknown_risk_requires_review_and_logs_warning(caplog):
    advice = LLMAnalyzer._template_dispatch_advice("unknown")
    assert advice == "Do not dispatch until the risk assessment has been reviewed."
    assert "unrecognized risk level" in caplog.text


def test_empty_comparison_keeps_manual_check_response():
    result = LLMAnalyzer._template_comparison([])
    assert result["best_plant"] == "Unknown"
    assert result["dispatch_advice"] == "Check plant availability manually."


def test_critical_best_plant_does_not_become_dispatchable_with_alternative():
    result = LLMAnalyzer._template_comparison([
        {"plant_name": "Best", "remaining_life": -1, "success_prob": 0.2,
         "risk_level": "critical"},
        {"plant_name": "Alternative", "remaining_life": -5, "success_prob": 0.1,
         "risk_level": "critical"},
    ])
    assert result["dispatch_advice"].startswith("Do NOT dispatch.")
    assert result["alternative"] == "Alternative"
