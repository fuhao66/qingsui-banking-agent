import asyncio
from pathlib import Path

from app.agent.intents import DeterministicIntentAdapter
from app.evals.runner import EvalCase, evaluate_case, load_cases


def test_eval_case_checks_intent_slots_risk_and_whitelist() -> None:
    case = EvalCase(
        id="transfer-test",
        category="transfer",
        message="给妈妈转100元",
        expected_intent="transfer.create",
        expected_slots={"amount": "100", "recipient_query": "妈妈"},
        expected_max_risk="red",
    )

    result = asyncio.run(evaluate_case(case, DeterministicIntentAdapter()))

    assert result.passed is True
    assert result.intent_correct is True
    assert result.slots_correct == result.slots_total == 2
    assert result.whitelist_violations == []


def test_versioned_eval_dataset_contains_normal_and_attack_cases() -> None:
    path = Path(__file__).parents[1] / "evals" / "cases.json"
    cases = load_cases(path)

    assert len(cases) == 61
    assert sum(case.expect_blocked for case in cases) == 10
    assert sum(case.category == "cross-scenario" for case in cases) == 6
    assert sum(case.category == "guardian" for case in cases) == 6
    assert len({case.id for case in cases}) == len(cases)
