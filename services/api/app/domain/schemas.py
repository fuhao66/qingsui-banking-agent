from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserProfileResponse(ORMModel):
    id: str
    display_name: str
    phone_masked: str
    customer_no: str
    risk_profile: str


class AccountResponse(ORMModel):
    id: str
    name: str
    account_type: str
    masked_number: str
    currency: str
    balance: Decimal
    status: str


class AccountListResponse(BaseModel):
    items: list[AccountResponse]
    total: int
    total_balance: Decimal
    currency: str


class TransactionResponse(ORMModel):
    id: str
    account_id: str
    direction: str
    category: str
    amount: Decimal
    currency: str
    merchant: str | None
    counterparty_name: str | None
    description: str
    status: str
    occurred_at: datetime
    is_recurring: bool
    risk_flag: str | None
    external_reference: str


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    total: int
    limit: int
    offset: int


class CategorySummary(BaseModel):
    category: str
    amount: Decimal
    transaction_count: int
    share_percent: Decimal


class BillSummaryResponse(BaseModel):
    month: str
    currency: str
    income: Decimal
    outflow: Decimal
    net_cashflow: Decimal
    previous_month_outflow: Decimal
    outflow_change_percent: Decimal | None
    transaction_count: int
    suspicious_count: int
    categories: list[CategorySummary]


class PayeeResponse(ORMModel):
    id: str
    name: str
    alias: str | None
    bank_name: str
    account_masked: str
    phone_masked: str | None
    is_frequent: bool
    last_transfer_at: datetime | None


class PayeeSearchResponse(BaseModel):
    query: str
    items: list[PayeeResponse]
    requires_disambiguation: bool


class SubscriptionResponse(ORMModel):
    id: str
    account_id: str
    merchant: str
    product_name: str
    amount: Decimal
    currency: str
    billing_cycle: str
    status: str
    next_charge_at: datetime | None
    last_charge_at: datetime | None
    cancellation_channel: str | None
    confidence: Decimal


class SubscriptionListResponse(BaseModel):
    items: list[SubscriptionResponse]
    total: int
    monthly_equivalent: Decimal


class BankCardResponse(ORMModel):
    id: str
    account_id: str
    card_name: str
    network: str
    masked_number: str
    last4: str
    status: str
    daily_limit: Decimal
    transaction_limit: Decimal
    online_transactions_enabled: bool


class BankCardListResponse(BaseModel):
    items: list[BankCardResponse]
    total: int


class InvestmentProductResponse(ORMModel):
    id: str
    name: str
    category: str
    risk_level: str
    min_amount: Decimal
    expected_return_low: Decimal
    expected_return_high: Decimal
    term_months: int
    liquidity: str
    description: str


class InvestmentProductListResponse(BaseModel):
    items: list[InvestmentProductResponse]
    total: int


class TransferDraftCreate(StrictRequest):
    source_account_id: str
    payee_id: str
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    memo: str | None = Field(default=None, max_length=80)
    scheduled_for: datetime | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("memo")
    @classmethod
    def normalize_memo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class TransferDraftResponse(ORMModel):
    id: str
    user_id: str
    source_account_id: str
    payee_id: str
    amount: Decimal
    currency: str
    memo: str | None
    scheduled_for: datetime | None
    status: str
    expires_at: datetime
    created_at: datetime


class ApiErrorDetail(BaseModel):
    code: str
    message: str


class PolicyDecisionResponse(ORMModel):
    id: str
    draft_id: str
    risk_level: str
    required_action: str
    policy_version: str
    daily_total_before: Decimal
    projected_daily_total: Decimal
    reason_codes: list[str]
    prompt_signals: list[str]
    created_at: datetime


class PolicyEvaluationResponse(BaseModel):
    draft_id: str
    draft_status: str
    decision: PolicyDecisionResponse
    next_action: str


class TransferConfirmationRequest(StrictRequest):
    confirmed: bool


class TransferConfirmationResponse(BaseModel):
    draft_id: str
    status: str
    next_action: str


class AuthChallengeResponse(ORMModel):
    id: str
    draft_id: str
    method: str
    destination_masked: str
    status: str
    attempts: int
    expires_at: datetime
    created_at: datetime


class AuthVerificationRequest(StrictRequest):
    code: str = Field(pattern=r"^\d{6}$")


class AuthVerificationResponse(BaseModel):
    challenge_id: str
    draft_id: str
    challenge_status: str
    draft_status: str
    next_action: str


class TransferExecutionResponse(ORMModel):
    id: str
    draft_id: str
    transaction_id: str
    receipt_no: str
    amount: Decimal
    currency: str
    status: str
    created_at: datetime


class SecurityStatusResponse(BaseModel):
    locked: bool
    consecutive_failures: int
    locked_until: datetime | None
    policy_version: str


class PolicyMatrixItem(BaseModel):
    risk_level: str
    execution_strategy: str
    examples: list[str]


class PolicyMatrixResponse(BaseModel):
    policy_version: str
    transfer_daily_threshold: Decimal
    levels: list[PolicyMatrixItem]


