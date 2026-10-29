import hashlib
import hmac
import json
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict

from app.agent.intents import IntentAdapter, IntentEnvelope, get_intent_adapter
from app.agent.tools import require_registered_tool


class PlanNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["tool", "gate"]
    tool_name: str | None
    depends_on: list[str]
    risk_level: Literal["green", "yellow", "red"]
    description: str


class PlanningState(TypedDict, total=False):
    message: str
    memory: dict[str, object]
    user_id: str
    intent_data: dict[str, object]
    model_provider: str
    plan: list[dict[str, object]]
    plan_hash: str


def plan_for_intent(intent: IntentEnvelope) -> list[PlanNode]:
    if intent.intent == "fraud.assess":
        return [PlanNode(id="guardian_review", kind="tool", tool_name="guardian.risk.assess", depends_on=[], risk_level="green", description="将证据作为不可信数据进行独立反诈审查")]
    if intent.intent == "account.balance":
        return [
            PlanNode(
                id="query_accounts",
                kind="tool",
                tool_name="accounts.list",
                depends_on=[],
                risk_level="green",
                description="查询账户与余额",
            )
        ]
    if intent.intent == "bill.summary":
        return [
            PlanNode(
                id="summarize_bill",
                kind="tool",
                tool_name="bill.summary",
                depends_on=[],
                risk_level="green",
                description="从交易账本计算月度账单",
            )
        ]
    if intent.intent == "bill.annual":
        return [PlanNode(id="annual_report", kind="tool", tool_name="bill.annual", depends_on=[], risk_level="green", description="聚合十二个月账本生成年度报告")]
    if intent.intent == "investment.holdings":
        return [PlanNode(id="list_holdings", kind="tool", tool_name="investment.holdings.list", depends_on=[], risk_level="green", description="查询当前理财持仓")]
    if intent.intent == "occasion.detect":
        return [PlanNode(id="scan_life_events", kind="tool", tool_name="life.events.scan", depends_on=[], risk_level="green", description="扫描已授权的生活事件")]
    extended_tools = {
        "transfer.schedule": ("transfer.schedule", "red"),
        "collection.aa": ("collection.aa.create", "yellow"),
        "subscription.reminder": ("subscription.reminder.create", "yellow"),
        "card.apply": ("card.application.create", "red"),
        "card.limit": ("card.limit.update", "red"),
        "card.restriction": ("card.restriction.update", "red"),
        "investment.subscribe": ("investment.subscribe", "red"),
        "investment.redeem": ("investment.redeem", "red"),
    }
    if intent.intent in extended_tools:
        tool_name, risk = extended_tools[intent.intent]
        return [
            PlanNode(id="prepare_operation", kind="gate", tool_name=None, depends_on=[], risk_level="green", description="校验并补齐动态业务参数"),
            PlanNode(id="authorization_gate", kind="gate", tool_name=None, depends_on=["prepare_operation"], risk_level=risk, description="等待明确确认或强验证"),
            PlanNode(id="execute_operation", kind="tool", tool_name=tool_name, depends_on=["authorization_gate"], risk_level=risk, description="通过白名单执行器完成操作并审计"),
        ]
    if intent.intent == "subscription.list":
        return [
            PlanNode(
                id="list_subscriptions",
                kind="tool",
                tool_name="subscriptions.list",
                depends_on=[],
                risk_level="green",
                description="查询并汇总活跃订阅",
            )
        ]
    if intent.intent == "subscription.cancel":
        return [
            PlanNode(
                id="resolve_subscription",
                kind="tool",
                tool_name="subscriptions.search",
                depends_on=[],
                risk_level="green",
                description="解析需要取消的订阅",
            ),
            PlanNode(
                id="authorization_gate",
                kind="gate",
                tool_name=None,
                depends_on=["resolve_subscription"],
                risk_level="yellow",
                description="等待用户核对并确认取消",
            ),
            PlanNode(
                id="cancel_subscription",
                kind="tool",
                tool_name="subscription.cancel",
                depends_on=["authorization_gate"],
                risk_level="yellow",
                description="执行订阅取消并写入审计",
            ),
        ]
    if intent.intent == "card.list":
        return [
            PlanNode(
                id="list_cards",
                kind="tool",
                tool_name="cards.list",
                depends_on=[],
                risk_level="green",
                description="查询脱敏银行卡及状态",
            )
        ]
    if intent.intent == "card.manage":
        return [
            PlanNode(
                id="resolve_card",
                kind="tool",
                tool_name="cards.resolve",
                depends_on=[],
                risk_level="green",
                description="按尾号解析目标银行卡",
            ),
            PlanNode(
                id="authorization_gate",
                kind="gate",
                tool_name=None,
                depends_on=["resolve_card"],
                risk_level="red",
                description="等待短信验证码强验证",
            ),
            PlanNode(
                id="update_card_status",
                kind="tool",
                tool_name="card.status.update",
                depends_on=["authorization_gate"],
                risk_level="red",
                description="更新卡片状态并写入审计",
            ),
        ]
    if intent.intent == "investment.recommend":
        return [
            PlanNode(
                id="load_risk_profile",
                kind="tool",
                tool_name="profile.get",
                depends_on=[],
                risk_level="green",
                description="读取已完成的客户风险评估",
            ),
            PlanNode(
                id="collect_preferences",
                kind="gate",
                tool_name=None,
                depends_on=["load_risk_profile"],
                risk_level="green",
                description="补充投资金额与持有期限",
            ),
            PlanNode(
                id="recommend_products",
                kind="tool",
                tool_name="investment.products.recommend",
                depends_on=["collect_preferences"],
                risk_level="green",
                description="在风险等级上限内匹配产品",
            ),
        ]
    if intent.intent == "occasion.plan":
        return [
            PlanNode(
                id="collect_occasion_details",
                kind="gate",
                tool_name=None,
                depends_on=[],
                risk_level="green",
                description="补充对象、日期和预算",
            ),
            PlanNode(
                id="check_budget",
                kind="tool",
                tool_name="budget.availability.check",
                depends_on=["collect_occasion_details"],
                risk_level="green",
                description="校验账户余额与其他任务资金预留",
            ),
            PlanNode(
                id="select_occasion_items",
                kind="tool",
                tool_name="occasion.catalog.search",
                depends_on=["collect_occasion_details"],
                risk_level="green",
                description="从白名单商户目录匹配鲜花和蛋糕",
            ),
            PlanNode(
                id="authorization_gate",
                kind="gate",
                tool_name=None,
                depends_on=["check_budget", "select_occasion_items"],
                risk_level="yellow",
                description="展示预算、商品和执行时间并等待明确确认",
            ),
            PlanNode(
                id="create_scheduled_task",
                kind="tool",
                tool_name="scheduled.task.create",
                depends_on=["authorization_gate"],
                risk_level="yellow",
                description="创建资金预留与可暂停的定时任务",
            ),
        ]
    if intent.intent == "transfer.create":
        return [
            PlanNode(
                id="resolve_account",
                kind="tool",
                tool_name="accounts.list",
                depends_on=[],
                risk_level="green",
                description="解析并校验付款账户",
            ),
            PlanNode(
                id="resolve_payee",
                kind="tool",
                tool_name="payees.search",
                depends_on=[],
                risk_level="green",
                description="解析收款人并在同名时暂停消歧",
            ),
            PlanNode(
                id="create_draft",
                kind="tool",
                tool_name="transfer.draft.create",
                depends_on=["resolve_account", "resolve_payee"],
                risk_level="yellow",
                description="创建不移动资金的转账草案",
            ),
            PlanNode(
                id="evaluate_policy",
                kind="tool",
                tool_name="transfer.policy.evaluate",
                depends_on=["create_draft"],
                risk_level="yellow",
                description="由服务器计算最终风险等级",
            ),
            PlanNode(
                id="authorization_gate",
                kind="gate",
                tool_name=None,
                depends_on=["evaluate_policy"],
                risk_level="red",
                description="等待用户确认或强认证",
            ),
            PlanNode(
                id="execute_transfer",
                kind="tool",
                tool_name="transfer.execute",
                depends_on=["authorization_gate"],
                risk_level="red",
                description="使用幂等键执行已授权转账",
            ),
        ]
    return [
        PlanNode(
            id="human_handoff",
            kind="gate",
            tool_name=None,
            depends_on=[],
            risk_level="red",
            description="未支持或低置信度意图转交人工",
        )
    ]


