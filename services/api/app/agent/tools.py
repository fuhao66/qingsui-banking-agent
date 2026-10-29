from dataclasses import dataclass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    risk_level: str
    side_effect: bool
    description: str


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition("accounts.list", "green", False, "查询当前用户账户与余额"),
    ToolDefinition("guardian.risk.assess", "green", False, "独立审查诈骗、注入与行为风险"),
    ToolDefinition("bill.summary", "green", False, "从账本计算指定月份账单"),
    ToolDefinition("bill.annual", "green", False, "从账本聚合年度报告"),
    ToolDefinition("subscriptions.list", "green", False, "查询识别出的活跃订阅"),
    ToolDefinition("subscriptions.search", "green", False, "在当前用户订阅中解析目标"),
    ToolDefinition("subscription.cancel", "yellow", True, "取消用户明确确认的订阅"),
    ToolDefinition("subscription.reminder.create", "yellow", True, "创建续费提醒"),
    ToolDefinition("cards.list", "green", False, "查询当前用户的脱敏银行卡"),
    ToolDefinition("cards.resolve", "green", False, "按尾号解析当前用户银行卡"),
    ToolDefinition("card.status.update", "red", True, "强验证后变更卡片状态"),
    ToolDefinition("card.application.create", "red", True, "强验证后申请沙箱卡"),
    ToolDefinition("card.limit.update", "red", True, "强验证后调整单笔限额"),
    ToolDefinition("card.restriction.update", "red", True, "强验证后调整线上交易权限"),
    ToolDefinition("auth.operation.create", "red", True, "创建敏感操作强认证挑战"),
    ToolDefinition("auth.operation.verify", "red", True, "验证敏感操作认证挑战"),
    ToolDefinition("profile.get", "green", False, "读取用户风险评估等级"),
    ToolDefinition("investment.products.recommend", "green", False, "按风险与期限筛选产品"),
    ToolDefinition("investment.holdings.list", "green", False, "查询理财持仓"),
    ToolDefinition("investment.subscribe", "red", True, "强验证后模拟申购"),
    ToolDefinition("investment.redeem", "red", True, "强验证后模拟赎回"),
    ToolDefinition("transfer.schedule", "red", True, "授权后创建定时转账"),
    ToolDefinition("collection.aa.create", "yellow", True, "确认后创建 AA 收款"),
    ToolDefinition("life.events.scan", "green", False, "扫描可信生活事件"),
    ToolDefinition("occasion.catalog.search", "green", False, "从可信商户目录匹配鲜花与蛋糕"),
    ToolDefinition("budget.availability.check", "green", False, "检查余额与已有资金预留"),
    ToolDefinition("scheduled.task.create", "yellow", True, "确认后创建预算预留与定时任务"),
    ToolDefinition("scheduled.task.status.update", "yellow", True, "暂停、恢复或取消定时任务"),
    ToolDefinition("payees.search", "green", False, "搜索当前用户的收款人"),
    ToolDefinition("transfer.draft.create", "yellow", True, "创建无资金权限的转账草案"),
    ToolDefinition("transfer.policy.evaluate", "yellow", True, "执行服务器权限判定"),
    ToolDefinition("transfer.confirm", "yellow", True, "记录用户显式确认"),
    ToolDefinition("auth.challenge.create", "red", True, "创建强认证挑战"),
    ToolDefinition("auth.challenge.verify", "red", True, "验证强认证挑战"),
    ToolDefinition("transfer.execute", "red", True, "执行已获授权的幂等转账"),
)
TOOL_REGISTRY = {tool.name: tool for tool in TOOL_DEFINITIONS}


def require_registered_tool(name: str) -> ToolDefinition:
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        raise ValueError(f"Tool is not registered: {name}")
    return tool
