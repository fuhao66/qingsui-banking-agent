# 青穗银行 AI Banking Agent

面向金融科技竞赛的银行 AI 智能体。系统采用“模型理解与规划、规则引擎授权、银行后端执行”的分层架构，目标是让自然语言银行业务既流畅又可验证。

> 本项目仅用于竞赛演示和安全研究，全部账户、资金、验证码和交易均为沙箱数据，不连接真实银行系统。

## 快速导航

- [本地与公网部署说明](docs/deployment.md)
- [测试与自动化评测说明](docs/testing.md)
- [系统架构](docs/architecture.md)
- [安全说明与漏洞报告](SECURITY.md)
- [PWA 与飞书接入](docs/stage-11-pwa-and-feishu-channel.md)

## 当前状态：获奖能力强化版

- 可交互 Web 工作台：真实对话、预置指令、任务状态与响应式布局
- FastAPI 服务：账户、账单、联系人、订阅、银行卡、理财产品和转账草案
- PostgreSQL、Redis 与 Docker Compose 本地环境
- SQLAlchemy 银行业务、安全、Agent 持久化模型与七版 Alembic 迁移
- 连续 12 个月的确定性演示数据和异常交易样本
- 绿色自动、黄色确认、红色强验证的确定性权限策略
- 短信验证码模拟、连续失败熔断、幂等资金执行与哈希审计链
- LangGraph 结构化意图规划、白名单 DAG、持久化暂停恢复和人工接管
- 会话上下文支持省略表达，例如“再给她转 50 元”
- 收款人消歧、黄色确认、红色验证码、人工接管的页面内完整闭环
- 实时任务 DAG、风险等级、策略决策与哈希审计链驾驶舱
- Banker Agent 与 Guardian Agent 独立制衡，可放行、动态提级或在副作用前熔断
- 通义千问视觉模型聊天截图证据提取，图片内容始终按不可信数据处理
- 基于诈骗话术、历史金额基线、陌生收款人和注入信号的可解释反诈分
- 实时 DAG 重路由、反事实解释与 SHA-256 决策凭证，可直接用于答辩攻防演示
- OpenAI Responses API 与通义千问双模型适配，可用时启用、失败时安全回退
- 动态槽位追问与合并，不完整请求可跨 HTTP 请求继续办理
- 卡片查询与冻结/解锁/挂失、订阅取消、风险约束理财推荐
- 手机号与定时转账、AA 收款、年度账单趋势报告
- 卡片申请、单笔限额和线上交易限制，订阅续费提醒
- 理财模拟申购、持仓查询与赎回（全程强验证和沙箱资金记账）
- 已授权生活事件扫描，可衔接生日跨场景任务
- 生日场景跨业务 DAG、预算预留、可信商户匹配与定时任务中心
- 定时任务暂停、恢复、取消、预算释放与哈希链审计
- 邀请码登录、短期 Bearer 会话、请求限流与多体验用户数据隔离
- 当前用户独立重置、管理员体验统计、Caddy 自动 HTTPS 公网部署
- 可安装 PWA 移动端入口，支持手机桌面启动与基础离线壳
- 飞书 IM 事件回调、Token/签名校验、消息幂等、用户沙箱映射与对话续接
- 黄色/红色 IM 操作强制跳转短时签名安全页确认，避免在聊天窗口直接执行
- 61 条意图、槽位、权限、Guardian 反诈与提示注入自动化评测集及 JSON 报告
- 开发环境一键恢复账户、卡片、订阅、转账与审计演示数据
- 第一至第八阶段架构、验收和安全自评说明
- 公网体验部署、安全配置和服务器上线说明

## 本地启动

复制并按需修改 `.env.example` 为 `.env`。`.env` 被 Git 忽略，不会随仓库上传。示例口令只适用于本地沙箱，不能用于公网或生产环境。

Windows 本地开发推荐使用一键脚本。它会自动迁移 SQLite 演示库、写入种子数据，并将 Web 和新版 API 固定启动在 `3000/8000` 端口：

```powershell
.\scripts\start-demo.ps1
```

停止演示服务：

```powershell
.\scripts\stop-demo.ps1
```

运行离线评测或 Qwen 实模评测：

```powershell
.\scripts\run-evals.ps1 -Provider deterministic
.\scripts\run-evals.ps1 -Provider qwen
```

报告生成在 `data/eval-report-<provider>.json`。评测不会执行业务工具或改变账户数据，会验证意图、槽位、权限风险、Guardian 裁决、提示注入拦截和工具白名单。

完整的依赖安装、后端测试、前端构建和 CI 说明见 [测试与自动化评测说明](docs/testing.md)。

## 公网体验部署

没有服务器时，可让本机持续在线并启动临时 HTTPS 隧道：