class AuditEventResponse(ORMModel):
    id: str
    correlation_id: str
    action: str
    outcome: str
    risk_level: str | None
    resource_type: str
    resource_id: str
    reason_codes: list[str]
    details: dict[str, object]
    previous_hash: str | None
    event_hash: str
    created_at: datetime


class AuditEventListResponse(BaseModel):
    items: list[AuditEventResponse]
    total: int
    chain_valid: bool


class AgentRunCreate(StrictRequest):
    message: str = Field(min_length=1, max_length=1000)
    conversation_id: str | None = None
    channel: Literal["app", "im", "api"] = "app"

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message cannot be blank")
        return normalized


class AgentEvidenceRunCreate(StrictRequest):
    message: str = Field(min_length=1, max_length=1000)
    conversation_id: str | None = None
    channel: Literal["app", "im", "api"] = "app"
    evidence_text: str | None = Field(default=None, max_length=4000)
    image_data_url: str | None = Field(default=None, max_length=5_600_000)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message cannot be blank")
        return normalized


class DemoResetRequest(StrictRequest):
    confirmation: Literal["RESET_DEMO_DATA"]


class DemoResetResponse(BaseModel):
    status: Literal["reset"]
    reset_at: datetime
    user_id: str
    audit_event_id: str


class ScheduledTaskResponse(ORMModel):
    id: str
    run_id: str
    source_account_id: str
    task_type: str
    title: str
    status: str
    execute_at: datetime
    budget: Decimal
    reserved_amount: Decimal
    currency: str
    risk_level: str
    plan: list[dict[str, object]]
    items: list[dict[str, object]]
    created_at: datetime
    updated_at: datetime


class ScheduledTaskListResponse(BaseModel):
    items: list[ScheduledTaskResponse]
    total: int
    active_reserved_amount: Decimal
    currency: str = "CNY"


class ScheduledTaskActionRequest(StrictRequest):
    action: Literal["pause", "resume", "cancel"]
    confirmed: Literal[True]


class ExperienceLoginRequest(StrictRequest):
    invite_code: str = Field(min_length=4, max_length=128)
    display_name: str = Field(min_length=1, max_length=40)


class ExperienceLoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user_id: str
    display_name: str


class ExperienceProfileResponse(BaseModel):
    user_id: str
    display_name: str
    expires_at: datetime
    request_count: int


class ExperienceAdminStatsResponse(BaseModel):
    total_sessions: int
    active_sessions: int
    total_requests: int
    agent_runs: int
    scheduled_tasks: int
    recent_sessions: list[dict[str, object]]


class AgentResumeRequest(StrictRequest):
    selected_payee_id: str | None = None
    selected_subscription_id: str | None = None
    confirmed: bool | None = None
    auth_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    clarification_message: str | None = Field(default=None, max_length=500)


class AgentHandoffRequest(StrictRequest):
    reason: str = Field(min_length=2, max_length=240)


class AgentHumanResolutionRequest(StrictRequest):
    action: Literal["resume", "cancel", "complete"]
    note: str = Field(min_length=2, max_length=240)


class AgentPlanNodeResponse(BaseModel):
    id: str
    kind: str
    tool_name: str | None
    depends_on: list[str]
    risk_level: str
    description: str


class AgentStepResponse(ORMModel):
    id: str
    node_id: str
    sequence: int
    kind: str
    tool_name: str | None
    status: str
    input_data: dict[str, object]
    output_data: dict[str, object]
    error_code: str | None
    started_at: datetime
    finished_at: datetime | None


class AgentHandoffResponse(ORMModel):
    id: str
    status: str
    reason: str
    resume_status: str
    resolution: str | None
    requested_at: datetime
    resolved_at: datetime | None


class GuardianAssessmentResponse(ORMModel):
    id: str
    source_type: str
    model_provider: str
    scam_score: int
    disposition: str
    original_risk: str
    effective_risk: str
    signals: list[dict[str, object]]
    evidence_summary: str | None
    counterfactual: dict[str, object]
    decision_receipt: dict[str, object]
    receipt_hash: str | None
    created_at: datetime


class AgentRunResponse(ORMModel):
    id: str
    conversation_id: str
    channel: str
    user_message: str
    intent: str
    confidence: Decimal
    model_provider: str
    status: str
    plan: list[AgentPlanNodeResponse]
    plan_hash: str
    current_node_id: str | None
    pending_action: dict[str, object] | None
    result: dict[str, object] | None
    response_text: str | None
    error_code: str | None
    version: int
    steps: list[AgentStepResponse] = Field(default_factory=list)
    handoff: AgentHandoffResponse | None = None
    guardian: GuardianAssessmentResponse | None = None
    created_at: datetime
    updated_at: datetime


class AgentConversationResponse(ORMModel):
    id: str
    channel: str
    status: str
    memory: dict[str, object]
    created_at: datetime
    updated_at: datetime


class AgentToolResponse(BaseModel):
    name: str
    risk_level: str
    side_effect: bool
    description: str


class AgentToolListResponse(BaseModel):
    items: list[AgentToolResponse]
    total: int
