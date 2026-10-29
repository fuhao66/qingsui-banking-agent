"use client";

import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CalendarClock,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDollarSign,
  CreditCard,
  DatabaseBackup,
  Fingerprint,
  FileImage,
  Gift,
  Handshake,
  Landmark,
  Link2,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  MessageCircleMore,
  Pause,
  PiggyBank,
  Play,
  ReceiptText,
  RotateCcw,
  Send,
  ShieldCheck,
  ShieldAlert,
  Sparkles,
  Trash2,
  Upload,
  UserRound,
  WalletCards,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { clearExperienceToken, createEvidenceRun, createRun, getAuditEvents, getExperienceProfile, getScheduledTasks, getSecurityStatus, loginExperience, logoutExperience, requestHandoff, resetDemoData, resumeRun, updateScheduledTask } from "@/lib/api";
import type {
  AgentPlanNode,
  AgentRun,
  AuditEvent,
  ChatMessage,
  PendingAction,
  RiskLevel,
  ScheduledTask,
  SecurityStatus,
} from "@/lib/types";

const PROMPTS = [
  { label: "查询总资产", message: "帮我查一下总资产", icon: WalletCards },
  { label: "分析 8 月账单", message: "分析一下2026年8月账单", icon: ReceiptText },
  { label: "年度账单", message: "生成2026年年度账单", icon: ReceiptText },
  { label: "取消自动续费", message: "帮我取消星幕视频的自动续费", icon: RotateCcw },
  { label: "续费提醒", message: "给星幕视频设置提前3天续费提醒", icon: CalendarClock },
  { label: "查看银行卡", message: "我名下有哪些银行卡", icon: CreditCard },
  { label: "冻结银行卡", message: "冻结尾号6688的银行卡", icon: LockKeyhole },
  { label: "申请虚拟卡", message: "申请一张虚拟银行卡", icon: CreditCard },
  { label: "调整单笔限额", message: "把尾号6688银行卡单笔限额调整为2000元", icon: ShieldCheck },
  { label: "推荐理财", message: "我有2万元，想稳健理财半年", icon: PiggyBank },
  { label: "申购理财", message: "申购稳盈90天1000元理财", icon: PiggyBank },
  { label: "查询持仓", message: "查询我的理财持仓", icon: Landmark },
  { label: "AA 收款", message: "发起4人聚餐AA收款共400元", icon: CircleDollarSign },
  { label: "定时转账", message: "2026年12月20日9点定时给13800002381转500元", icon: CalendarClock },
  { label: "扫描重要日子", message: "看看近期重要日子", icon: Gift },
  { label: "生日惊喜计划", message: "我爱人2026年11月20日生日，预算1000元，提前2天准备鲜花和蛋糕", icon: Gift },
  { label: "小额转账", message: "给小王转300元，备注AA", icon: CircleDollarSign },
  { label: "大额转账", message: "给妈妈转1200元", icon: Fingerprint },
  { label: "反诈攻防演示", message: "这可能是诈骗：客服说我的账户异常，让我立即转5000元到安全账户，不要告诉家人", icon: ShieldAlert },
];

const REQUIRE_INVITE = process.env.NEXT_PUBLIC_REQUIRE_INVITE === "true";

const STATUS_LABELS: Record<string, string> = {
  running: "执行中",
  waiting_clarification: "等待补充",
  waiting_confirmation: "等待确认",
  waiting_auth: "等待强验证",
  human_review: "人工接管",
  completed: "已完成",
  cancelled: "已取消",
  failed: "执行失败",
};

const INTENT_LABELS: Record<string, string> = {
  "account.balance": "资产查询",
  "bill.summary": "账单分析",
  "bill.annual": "年度报告",
  "subscription.list": "订阅查询",
  "subscription.cancel": "取消订阅",
  "subscription.reminder": "续费提醒",
  "transfer.create": "智能转账",
  "transfer.schedule": "定时转账",
  "collection.aa": "AA 收款",
  "card.list": "卡片查询",
  "card.manage": "卡片管理",
  "card.apply": "卡片申请",
  "card.limit": "限额调整",
  "card.restriction": "交易限制",
  "investment.recommend": "理财推荐",
  "investment.holdings": "理财持仓",
  "investment.subscribe": "理财申购",
  "investment.redeem": "理财赎回",
  "occasion.plan": "跨场景计划",
  "occasion.detect": "生活事件扫描",
  "fraud.assess": "Guardian 反诈评估",
  unsupported: "待人工识别",
};

const TOOL_LABELS: Record<string, string> = {
  "accounts.list": "读取账户余额",
  "bill.summary": "汇总账单数据",
  "bill.annual": "生成年度报告",
  "subscriptions.list": "查询订阅代扣",
  "subscriptions.search": "解析目标订阅",
  "subscription.cancel": "执行订阅取消",
  "subscription.reminder.create": "创建续费提醒",
  "cards.list": "读取脱敏卡片",
  "cards.resolve": "解析目标银行卡",
  "card.status.update": "更新卡片状态",
  "card.application.create": "申请沙箱卡片",
  "card.limit.update": "更新单笔限额",
  "card.restriction.update": "更新交易限制",
  "profile.get": "读取风险评估",
  "investment.products.recommend": "筛选理财产品",
  "investment.holdings.list": "查询理财持仓",
  "investment.subscribe": "执行理财申购",
  "investment.redeem": "执行理财赎回",
  "transfer.schedule": "创建定时转账",
  "collection.aa.create": "创建 AA 收款",
  "life.events.scan": "扫描生活事件",
  "occasion.catalog.search": "匹配可信商户",
  "budget.availability.check": "校验可用预算",
  "scheduled.task.create": "创建定时任务",
  "scheduled.task.status.update": "更新任务状态",
  "payees.search": "解析收款人",
  "transfer.draft.create": "创建转账草稿",
  "transfer.policy.evaluate": "执行安全策略",
  "transfer.confirm": "获取用户确认",
  "auth.challenge.verify": "完成强身份验证",
  "auth.operation.verify": "验证敏感操作",
  "transfer.execute": "执行银行转账",
  "guardian.risk.assess": "Guardian 独立风险复核",
};

