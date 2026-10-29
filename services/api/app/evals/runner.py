import argparse
import asyncio
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.guardian import static_signal_assessment
from app.agent.intents import DeterministicIntentAdapter, IntentName, get_intent_adapter
from app.agent.planner import generate_plan
from app.agent.tools import TOOL_REGISTRY
from app.core.config import settings
from app.security.prompt_guard import inspect_untrusted_text


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: str
    message: str
    expected_intent: IntentName | None = None
    expected_slots: dict[str, str | None] = Field(default_factory=dict)
    expect_blocked: bool = False
    expected_max_risk: Literal["green", "yellow", "red"] | None = None
    expected_guardian_disposition: Literal["allow", "step_up", "block"] | None = None


class EvalCaseResult(BaseModel):
    id: str
    category: str
    expected_intent: IntentName | None
    predicted_intent: IntentName | None
    intent_correct: bool | None
    expected_slots: dict[str, str | None]
    predicted_slots: dict[str, str | None]
    slots_correct: int
    slots_total: int
    expected_blocked: bool
    blocked: bool
    guard_correct: bool
    expected_max_risk: str | None
    predicted_max_risk: str | None
    risk_correct: bool | None
    expected_guardian_disposition: str | None
    predicted_guardian_disposition: str
    guardian_correct: bool | None
    model_provider: str
    whitelist_violations: list[str]
    latency_ms: float
    passed: bool
    error: str | None = None


RISK_RANK = {"green": 1, "yellow": 2, "red": 3}


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile_value * len(ordered)) - 1)
    return round(ordered[index], 2)


async def evaluate_case(case: EvalCase, adapter) -> EvalCaseResult:
    started = perf_counter()
    inspection = inspect_untrusted_text(case.message)
    selected_adapter = DeterministicIntentAdapter() if inspection.suspicious else adapter
    try:
        planning = await generate_plan(
            case.message,
            {},
            "evaluation-user",
            adapter=selected_adapter,
        )
        intent_data = planning["intent_data"]
        predicted_intent = intent_data["intent"]
        predicted_slots = intent_data["slots"]
        plan = planning["plan"]
        tools = [node["tool_name"] for node in plan if node.get("tool_name")]
        whitelist_violations = [name for name in tools if name not in TOOL_REGISTRY]
        risks = [str(node["risk_level"]) for node in plan]
        predicted_max_risk = max(risks, key=RISK_RANK.get) if risks else None
        slots_correct = sum(
            predicted_slots.get(name) == expected for name, expected in case.expected_slots.items()
        )
        intent_correct = (
            None if case.expected_intent is None else predicted_intent == case.expected_intent
        )
        risk_correct = (
            None if case.expected_max_risk is None else predicted_max_risk == case.expected_max_risk
        )
        _, guardian_disposition, _ = static_signal_assessment(case.message, inspection.signals)
        guardian_correct = (
            None
            if case.expected_guardian_disposition is None
            else guardian_disposition == case.expected_guardian_disposition
        )
        blocked = inspection.suspicious
        guard_correct = blocked == case.expect_blocked
        passed = (
            all(value is not False for value in (intent_correct, risk_correct, guard_correct, guardian_correct))
            and slots_correct == len(case.expected_slots)
            and not whitelist_violations
        )
        return EvalCaseResult(
            id=case.id,
            category=case.category,
            expected_intent=case.expected_intent,
            predicted_intent=predicted_intent,
            intent_correct=intent_correct,
            expected_slots=case.expected_slots,
            predicted_slots=predicted_slots,
            slots_correct=slots_correct,
            slots_total=len(case.expected_slots),
            expected_blocked=case.expect_blocked,
            blocked=blocked,
            guard_correct=guard_correct,
            expected_max_risk=case.expected_max_risk,
            predicted_max_risk=predicted_max_risk,
            risk_correct=risk_correct,
            expected_guardian_disposition=case.expected_guardian_disposition,
            predicted_guardian_disposition=guardian_disposition,
            guardian_correct=guardian_correct,
            model_provider=str(planning["model_provider"]),
            whitelist_violations=whitelist_violations,
            latency_ms=round((perf_counter() - started) * 1000, 2),
            passed=passed,
        )
    except Exception as exc:  # noqa: BLE001 - one bad case must not abort the suite
        return EvalCaseResult(
            id=case.id,
            category=case.category,
            expected_intent=case.expected_intent,
            predicted_intent=None,
            intent_correct=False if case.expected_intent is not None else None,
            expected_slots=case.expected_slots,
            predicted_slots={},
            slots_correct=0,
            slots_total=len(case.expected_slots),
            expected_blocked=case.expect_blocked,
            blocked=inspection.suspicious,
            guard_correct=inspection.suspicious == case.expect_blocked,
            expected_max_risk=case.expected_max_risk,
            predicted_max_risk=None,
            risk_correct=False if case.expected_max_risk is not None else None,
            expected_guardian_disposition=case.expected_guardian_disposition,
            predicted_guardian_disposition="allow",
            guardian_correct=False if case.expected_guardian_disposition is not None else None,
            model_provider=getattr(selected_adapter, "provider_name", "unknown"),
            whitelist_violations=[],
            latency_ms=round((perf_counter() - started) * 1000, 2),
            passed=False,
            error=type(exc).__name__,
        )


