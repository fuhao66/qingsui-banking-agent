# 第六阶段：LLM 理解、动态补槽与扩展银行场景

## 阶段目标

把固定范围的规则型演示升级为“LLM 负责理解，服务端负责规划与授权”的受控 Agent，并增加卡片管理、订阅取消和理财推荐。系统仍能在没有外部密钥或网络的答辩环境中稳定运行。

## 关键架构

```text
自由自然语言
  → Prompt 注入检查
  → OpenAI Responses API 严格 JSON Schema，或 Qwen Chat JSON 意图/槽位
      └─ 无密钥或调用失败：确定性适配器安全回退
  → 服务端从意图白名单生成 DAG
  → 工具注册表、依赖、环路与计划哈希校验
  → 缺失槽位暂停并追问
  → 绿色查询 / 黄色确认 / 红色强验证
  → 受控业务服务执行并写入哈希审计链
```

模型只允许输出 `intent`、`confidence`、`slots` 和 `missing_slots`。模型不能输出最终权限等级，不能直接选择任意工具，也不能访问数据库。服务端仅为以下白名单意图生成计划：

- `account.balance`
- `bill.summary`
- `subscription.list`
- `subscription.cancel`
- `transfer.create`
- `card.list`
- `card.manage`
- `investment.recommend`

## 动态槽位补全

当金额、期限、银行卡尾号、订阅平台或转账信息不完整时，运行状态变为 `waiting_clarification`。服务端持久化原始计划与已有槽位，用户补充信息后重新进行结构化理解，并只合并与当前意图一致的槽位。补充内容如果试图覆盖指令或绕过权限，会转交人工。

示例：

```text
用户：帮我推荐理财产品
Agent：请补充投资金额和预计持有期限。
用户：2 万元，半年内不用，偏稳健
Agent：根据已存的 balanced 风险评估筛选低/中风险产品。
```

## 新增业务

### 卡片管理

- “我名下有哪些银行卡”：绿色查询，仅返回脱敏卡号。
- “冻结尾号 6688 的银行卡”：红色操作，必须完成短信 OTP。
- 同一流程支持 `lock`、`unlock` 和 `report_lost`。
- 通用敏感操作认证挑战独立持久化，连续失败复用全局熔断策略。

### 订阅取消

- 支持按商户或会员名称解析目标订阅。
- 多个候选时暂停并让用户选择。
- 取消属于黄色操作，页面展示平台、产品与月费，明确确认后才更新状态。

### 理财推荐

- 必须取得投资金额和持有期限。
- 读取银行保存的客户风险评估等级，并将用户临时偏好作为更严格的上限。
- 仅推荐金额、期限和风险等级都匹配的产品。
- 返回收益区间、期限、流动性与风险等级；不会自动申购。

## LLM 配置

### OpenAI

在根目录 `.env` 中配置：

```dotenv
AGENT_MODEL_PROVIDER=auto
OPENAI_API_KEY=你的服务端密钥
OPENAI_MODEL=gpt-5-mini
```

密钥只由 FastAPI 服务读取，不会进入浏览器。`auto` 模式在存在密钥时优先使用 OpenAI Responses API；如果调用超时、接口异常或结构化输出校验失败，会标记为 `deterministic_fallback` 并使用本地适配器完成本次理解。

实现遵循 OpenAI Responses API 的 Structured Outputs 方式，使用严格 JSON Schema、`store=false`、限制输出长度，并对用户标识进行哈希后作为安全标识发送。参考：[OpenAI Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)。

### 通义千问（阿里云百炼）

在根目录 `.env` 中配置：

```dotenv
AGENT_MODEL_PROVIDER=qwen
DASHSCOPE_API_KEY=你的百炼服务端密钥
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus
```

千问适配器调用百炼 OpenAI 兼容 Chat API，并请求 `json_object` 输出；返回内容仍须通过与 OpenAI 通道完全相同的 `IntentEnvelope` 校验。密钥、完整账户数据和银行工具均不会进入模型上下文。百炼现有公共域名仍可使用，正式部署可替换为业务空间专属域名。参考：[阿里云百炼 OpenAI 兼容 Chat API](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)。

`auto` 的优先级为 OpenAI → Qwen → 确定性适配器。为避免答辩环境中旧密钥抢占，使用千问时建议显式设置 `AGENT_MODEL_PROVIDER=qwen`。任一在线模型超时、接口失败、空响应或结构校验失败，都会标记为 `deterministic_fallback` 并安全降级。

## 推荐演示顺序

1. 输入“帮我推荐理财产品”，再补充“2 万元，半年内不用，偏稳健”，展示动态补槽。
2. 输入“把星幕视频会员停掉”，确认黄色取消卡片。
3. 输入“请暂停尾号 6688 这张银行卡的交易”，输入演示验证码 `246810`。
4. 输入“给小王转 300 元”，展示同名消歧与黄色转账确认。
5. 指向右侧模型来源、DAG、计划哈希和审计哈希链，说明 LLM 与授权执行的隔离边界。

## 验收标准

- 新旧 Agent 测试全部通过。
- Alembic `0004` 可升级、降级并再次升级。
- 自由表达的理财请求可暂停补槽并返回匹配产品。
- 订阅取消必须经过明确确认。
- 卡片冻结必须经过 OTP，验证码不出现在运行步骤中。
- 所有新增关键操作进入审计哈希链。
- Web 通过 ESLint、TypeScript 和 Next.js 生产构建。
