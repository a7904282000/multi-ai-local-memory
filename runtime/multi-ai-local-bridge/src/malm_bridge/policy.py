from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class CaptureDecision:
    decision: str
    reason: str
    kind: str | None = None
    key: str | None = None
    content: str | None = None
    sensitivity: str = "NORMAL"


_LOW_VALUE = {
    "ok", "okay", "thanks", "thank you", "next", "test", "收到", "好", "好的", "下一步", "測試", "謝謝"
}

# Secrets are prohibited from durable memory even when explicitly requested.
_SECRET_RE = re.compile(
    r"(?:password|passcode|api\s*key|private\s*key|secret\s*key|bearer\s+token|auth(?:orization)?\s*token|otp|one[- ]time\s*password|"
    r"密碼|口令|私鑰|API\s*金鑰|API\s*KEY|驗證碼|一次性密碼|存取權杖|授權權杖)",
    re.I,
)

# Public-package default is sensitive_memory=explicit_only. This conservative baseline
# blocks silent promotion when obvious sensitive-domain terms are present. A stronger
# local classifier may replace it without changing the policy interface.
_SENSITIVE_RE = re.compile(
    r"(?:sexual|sex\s+life|sexual\s+orientation|diagnos(?:is|ed)|medical\s+condition|religion|religious|political\s+party|"
    r"race|ethnicity|criminal\s+history|union\s+membership|"
    r"性行為|性生活|性偏好|性傾向|疾病|診斷|病史|宗教|政黨|政治立場|種族|族裔|犯罪紀錄|工會)",
    re.I,
)

_EXPLICIT_RE = re.compile(r"(?:請|幫我)?記住|remember\s+(?:that|this)", re.I)

# High-confidence, user-originated durable classes. These patterns classify; they never
# paraphrase source content. Unknown statements remain CANDIDATE rather than being saved.
_PREFERENCE_RE = re.compile(
    r"(?:^|[\s，。,.])(?:我|本人|i)\s*(?:比較|really\s+)?(?:喜歡|偏好|習慣|不喜歡|討厭|like|love|prefer|dislike|hate)",
    re.I,
)
_RULE_RE = re.compile(
    r"(?:以後|之後|未來|from\s+now\s+on|always|never).{0,80}(?:請|要|不要|禁止|必須|一律|should|must|do\s+not|don't)|"
    r"(?:回答|回覆|處理|工作方式|規則).{0,60}(?:要|不要|禁止|必須|一律|優先)",
    re.I,
)
_DECISION_RE = re.compile(
    r"(?:我(?:們)?(?:已)?決定|決定採用|正式採用|定稿|改成|切換到|不再使用|淘汰|we\s+decided|i\s+decided|switch(?:ed)?\s+to|adopt(?:ed)?)",
    re.I,
)
_PROJECT_STATE_RE = re.compile(
    r"(?:(?:專案|項目|功能|階段|目前|現在).{0,80}(?:已完成|完成了|已通過|PASS|FAIL|BLOCKED)|"
    r"(?:已完成|完成了|已通過).{0,80}(?:專案|項目|功能|階段))",
    re.I,
)


class DefaultCapturePolicy:
    """Conservative deterministic durable-memory classifier.

    Guarantees:
    - ordinary conversation is not automatically saved;
    - obvious secrets are never committed;
    - obvious sensitive memory requires an explicit remember request;
    - high-confidence durable statements can be committed without an explicit keyword;
    - committed automatic content is the user's source text, not an AI paraphrase.

    A future local/model-assisted classifier can replace this implementation behind the
    same interface, but must preserve these safety and source-fidelity invariants.
    """

    def classify(self, user_text: str, assistant_text: str, explicit_remember_request: bool) -> CaptureDecision:
        raw = user_text
        clean = raw.strip()
        if not clean:
            return CaptureDecision("DROP", "empty-user-text")
        if clean.casefold() in _LOW_VALUE or len(clean) <= 2:
            return CaptureDecision("DROP", "low-value-transient")

        explicit = bool(explicit_remember_request or _EXPLICIT_RE.search(clean))
        if _SECRET_RE.search(clean):
            return CaptureDecision("REJECT", "secret-prohibited", sensitivity="SECRET_PROHIBITED")

        sensitive = bool(_SENSITIVE_RE.search(clean))
        if sensitive and not explicit:
            return CaptureDecision("CANDIDATE", "sensitive-explicit-only", sensitivity="SENSITIVE")

        if explicit:
            # Existing explicit-memory behavior intentionally removes only the command
            # prefix. This is capture-time formatting, not migration/source purification.
            content = re.sub(r"^(?:請|幫我)?記住[:：\s]*", "", clean, flags=re.I).strip() or clean
            return CaptureDecision(
                "COMMIT", "explicit-remember", kind="explicit_memory", key="explicit",
                content=content, sensitivity="SENSITIVE" if sensitive else "NORMAL",
            )

        # Automatic durable capture is deliberately narrow. Keep the exact trimmed user
        # statement as memory content; classification metadata is derived separately.
        if _PREFERENCE_RE.search(clean):
            return CaptureDecision("COMMIT", "durable-preference", kind="preference", key="preference", content=clean)
        if _RULE_RE.search(clean):
            return CaptureDecision("COMMIT", "durable-rule", kind="rule", key="rule", content=clean)
        if _DECISION_RE.search(clean):
            return CaptureDecision("COMMIT", "durable-decision", kind="decision", key="decision", content=clean)
        if _PROJECT_STATE_RE.search(clean):
            return CaptureDecision("COMMIT", "durable-project-state", kind="project_state", key="project_state", content=clean)

        return CaptureDecision("CANDIDATE", "semantic-extraction-required")