async def run_evaluation(cases: list[EvalCase]) -> dict[str, object]:
    adapter = get_intent_adapter()
    results = [await evaluate_case(case, adapter) for case in cases]
    intent_results = [item for item in results if item.intent_correct is not None]
    risk_results = [item for item in results if item.risk_correct is not None]
    guardian_results = [item for item in results if item.guardian_correct is not None]
    slot_total = sum(item.slots_total for item in results)
    slot_correct = sum(item.slots_correct for item in results)
    security_cases = [item for item in results if item.expected_blocked]
    latencies = [item.latency_ms for item in results]
    summary = {
        "total_cases": len(results),
        "passed_cases": sum(item.passed for item in results),
        "intent_accuracy": round(
            sum(item.intent_correct is True for item in intent_results) / len(intent_results),
            4,
        )
        if intent_results
        else 0.0,
        "slot_accuracy": round(slot_correct / slot_total, 4) if slot_total else 1.0,
        "risk_accuracy": round(
            sum(item.risk_correct is True for item in risk_results) / len(risk_results),
            4,
        )
        if risk_results
        else 0.0,
        "guardian_accuracy": round(
            sum(item.guardian_correct is True for item in guardian_results) / len(guardian_results), 4
        ) if guardian_results else 1.0,
        "security_block_rate": round(
            sum(item.blocked for item in security_cases) / len(security_cases), 4
        )
        if security_cases
        else 1.0,
        "unsafe_bypass_count": sum(not item.blocked for item in security_cases),
        "whitelist_violation_count": sum(len(item.whitelist_violations) for item in results),
        "fallback_count": sum(item.model_provider == "deterministic_fallback" for item in results),
        "error_count": sum(item.error is not None for item in results),
        "latency_p50_ms": percentile(latencies, 0.5),
        "latency_p95_ms": percentile(latencies, 0.95),
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": settings.agent_model_provider,
        "model": (
            settings.qwen_model
            if settings.agent_model_provider == "qwen"
            else settings.openai_model
            if settings.agent_model_provider == "openai"
            else settings.agent_model_provider
        ),
        "summary": summary,
        "cases": [item.model_dump(mode="json") for item in results],
    }


def load_cases(path: Path) -> list[EvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [EvalCase.model_validate(item) for item in payload["cases"]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Banking Agent intent and safety evals.")
    parser.add_argument("--cases", type=Path, default=Path("evals/cases.json"))
    parser.add_argument("--output", type=Path, default=Path("../../data/eval-report.json"))
    parser.add_argument(
        "--provider",
        choices=("deterministic", "qwen", "openai", "auto"),
        default=settings.agent_model_provider,
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    settings.agent_model_provider = args.provider
    cases = load_cases(args.cases)
    if args.limit > 0:
        cases = cases[: args.limit]
    report = asyncio.run(run_evaluation(cases))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = report["summary"]
    print(
        "评测完成："
        f"{summary['passed_cases']}/{summary['total_cases']} 通过，"
        f"意图准确率 {summary['intent_accuracy']:.1%}，"
        f"槽位准确率 {summary['slot_accuracy']:.1%}，"
        f"安全拦截率 {summary['security_block_rate']:.1%}，"
        f"白名单违规 {summary['whitelist_violation_count']}。"
    )
    print(f"报告：{args.output.resolve()}")


if __name__ == "__main__":
    main()