def validate_dag(nodes: list[PlanNode]) -> None:
    node_ids = {node.id for node in nodes}
    if len(node_ids) != len(nodes):
        raise ValueError("DAG contains duplicate node ids.")
    for node in nodes:
        if node.kind == "tool":
            if node.tool_name is None:
                raise ValueError(f"Tool node {node.id} has no tool name.")
            require_registered_tool(node.tool_name)
        elif node.tool_name is not None:
            raise ValueError(f"Gate node {node.id} cannot name a tool.")
        unknown = set(node.depends_on) - node_ids
        if unknown:
            raise ValueError(f"Node {node.id} has unknown dependencies: {sorted(unknown)}")

    remaining = {node.id: set(node.depends_on) for node in nodes}
    while remaining:
        ready = {node_id for node_id, deps in remaining.items() if not deps}
        if not ready:
            raise ValueError("DAG contains a cycle.")
        remaining = {
            node_id: deps - ready
            for node_id, deps in remaining.items()
            if node_id not in ready
        }


def hash_plan(plan: list[dict[str, object]]) -> str:
    canonical = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def verify_plan_hash(plan: list[dict[str, object]], expected_hash: str) -> bool:
    return hmac.compare_digest(hash_plan(plan), expected_hash)


def build_planning_graph(adapter: IntentAdapter):
    async def understand(state: PlanningState) -> dict[str, object]:
        intent = await adapter.classify(
            state["message"], state["memory"], state["user_id"]
        )
        return {
            "intent_data": intent.model_dump(mode="json"),
            "model_provider": adapter.provider_name,
        }

    def build_dag(state: PlanningState) -> dict[str, object]:
        intent = IntentEnvelope.model_validate(state["intent_data"])
        plan = [node.model_dump(mode="json") for node in plan_for_intent(intent)]
        return {"plan": plan}

    def validate(state: PlanningState) -> dict[str, object]:
        nodes = [PlanNode.model_validate(node) for node in state["plan"]]
        validate_dag(nodes)
        return {"plan_hash": hash_plan(state["plan"])}

    builder = StateGraph(PlanningState)
    builder.add_node("understand_intent", understand)
    builder.add_node("build_dag", build_dag)
    builder.add_node("validate_dag", validate)
    builder.add_edge(START, "understand_intent")
    builder.add_edge("understand_intent", "build_dag")
    builder.add_edge("build_dag", "validate_dag")
    builder.add_edge("validate_dag", END)
    return builder.compile()


async def generate_plan(
    message: str,
    memory: dict[str, object],
    user_id: str,
    adapter: IntentAdapter | None = None,
) -> PlanningState:
    selected_adapter = adapter or get_intent_adapter()
    graph = build_planning_graph(selected_adapter)
    return await graph.ainvoke(
        {"message": message, "memory": memory, "user_id": user_id}
    )