const initialMessage: ChatMessage = {
  id: "welcome",
  role: "assistant",
  text: "你好，我是青穗银行智能体。你可以直接说想查什么或想办理什么；每一步操作都会经过权限策略校验。",
};

function riskOf(run: AgentRun | null): RiskLevel {
  if (!run) return "green";
  if (run.guardian?.effective_risk) return run.guardian.effective_risk;
  if (run.plan.some((node) => node.risk_level === "red")) return "red";
  if (run.plan.some((node) => node.risk_level === "yellow")) return "yellow";
  return "green";
}

function riskMeta(level: RiskLevel) {
  if (level === "red") return { label: "红色 · 强验证", short: "MFA", description: "资金或敏感操作，验证身份后执行" };
  if (level === "yellow") return { label: "黄色 · 用户确认", short: "确认", description: "涉及账户变更，明确确认后执行" };
  return { label: "绿色 · 自动执行", short: "只读", description: "查询类操作，不改变账户状态" };
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function shortId(value?: string | null) {
  return value ? value.slice(0, 8).toUpperCase() : "READY";
}

function nodeState(node: AgentPlanNode, run: AgentRun) {
  const step = run.steps.find((item) => item.node_id === node.id);
  if (step?.status === "completed") return "done";
  if (step?.status === "failed") return "failed";
  if (run.current_node_id === node.id) return "active";
  return "waiting";
}

function ResultSummary({ run }: { run: AgentRun }) {
  if (!run.result || run.status !== "completed") return null;
  const result = run.result;

  if (run.intent === "fraud.assess") {
    const assessment = result.fraud_assessment as Record<string, unknown> | undefined;
    return (
      <div className="result-card fraud-result">
        <div><span>Guardian 反诈分</span><strong>{String(assessment?.score ?? run.guardian?.scam_score ?? 0)}/100</strong></div>
        <small>仅分析证据，未执行任何资金操作</small>
      </div>
    );
  }

  if (run.intent === "account.balance") {
    const accountCount = Array.isArray(result.accounts) ? result.accounts.length : result.account_count;
    return (
      <div className="result-card balance-result">
        <span>账户总资产</span>
        <strong>¥ {String(result.total_balance ?? "—")}</strong>
        <small>{String(accountCount ?? "—")} 个账户 · 数据来自银行核心系统</small>
      </div>
    );
  }

  if (run.intent === "bill.summary") {
    return (
      <div className="result-card result-grid">
        <div><span>月份</span><b>{String(result.month ?? "—")}</b></div>
        <div><span>总支出</span><b>¥ {String(result.outflow ?? result.total_expense ?? result.total_spending ?? "—")}</b></div>
        <div><span>交易笔数</span><b>{String(result.transaction_count ?? "—")}</b></div>
      </div>
    );
  }

  if (run.intent === "bill.annual") {
    const months = Array.isArray(result.months) ? result.months as Array<Record<string, unknown>> : [];
    const maxOutflow = Math.max(...months.map((month) => Number(month.outflow || 0)), 1);
    return (
      <div className="result-card">
        <div className="result-grid">
          <div><span>年度</span><b>{String(result.year)} 年</b></div>
          <div><span>全年支出</span><b>¥ {String(result.outflow)}</b></div>
          <div><span>净现金流</span><b>¥ {String(result.net_cashflow)}</b></div>
        </div>
        <div className="annual-bars" aria-label="月度支出趋势">
          {months.map((month) => <span key={String(month.month)} title={`${String(month.month)} ¥${String(month.outflow)}`} style={{ height: `${Math.max(8, Number(month.outflow || 0) / maxOutflow * 54)}px` }} />)}
        </div>
      </div>
    );
  }

  if (run.intent === "subscription.list") {
    const subscriptionCount = Array.isArray(result.subscriptions) ? result.subscriptions.length : result.active_count;
    return (
      <div className="result-card result-grid">
        <div><span>有效订阅</span><b>{String(subscriptionCount ?? result.total ?? "—")} 项</b></div>
        <div><span>月度支出</span><b>¥ {String(result.monthly_equivalent ?? "—")}</b></div>
      </div>
    );
  }

  if (run.intent === "subscription.cancel") {
    return (
      <div className="result-card transfer-result">
        <CheckCircle2 size={20} />
        <div><span>订阅已取消</span><b>{String(result.merchant ?? "—")} · {String(result.product_name ?? "")}</b></div>
      </div>
    );
  }

  if (run.intent === "card.list") {
    const cards = Array.isArray(result.cards) ? result.cards as Array<Record<string, unknown>> : [];
    return (
      <div className="result-card card-result-list">
        {cards.map((card) => (
          <div className="bank-card-row" key={String(card.id)}>
            <span className="mini-card-icon"><CreditCard size={16} /></span>
            <div><b>{String(card.card_name)}</b><small>{String(card.masked_number)} · 日限额 ¥{String(card.daily_limit)}</small></div>
            <em className={`card-status ${String(card.status)}`}>{card.status === "active" ? "正常" : card.status === "locked" ? "已冻结" : "已挂失"}</em>
          </div>
        ))}
      </div>
    );
  }

  if (run.intent === "card.manage") {
    return (
      <div className="result-card transfer-result">
        <ShieldCheck size={20} />
        <div><span>卡片状态已更新</span><b>尾号 {String(result.last4 ?? "—")} · {result.status === "locked" ? "已冻结" : result.status === "lost" ? "已挂失" : "正常使用"}</b></div>
      </div>
    );
  }

  if (run.intent === "investment.recommend") {
    const products = Array.isArray(result.products) ? result.products as Array<Record<string, unknown>> : [];
    return (
      <div className="investment-results">
        <div className="investment-note"><ShieldCheck size={14} /><span>已按你的风险评估上限筛选，不会自动申购</span></div>
        {products.map((product) => (
          <div className="product-card" key={String(product.id)}>
            <div className="product-top"><b>{String(product.name)}</b><em className={`product-risk ${String(product.risk_level)}`}>{product.risk_level === "low" ? "低风险" : product.risk_level === "medium" ? "中风险" : "高风险"}</em></div>
            <div className="product-metrics">
              <span><small>业绩比较基准</small><strong>{String(product.expected_return_low)}% ~ {String(product.expected_return_high)}%</strong></span>
              <span><small>建议持有</small><b>{Number(product.term_months) === 0 ? "灵活" : `${String(product.term_months)} 个月`}</b></span>
            </div>
            <p>{String(product.description)}</p>
          </div>
        ))}
      </div>
    );
  }

  if (run.intent === "investment.holdings") {
    const holdings = Array.isArray(result.holdings) ? result.holdings as Array<Record<string, unknown>> : [];
    return <div className="investment-results">{holdings.length ? holdings.map((item) => <div className="product-card" key={String(item.holding_id)}><div className="product-top"><b>{String(item.product_name)}</b><em className="product-risk low">持有中</em></div><div className="product-metrics"><span><small>本金</small><strong>¥ {String(item.principal)}</strong></span><span><small>当前价值</small><b>¥ {String(item.current_value)}</b></span></div></div>) : <div className="investment-note">暂无有效持仓，可先体验理财申购。</div>}</div>;
  }

  if (run.intent === "occasion.detect") {
    const events = Array.isArray(result.life_events) ? result.life_events as Array<Record<string, unknown>> : [];
    return <div className="result-card card-result-list">{events.map((event) => <div className="bank-card-row" key={String(event.event_id)}><span className="mini-card-icon"><Gift size={16} /></span><div><b>{String(event.person)}的{String(event.event_type)}</b><small>{formatDateTime(String(event.event_date))} · 建议预算 ¥{String(event.default_budget)}</small></div></div>)}</div>;
  }

  if (["transfer.schedule", "collection.aa", "subscription.reminder", "card.apply", "card.limit", "card.restriction", "investment.subscribe", "investment.redeem"].includes(run.intent)) {
    return (
      <div className="result-card transfer-result">
        <CheckCircle2 size={20} />
        <div><span>{INTENT_LABELS[run.intent]}已完成</span><b>{String(result.product_name ?? result.merchant ?? result.recipient ?? result.card ?? result.masked_number ?? result.title ?? "业务状态已更新")}</b><small>操作编号 {String(result.operation_id ?? "—").slice(0, 8).toUpperCase()} · 全链路已审计</small></div>
      </div>
    );
  }

  if (run.intent === "occasion.plan") {
    return (
      <div className="result-card occasion-result">
        <span className="occasion-result-icon"><CalendarClock size={18} /></span>
        <div><span>跨场景任务已创建</span><b>{String(result.title ?? "生日准备计划")}</b><small>{formatDateTime(String(result.execute_at))} 执行 · 已预留 ¥{String(result.reserved_amount)}</small></div>
      </div>
    );
  }

  if (run.intent === "transfer.create") {
    return (
      <div className="result-card transfer-result">
        <CheckCircle2 size={20} />
        <div><span>转账已完成</span><b>回单号 {String(result.receipt_no ?? "已生成")}</b></div>
      </div>
    );
  }
  return null;
}

interface ActionCardProps {
  run: AgentRun;
  busy: boolean;
  onResume: (payload: Record<string, unknown>) => void;
  onHandoff: () => void;
}

function PendingActionCard({ run, busy, onResume, onHandoff }: ActionCardProps) {
  const action = run.pending_action as PendingAction | null;
  const [otp, setOtp] = useState("");
  const [clarification, setClarification] = useState("");
  if (!action) return null;

  if (action.type === "payee_disambiguation") {
    return (
      <div className="action-card">
        <div className="action-title"><UserRound size={17} /><b>确认收款人</b></div>
        <p>{action.prompt || "找到了多个匹配联系人，请选择。"}</p>
        <div className="payee-list">
          {action.options?.map((option) => (
            <button key={option.id} disabled={busy} onClick={() => onResume({ selected_payee_id: option.id })}>
              <span className="payee-avatar">{"name" in option ? option.name.slice(0, 1) : "订"}</span>
              <span>{"name" in option && <><b>{option.name}</b><small>{option.bank_name} · {option.account_masked}{option.alias ? ` · ${option.alias}` : ""}</small></>}</span>
              <ChevronRight size={16} />
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (action.type === "subscription_disambiguation") {
    return (
      <div className="action-card">
        <div className="action-title"><RotateCcw size={17} /><b>选择需要取消的订阅</b></div>
        <p>{action.prompt || "请选择一项订阅。"}</p>
        <div className="payee-list">
          {action.options?.map((option) => "merchant" in option && (
            <button key={option.id} disabled={busy} onClick={() => onResume({ selected_subscription_id: option.id })}>
              <span className="payee-avatar">{option.merchant.slice(0, 1)}</span>
              <span><b>{option.merchant}</b><small>{option.product_name} · ¥{String(option.amount)}/月</small></span>
              <ChevronRight size={16} />
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (action.type === "transfer_confirmation") {
    const details = action.details || {};
    return (
      <div className="action-card yellow-action">
        <div className="action-title"><ShieldCheck size={17} /><b>黄色权限确认</b><em>需要本人确认</em></div>
        <p>{action.prompt || "请核对转账信息。"}</p>
        <dl className="transfer-details">
          <div><dt>收款人</dt><dd>{details.payee || "—"}</dd></div>
          <div><dt>付款账户</dt><dd>{details.source_account || "—"}</dd></div>
          <div><dt>金额</dt><dd className="amount">¥ {String(details.amount ?? "—")}</dd></div>
        </dl>
        <div className="action-buttons">
          <button className="secondary-button" disabled={busy} onClick={() => onResume({ confirmed: false })}><X size={15} />取消</button>
          <button className="primary-button yellow-button" disabled={busy} onClick={() => onResume({ confirmed: true })}><Check size={15} />确认转账</button>
        </div>
      </div>
    );
  }

  if (action.type === "subscription_confirmation") {
    const details = action.details || {};
    return (
      <div className="action-card yellow-action">
        <div className="action-title"><ShieldCheck size={17} /><b>黄色权限确认</b><em>需要本人确认</em></div>
        <p>{action.prompt || "请确认是否取消订阅。"}</p>
        <dl className="transfer-details">
          <div><dt>服务平台</dt><dd>{String(details.merchant ?? "—")}</dd></div>
          <div><dt>订阅项目</dt><dd>{String(details.product_name ?? "—")}</dd></div>
          <div><dt>每月扣费</dt><dd className="amount">¥ {String(details.amount ?? "—")}</dd></div>
        </dl>
        <div className="action-buttons">
          <button className="secondary-button" disabled={busy} onClick={() => onResume({ confirmed: false })}><X size={15} />保留订阅</button>
          <button className="primary-button yellow-button" disabled={busy} onClick={() => onResume({ confirmed: true })}><Check size={15} />确认取消</button>
        </div>
      </div>
    );
  }

  if (action.type === "operation_confirmation") {
    const details = action.details || {};
    return (
      <div className="action-card yellow-action">
        <div className="action-title"><ShieldCheck size={17} /><b>黄色权限确认</b><em>需要本人确认</em></div>
        <p>{action.prompt || "请核对操作信息。"}</p>
        <dl className="transfer-details">
          {Object.entries(details).filter(([, value]) => value !== null && value !== undefined).slice(0, 5).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}
        </dl>
        <div className="action-buttons">
          <button className="secondary-button" disabled={busy} onClick={() => onResume({ confirmed: false })}><X size={15} />取消</button>
          <button className="primary-button yellow-button" disabled={busy} onClick={() => onResume({ confirmed: true })}><Check size={15} />确认执行</button>
        </div>
      </div>
    );
  }

  if (action.type === "occasion_confirmation") {
    const details = action.details || {};
    const items = Array.isArray(details.items) ? details.items as Array<Record<string, unknown>> : [];
    return (
      <div className="action-card yellow-action occasion-action">
        <div className="action-title"><CalendarClock size={17} /><b>跨场景计划确认</b><em>黄色权限</em></div>
        <p>{action.prompt || "请核对任务信息。"}</p>
        <dl className="transfer-details">
          <div><dt>准备对象</dt><dd>{String(details.person ?? "—")} · {String(details.occasion ?? "")}</dd></div>
          <div><dt>自动执行</dt><dd>{details.execute_at ? formatDateTime(String(details.execute_at)) : "—"}</dd></div>
          <div><dt>预算预留</dt><dd className="amount">¥ {String(details.budget ?? "—")}</dd></div>
        </dl>
        <div className="occasion-items">
          {items.map((item) => <span key={`${String(item.category)}-${String(item.merchant)}`}><b>{String(item.category)}</b>{String(item.item)} · ¥{String(item.estimated_amount)}</span>)}
        </div>
        <div className="action-buttons">
          <button className="secondary-button" disabled={busy} onClick={() => onResume({ confirmed: false })}><X size={15} />取消计划</button>
          <button className="primary-button yellow-button" disabled={busy} onClick={() => onResume({ confirmed: true })}><Check size={15} />确认并预留</button>
        </div>
      </div>
    );
  }

  if (action.type === "strong_authentication") {
    const details = action.details || {};
    const isCardAction = details.operation === "card_manage";
    const operationName = INTENT_LABELS[String(details.operation)] || "敏感业务操作";
    const target = isCardAction ? String(details.card ?? "—") : details.amount ? `¥ ${String(details.amount)}` : operationName;
    return (
      <div className="action-card red-action">
        <div className="action-title"><Fingerprint size={18} /><b>红色权限强验证</b><em>短信验证码</em></div>
        <p>{action.prompt || "该操作风险较高，请完成身份验证。"}</p>
        <div className="auth-amount">
          <span>{isCardAction ? "目标银行卡" : "待验证操作"}</span>
          <strong>{target}</strong>
        </div>
        <label className="otp-field">
          <span>6 位验证码</span>
          <input inputMode="numeric" maxLength={6} value={otp} onChange={(event) => setOtp(event.target.value.replace(/\D/g, ""))} placeholder="演示码 246810" />
        </label>
        <div className="action-buttons">
          <button className="secondary-button" disabled={busy} onClick={onHandoff}><Handshake size={15} />人工协助</button>
          <button className="primary-button red-button" disabled={busy || otp.length !== 6} onClick={() => onResume({ auth_code: otp })}><LockKeyhole size={15} />验证并执行</button>
        </div>
        <small className="demo-hint">演示环境固定验证码：246810</small>
      </div>
    );
  }

  if (action.type === "missing_slots") {
    return (
      <div className="action-card">
        <div className="action-title"><MessageCircleMore size={17} /><b>补充业务信息</b></div>
        <p>{action.prompt || "请补充缺失信息。"}</p>
        <form className="inline-clarify" onSubmit={(event) => { event.preventDefault(); if (clarification.trim()) onResume({ clarification_message: clarification.trim() }); }}>
          <input value={clarification} onChange={(event) => setClarification(event.target.value)} placeholder="例如：给小王转 300 元" />
          <button disabled={busy || !clarification.trim()}><ArrowRight size={16} /></button>
        </form>
      </div>
    );
  }

  if (action.type === "human_review") {
    return (
      <div className="action-card human-action">
        <div className="action-title"><Handshake size={17} /><b>已转人工复核</b><em>安全保护</em></div>
        <p>{action.prompt || "本次请求需要人工客服进一步确认。"}</p>
      </div>
    );
  }

  return null;
}

function RunTimeline({ run }: { run: AgentRun | null }) {
  if (!run) {
    return <div className="empty-dag"><Bot size={28} /><p>发送一条指令后，这里将展示智能体的任务拆解与执行状态。</p></div>;
  }
  return (
    <div className="timeline">
      {run.plan.map((node, index) => {
        const state = nodeState(node, run);
        return (
          <div className={`timeline-step ${state}`} key={node.id}>
            <span className="timeline-marker">
              {state === "done" ? <Check size={13} /> : state === "failed" ? <X size={13} /> : index + 1}
            </span>
            <div><b>{TOOL_LABELS[node.tool_name || ""] || node.description}</b><small>{node.description}</small></div>
            {state === "active" && <em>{run.status.startsWith("waiting") ? "已暂停" : "执行中"}</em>}
          </div>
        );
      })}
    </div>
  );
}

function GuardianPanel({ run }: { run: AgentRun | null }) {
  const guardian = run?.guardian;
  if (!guardian) return <p className="empty-audit">Guardian 将在高影响业务前独立复核。</p>;
  const labels = { allow: "放行", step_up: "动态提级", block: "已熔断" };
  return (
    <div className={`guardian-panel guardian-${guardian.disposition}`}>
      <div className="guardian-score">
        <span><ShieldAlert size={17} /> Guardian Agent</span>
        <strong>{guardian.scam_score}<small>/100</small></strong>
      </div>
      <div className="guardian-verdict"><b>{labels[guardian.disposition]}</b><span>{guardian.original_risk} → {guardian.effective_risk}</span></div>
      {guardian.signals.length > 0 && <div className="guardian-signals">{guardian.signals.slice(0, 4).map((signal) => <span key={signal.code}>{signal.label} +{signal.weight}</span>)}</div>}
      {guardian.counterfactual.without_signals && <p>{guardian.counterfactual.without_signals}</p>}
      <small className="receipt-hash"><Fingerprint size={11} /> 决策凭证 {guardian.receipt_hash ? shortId(guardian.receipt_hash) : "生成中"}</small>
    </div>
  );
}

function TaskCenter({ tasks, busy, onAction }: { tasks: ScheduledTask[]; busy: boolean; onAction: (task: ScheduledTask, action: "pause" | "resume" | "cancel") => void }) {
  const active = tasks.filter((task) => task.status !== "cancelled").slice(0, 3);
  return (
    <div className="task-center">
      <div className="section-title"><span>定时任务中心</span><span className="task-count">{active.length} ACTIVE</span></div>
      {active.length ? active.map((task) => (
        <div className={`scheduled-task ${task.status}`} key={task.id}>
          <span className="task-icon"><CalendarClock size={15} /></span>
          <div><b>{task.title}</b><small>{formatDateTime(task.execute_at)} · 预留 ¥{String(task.reserved_amount)}</small></div>
          <div className="task-actions">
            {task.status === "scheduled" ? <button disabled={busy} title="暂停" onClick={() => onAction(task, "pause")}><Pause size={11} /></button> : <button disabled={busy} title="恢复" onClick={() => onAction(task, "resume")}><Play size={11} /></button>}
            <button disabled={busy} title="取消并释放预算" onClick={() => onAction(task, "cancel")}><Trash2 size={11} /></button>
          </div>
        </div>
      )) : <p className="empty-audit">确认跨场景计划后，任务会显示在这里。</p>}
    </div>
  );
}

function AuditTrail({ events, chainValid }: { events: AuditEvent[]; chainValid: boolean }) {
  return (
    <div className="audit-block">
      <div className="section-title">
        <span>审计事件</span>
        <span className={`chain-chip ${chainValid ? "valid" : "invalid"}`}><Link2 size={11} />{chainValid ? "哈希链完整" : "链路异常"}</span>
      </div>
      {events.length ? (
        <div className="audit-list">
          {events.slice(0, 5).map((event) => (
            <div className="audit-event" key={event.id}>
              <span className={`audit-dot ${event.outcome}`} />
              <div><b>{event.action.replaceAll("_", " ")}</b><small>{event.resource_type} · {shortId(event.resource_id)}</small></div>
              <time>{formatTime(event.created_at)}</time>
            </div>
          ))}
        </div>
      ) : <p className="empty-audit">执行任务后将生成不可篡改审计记录。</p>}
    </div>
  );
}

function ExperienceLogin({ onAuthenticated }: { onAuthenticated: (displayName: string) => void }) {
  const [displayName, setDisplayName] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!displayName.trim() || !inviteCode.trim()) return;
    setSubmitting(true);
    setLoginError(null);
    try {
      const session = await loginExperience(inviteCode.trim(), displayName.trim());
      onAuthenticated(session.display_name);
    } catch (requestError) {
      setLoginError(requestError instanceof Error ? requestError.message : "邀请码登录失败。");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="experience-login-shell">
      <section className="experience-login-card">
        <span className="login-brand"><Landmark size={24} /></span>
        <p className="eyebrow">青穗银行 · 安全沙箱</p>
        <h1>体验 AI Banking Agent</h1>
        <p className="login-copy">每位访客会获得独立的演示账户，操作不会影响其他体验者，也不会连接真实资金。</p>
        <form onSubmit={submit}>
          <label><span>怎么称呼你</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} maxLength={40} placeholder="例如：王老师" autoComplete="name" /></label>
          <label><span>体验邀请码</span><input value={inviteCode} onChange={(event) => setInviteCode(event.target.value)} maxLength={128} placeholder="请输入邀请码" type="password" autoComplete="one-time-code" /></label>
          {loginError && <div className="login-error"><AlertTriangle size={14} />{loginError}</div>}
          <button disabled={submitting || !displayName.trim() || !inviteCode.trim()}>{submitting ? <LoaderCircle className="spin" size={17} /> : <ShieldCheck size={17} />}{submitting ? "正在创建独立沙箱…" : "进入安全体验"}</button>
        </form>
        <small>会话限时有效 · 请求限流 · 全链路审计</small>
      </section>
    </main>
  );
}

export default function AgentWorkbench() {
  const [authenticated, setAuthenticated] = useState(!REQUIRE_INVITE);
  const [authChecking, setAuthChecking] = useState(REQUIRE_INVITE);
  const [experienceName, setExperienceName] = useState("刘女士");
  const [messages, setMessages] = useState<ChatMessage[]>([initialMessage]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string>();
  const [activeRun, setActiveRun] = useState<AgentRun | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [chainValid, setChainValid] = useState(true);
  const [security, setSecurity] = useState<SecurityStatus | null>(null);
  const [scheduledTasks, setScheduledTasks] = useState<ScheduledTask[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [evidenceImage, setEvidenceImage] = useState<{ name: string; dataUrl: string } | null>(null);
  const conversationRef = useRef<HTMLDivElement>(null);
  const evidenceInputRef = useRef<HTMLInputElement>(null);

  const level = riskOf(activeRun);
  const risk = riskMeta(level);

  const refreshSafety = async () => {
    const [auditResult, securityResult, taskResult] = await Promise.allSettled([getAuditEvents(), getSecurityStatus(), getScheduledTasks()]);
    if (auditResult.status === "fulfilled") {
      setAuditEvents(auditResult.value.items);
      setChainValid(auditResult.value.chain_valid);
    }
    if (securityResult.status === "fulfilled") setSecurity(securityResult.value);
    if (taskResult.status === "fulfilled") setScheduledTasks(taskResult.value.items);
  };

  useEffect(() => {
    if (!REQUIRE_INVITE) return;
    getExperienceProfile()
      .then((profile) => {
        setExperienceName(profile.display_name);
        setAuthenticated(true);
      })
      .catch(() => {
        clearExperienceToken();
        setAuthenticated(false);
      })
      .finally(() => setAuthChecking(false));
  }, []);

  useEffect(() => {
    if (authenticated) refreshSafety();
  }, [authenticated]);

  useEffect(() => {
    conversationRef.current?.scrollTo({ top: conversationRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const updateRunMessage = (run: AgentRun) => {
    setActiveRun(run);
    setConversationId(run.conversation_id);
    setMessages((current) => {
      const existing = current.findIndex((message) => message.run?.id === run.id);
      const nextMessage: ChatMessage = {
        id: `assistant-${run.id}`,
        role: "assistant",
        text: run.response_text || STATUS_LABELS[run.status] || "任务状态已更新。",
        run,
      };
      if (existing === -1) return [...current, nextMessage];
      return current.map((message, index) => index === existing ? nextMessage : message);
    });
  };

  const submitMessage = async (message: string) => {
    const text = message.trim();
    if (!text || busy) return;
    setError(null);
    setNotice(null);
    setInput("");
    setMessages((current) => [...current, { id: `user-${Date.now()}`, role: "user", text }]);
    setBusy(true);
    try {
      const run = evidenceImage
        ? await createEvidenceRun(text, undefined, evidenceImage.dataUrl, conversationId)
        : await createRun(text, conversationId);
      updateRunMessage(run);
      setEvidenceImage(null);
      await refreshSafety();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "无法连接 Agent API，请确认后端已启动。");
    } finally {
      setBusy(false);
    }
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    submitMessage(input);
  };

  const handleEvidenceImage = (file?: File) => {
    if (!file) return;
    if (![/image\/png/, /image\/jpeg/, /image\/webp/].some((pattern) => pattern.test(file.type))) {
      setError("只能上传 PNG、JPEG 或 WebP 图片。");
      return;
    }
    if (file.size > 4 * 1024 * 1024) {
      setError("证据图片不能超过 4 MB。");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setEvidenceImage({ name: file.name, dataUrl: String(reader.result) });
    reader.readAsDataURL(file);
  };

  const handleResume = async (payload: Record<string, unknown>) => {
    if (!activeRun || busy) return;
    setError(null);
    setBusy(true);
    try {
      const run = await resumeRun(activeRun.id, payload);
      updateRunMessage(run);
      await refreshSafety();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "恢复任务失败，请重试。");
      await refreshSafety();
    } finally {
      setBusy(false);
    }
  };

  const handleHandoff = async () => {
    if (!activeRun || busy) return;
    setBusy(true);
    try {
      const run = await requestHandoff(activeRun.id, "用户在强验证环节请求人工协助");
      updateRunMessage(run);
      await refreshSafety();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "人工接管请求失败。");
    } finally {
      setBusy(false);
    }
  };

  const resetConversation = () => {
    setMessages([initialMessage]);
    setConversationId(undefined);
    setActiveRun(null);
    setError(null);
    setInput("");
    setEvidenceImage(null);
  };

  const handleDemoReset = async () => {
    if (busy || !window.confirm("确定恢复全部演示数据吗？当前会话、转账、卡片和订阅状态都会回到初始值。")) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await resetDemoData();
      resetConversation();
      setNotice("演示数据已恢复，可以从任意场景重新开始。重置操作已写入审计日志。");
      await refreshSafety();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "演示数据重置失败。");
    } finally {
      setBusy(false);
    }
  };

  const handleTaskAction = async (task: ScheduledTask, action: "pause" | "resume" | "cancel") => {
    const labels = { pause: "暂停", resume: "恢复", cancel: "取消并释放预算" };
    if (busy || !window.confirm(`确认${labels[action]}“${task.title}”吗？`)) return;
    setBusy(true);
    setError(null);
    try {
      await updateScheduledTask(task.id, action);
      setNotice(`任务已${labels[action]}，操作已写入审计日志。`);
      await refreshSafety();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "任务状态更新失败。");
    } finally {
      setBusy(false);
    }
  };

  const handleLogout = async () => {
    await logoutExperience();
    resetConversation();
    setScheduledTasks([]);
    setAuditEvents([]);
    setAuthenticated(false);
  };

  const completedNodes = useMemo(() => activeRun?.steps.filter((step) => step.status === "completed").length || 0, [activeRun]);

  if (authChecking) return <main className="experience-login-shell"><LoaderCircle className="spin" size={28} /></main>;
  if (!authenticated) return <ExperienceLogin onAuthenticated={(name) => { setExperienceName(name); setAuthenticated(true); }} />;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark"><Landmark size={19} /></span>
          <strong>青穗银行</strong>
          <span className="brand-divider" />
          <span className="brand-product">AI Banking Agent</span>
        </div>
        <div className="topbar-actions">
          <span className={`api-badge ${error ? "offline" : ""}`}><span className="status-dot" />{error ? "API 待连接" : "安全沙箱"}</span>
          <button className="reset-button demo-reset-button" disabled={busy} onClick={handleDemoReset}><DatabaseBackup size={14} />重置数据</button>
          <button className="reset-button" disabled={busy} onClick={resetConversation}><RotateCcw size={14} />新会话</button>
          {REQUIRE_INVITE && <button className="reset-button" disabled={busy} onClick={handleLogout}><LogOut size={14} />退出</button>}
          <div className="avatar" aria-label={`演示用户${experienceName}`}>{experienceName.slice(0, 1)}</div>
        </div>
      </header>

      <section className="workspace">
        <aside className="nav-rail" aria-label="主要导航">
          <button className="nav-item active" aria-label="AI 助手"><Sparkles size={21} /></button>
          <button className="nav-item" aria-label="账户"><WalletCards size={21} /></button>
          <button className="nav-item" aria-label="账单"><ReceiptText size={21} /></button>
          <button className="nav-item" aria-label="安全中心"><ShieldCheck size={21} /></button>
          <span className="nav-spacer" />
          <button className="nav-item" aria-label="安全锁定"><LockKeyhole size={20} /></button>
        </aside>

        <section className="assistant-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">银行业务，一句话办好</p><h1>你好，{experienceName}</h1></div>
            <span className="private-chip"><ShieldCheck size={14} />会话已加密</span>
          </div>

          <div className="prompt-gallery" aria-label="演示指令">
            {PROMPTS.map(({ label, message, icon: Icon }) => (
              <button key={label} disabled={busy} onClick={() => submitMessage(message)}><Icon size={15} /><span>{label}</span></button>
            ))}
          </div>

          <div className="conversation" ref={conversationRef} aria-live="polite">
            {messages.map((message) => (
              message.role === "user" ? (
                <div className="message user-message" key={message.id}>{message.text}</div>
              ) : (
                <div className="agent-row" key={message.id}>
                  <span className="agent-avatar"><Sparkles size={16} /></span>
                  <div className="message agent-message">
                    <p>{message.text}</p>
                    {message.run && <ResultSummary run={message.run} />}
                    {message.run && message.run.id === activeRun?.id && (
                      <PendingActionCard run={message.run} busy={busy} onResume={handleResume} onHandoff={handleHandoff} />
                    )}
                    {message.run && <small className="message-meta">{STATUS_LABELS[message.run.status]} · {INTENT_LABELS[message.run.intent] || message.run.intent} · {formatTime(message.run.updated_at)}</small>}
                  </div>
                </div>
              )
            ))}
            {busy && (
              <div className="agent-row typing-row"><span className="agent-avatar"><Sparkles size={16} /></span><div className="typing"><i /><i /><i /></div></div>
            )}
          </div>

          {error && <div className="error-banner"><AlertTriangle size={15} /><span>{error}</span><button onClick={() => setError(null)} aria-label="关闭错误"><X size={14} /></button></div>}
          {notice && <div className="notice-banner"><CheckCircle2 size={15} /><span>{notice}</span><button onClick={() => setNotice(null)} aria-label="关闭提示"><X size={14} /></button></div>}

          {evidenceImage && <div className="evidence-chip"><FileImage size={14} /><span>{evidenceImage.name}</span><b>Guardian 视觉证据</b><button type="button" onClick={() => setEvidenceImage(null)}><X size={13} /></button></div>}
          <form className="composer" onSubmit={handleSubmit}>
            <MessageCircleMore size={20} />
            <input value={input} onChange={(event) => setInput(event.target.value)} disabled={busy} aria-label="向银行智能体发送消息" placeholder="例如：给小王转 300 元，备注 AA…" />
            <input ref={evidenceInputRef} className="evidence-input" type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => handleEvidenceImage(event.target.files?.[0])} />
            <button className="upload-button" type="button" disabled={busy} title="上传聊天截图作为反诈证据" onClick={() => evidenceInputRef.current?.click()}><Upload size={17} /></button>
            <button type="submit" disabled={busy || !input.trim()} aria-label="发送">{busy ? <LoaderCircle className="spin" size={18} /> : <Send size={18} />}</button>
          </form>
          <p className="disclaimer">演示环境 · Agent 不直接持有资金权限，所有操作均由策略引擎独立裁决</p>
        </section>

        <aside className="cockpit-panel">
          <div className="cockpit-heading">
            <div><p className="eyebrow">实时安全驾驶舱</p><h2>任务执行链路</h2></div>
            <span className="run-id">RUN-{shortId(activeRun?.id)}</span>
          </div>

          <section className={`risk-card risk-${level}`}>
            <span className="risk-icon">{level === "red" ? <Fingerprint size={21} /> : level === "yellow" ? <AlertTriangle size={21} /> : <ShieldCheck size={21} />}</span>
            <div><span>当前权限等级</span><strong>{risk.label}</strong><small>{risk.description}</small></div>
            <b>{risk.short}</b>
          </section>

          <section className="cockpit-section dag-section">
            <div className="section-title">
              <span>任务 DAG</span>
              <span className="live-label"><i />{activeRun ? `${completedNodes}/${activeRun.plan.length}` : "READY"}</span>
            </div>
            <RunTimeline run={activeRun} />
          </section>

          <section className="cockpit-section compact decision-section">
            <div className="section-title"><span>策略决策</span><ShieldCheck size={15} /></div>
            <dl className="decision-list">
              <div><dt>业务意图</dt><dd>{activeRun ? INTENT_LABELS[activeRun.intent] || activeRun.intent : "等待指令"}</dd></div>
              <div><dt>运行状态</dt><dd className={`status-${activeRun?.status || "ready"}`}>{activeRun ? STATUS_LABELS[activeRun.status] : "就绪"}</dd></div>
              <div><dt>模型来源</dt><dd>{activeRun?.model_provider || "Deterministic"}</dd></div>
              <div><dt>置信度</dt><dd>{activeRun ? `${Math.round(Number(activeRun.confidence) * 100)}%` : "—"}</dd></div>
              <div><dt>计划哈希</dt><dd className="mono">{activeRun ? shortId(activeRun.plan_hash) : "—"}</dd></div>
            </dl>
          </section>

          <section className="cockpit-section guardian-section">
            <div className="section-title"><span>双 Agent 制衡</span><span className="live-label"><i />INDEPENDENT</span></div>
            <GuardianPanel run={activeRun} />
          </section>

          <section className="cockpit-section task-center-section">
            <TaskCenter tasks={scheduledTasks} busy={busy} onAction={handleTaskAction} />
          </section>

          <section className="cockpit-section audit-section">
            <AuditTrail events={auditEvents} chainValid={chainValid} />
          </section>

          <section className="system-strip">
            <span><i />Agent API</span>
            <span className={chainValid ? "" : "system-alert"}><i />审计{chainValid ? "正常" : "异常"}</span>
            <span className={security?.locked ? "system-alert" : ""}><i />{security?.locked ? "账户锁定" : "风控在线"}</span>
          </section>
        </aside>
      </section>
    </main>
  );
}
