import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent.intents import (
    DeterministicIntentAdapter,
    OpenAIResponsesIntentAdapter,
    QwenChatIntentAdapter,
    ResilientIntentAdapter,
    get_intent_adapter,
)
from app.core.config import Settings, settings


class FakeQwenCompletions:
    def __init__(self, content: str) -> None:
        self.content = content
        self.kwargs: dict[str, object] = {}

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


def test_qwen_adapter_requests_json_and_validates_the_intent(monkeypatch) -> None:
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(settings, "qwen_model", "qwen-plus")
    completion = FakeQwenCompletions(
        json.dumps(
            {
                "intent": "investment.recommend",
                "confidence": 0.93,
                "slots": {
                    "investment_amount": "2万",
                    "horizon_months": "半年",
                    "risk_preference": "moderate",
                },
                "missing_slots": [],
            }
        )
    )
    adapter = QwenChatIntentAdapter()
    adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=completion))

    result = asyncio.run(
        adapter.classify(
            "我打算拿两万块放着半年，尽量别太激进",
            {
                "last_intent": "account.balance",
                "private_account_number": "should-not-be-sent",
            },
            "demo-user",
        )
    )

    assert result.intent == "investment.recommend"
    assert result.slots["investment_amount"] == "20000"
    assert result.slots["horizon_months"] == "6"
    assert result.slots["risk_preference"] == "balanced"
    assert completion.kwargs["model"] == "qwen-plus"
    assert completion.kwargs["response_format"] == {"type": "json_object"}
    assert "private_account_number" not in str(completion.kwargs["messages"])


def test_provider_selection_keeps_qwen_and_openai_independent(monkeypatch) -> None:
    monkeypatch.setattr(settings, "agent_model_provider", "qwen")
    monkeypatch.setattr(settings, "dashscope_api_key", "qwen-test-key")
    monkeypatch.setattr(settings, "openai_api_key", "openai-test-key")

    qwen_adapter = get_intent_adapter()
    assert isinstance(qwen_adapter, ResilientIntentAdapter)
    assert isinstance(qwen_adapter.primary, QwenChatIntentAdapter)

    monkeypatch.setattr(settings, "agent_model_provider", "openai")
    openai_adapter = get_intent_adapter()
    assert isinstance(openai_adapter, ResilientIntentAdapter)
    assert isinstance(openai_adapter.primary, OpenAIResponsesIntentAdapter)

    monkeypatch.setattr(settings, "agent_model_provider", "qwen")
    monkeypatch.setattr(settings, "dashscope_api_key", None)
    assert isinstance(get_intent_adapter(), DeterministicIntentAdapter)


def test_qwen_base_url_rejects_non_aliyun_hosts() -> None:
    with pytest.raises(ValidationError, match="aliyuncs.com"):
        Settings(_env_file=None, qwen_base_url="https://attacker.example/v1")
