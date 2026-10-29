import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptInspection:
    suspicious: bool
    signals: list[str]


SIGNATURES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "INSTRUCTION_OVERRIDE",
        re.compile(
            r"(ignore|disregard).{0,24}(previous|prior|system).{0,16}instruction",
            re.IGNORECASE,
        ),
    ),
    (
        "CHINESE_INSTRUCTION_OVERRIDE",
        re.compile(r"(忽略|无视|覆盖).{0,16}(之前|以上|系统).{0,12}(指令|规则|提示)"),
    ),
    (
        "AUTHORIZATION_BYPASS",
        re.compile(
            r"(bypass|绕过|跳过).{0,20}(auth|verify|权限|验证|确认)",
            re.IGNORECASE,
        ),
    ),
    (
        "SECRET_EXFILTRATION",
        re.compile(
            r"(system prompt|系统提示词|短信验证码|otp|u盾密码)", re.IGNORECASE
        ),
    ),
    (
        "TOOL_INJECTION",
        re.compile(
            r"(call|invoke|调用|执行).{0,16}(tool|function|工具|函数)",
            re.IGNORECASE,
        ),
    ),
)


def inspect_untrusted_text(value: str | None) -> PromptInspection:
    """Classify untrusted text; it never interprets the text as an instruction."""
    if not value:
        return PromptInspection(suspicious=False, signals=[])
    signals = [name for name, pattern in SIGNATURES if pattern.search(value)]
    return PromptInspection(suspicious=bool(signals), signals=signals)