```powershell
.\scripts\start-public-tunnel.ps1
.\scripts\stop-public-tunnel.ps1
```

启动后终端会显示临时公网地址和邀请码。详细限制见 [本机公网体验隧道](docs/local-public-tunnel.md)。

需要固定域名和长期稳定运行时，再使用下面的 Docker 服务器方案。

复制 `.env.public.example` 为 `.env.public`，填写真实域名、随机邀请码、管理员令牌、数据库密码、HMAC 密钥和 Qwen Key，然后运行：

```powershell
.\scripts\deploy-public.ps1 -ValidateOnly
.\scripts\deploy-public.ps1
```

公网模式会强制邀请码登录并为每位访客创建独立沙箱。完整步骤见 [公网体验部署文档](docs/stage-9-public-experience-deployment.md)。

本地、临时公网隧道、固定域名 Docker 部署的统一操作步骤见 [部署说明](docs/deployment.md)。

手机浏览器打开 HTTPS 地址后可使用“添加到主屏幕”安装为 PWA。飞书应用接入需要配置回调地址
`https://你的域名/api/v1/channels/feishu/events`，并在环境变量中填写飞书验证 Token、Encrypt Key、App ID 与 App Secret。
绿色查询可直接在 IM 返回结果；黄色、红色操作只返回十分钟有效的签名安全链接，并在 PWA 页面完成确认或强验证。
完整配置与验收步骤见 [多渠道接入说明](docs/stage-11-pwa-and-feishu-channel.md)。

演示数据库与进程日志保存在被 Git 忽略的 `data/` 目录。启动脚本不会终止其他程序；若端口被占用，会明确提示先处理占用进程。

也可以使用 Docker：

```powershell
docker compose up --build
```

启动后访问：

- Web：<http://localhost:3000>
- API 文档：<http://localhost:8000/docs>
- API 存活检查：<http://localhost:8000/health/live>
- API 就绪检查：<http://localhost:8000/health/ready>
- 账户接口：<http://localhost:8000/api/v1/accounts>
- 2026 年 8 月账单：<http://localhost:8000/api/v1/bill-summary?month=2026-08>
- 2026 年年度报告：<http://localhost:8000/api/v1/annual-report?year=2026>
- 收款人消歧：<http://localhost:8000/api/v1/payees/search?q=小王>
- 银行卡：<http://localhost:8000/api/v1/cards>
- 理财产品：<http://localhost:8000/api/v1/investment-products>
- 理财持仓：<http://localhost:8000/api/v1/investment-holdings>
- 生活事件：<http://localhost:8000/api/v1/life-events>
- 沙箱业务操作：<http://localhost:8000/api/v1/business-operations>
- 权限矩阵：<http://localhost:8000/api/v1/security/policy-matrix>
- 安全状态：<http://localhost:8000/api/v1/security/status>
- 审计事件：<http://localhost:8000/api/v1/security/audit-events>
- Agent 工具清单：<http://localhost:8000/api/v1/agent/tools>
- Agent 运行入口：`POST http://localhost:8000/api/v1/agent/runs`
- 定时任务中心：<http://localhost:8000/api/v1/scheduled-tasks>

## 不使用 Docker 的开发方式

前端使用 pnpm，后端要求 Python 3.12+。

```powershell
pnpm install
pnpm dev:web
```

```powershell
cd services/api
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## 目录

```text
apps/web/          Next.js 用户界面与安全驾驶舱
services/api/      FastAPI 业务与 Agent API
docs/              架构、验收和后续设计文档
.github/workflows/ GitHub Actions 自动测试与构建
docker-compose.yml 本地完整运行环境
```

Web 工作台已与 Agent API 全面联动。推荐现场依次演示“推荐理财”“取消自动续费”“冻结银行卡”和“小额转账”，即可展示动态补槽、绿黄红权限与跨业务白名单规划；详细步骤见 `docs/stage-6-llm-and-extended-scenarios.md`。

本地沙箱短信验证码默认为 `246810`，仅用于比赛演示与自动测试。生产环境必须替换为银行认证服务，并覆盖 `SECURITY_HMAC_SECRET` 与验证码配置。

Agent 支持 OpenAI、通义千问和离线确定性适配器。`auto` 模式会优先使用已配置的 OpenAI，再尝试通义千问；答辩使用千问时建议显式设置 `AGENT_MODEL_PROVIDER=qwen`。未配置密钥或模型调用失败时，系统会自动使用确定性中文适配器，保证离线演示稳定。无论使用哪个模型，模型都不能获得银行工具，工具选择、风险判定和执行授权始终由服务端控制。具体配置和演示步骤见 `docs/stage-6-llm-and-extended-scenarios.md`。
