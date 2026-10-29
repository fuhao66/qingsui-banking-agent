# 测试与自动化评测说明

项目提供单元与接口测试、Agent 自动化评测、前端静态检查和生产构建验证。测试默认使用隔离的 SQLite 沙箱，不连接真实银行系统，也不会执行真实资金操作。

## 1. 后端测试

安装开发依赖：

```powershell
cd services/api
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

运行全部测试：

```powershell
python -m pytest -q
```

运行重点模块：

```powershell
python -m pytest tests/test_security_flow.py -q
python -m pytest tests/test_agent_runtime.py -q
python -m pytest tests/test_guardian_agent.py -q
python -m pytest tests/test_multichannel.py -q
python -m pytest tests/test_complete_scenarios.py -q
```

主要覆盖范围：

- 余额、账单、银行卡、订阅、理财和转账接口
- 动态槽位补全、联系人消歧和跨轮会话恢复
- 白名单 DAG、工具参数校验和意图切换
- 绿黄红权限、确认、验证码、熔断和幂等执行
- Guardian 风险提级、诈骗信号和提示注入防御
- Demo 一键重置和不同体验用户的数据隔离
- 飞书回调校验、消息去重、安全链接和强验证

## 2. Agent 自动化评测

确定性离线评测：

```powershell
.\scripts\run-evals.ps1 -Provider deterministic
```

使用通义千问评测：

```powershell
.\scripts\run-evals.ps1 -Provider qwen
```

评测集位于 `services/api/evals/cases.json`，报告写入被 Git 忽略的 `data/eval-report-<provider>.json`。评测检查意图、槽位、风险等级、Guardian 裁决、提示注入拦截和工具白名单，不调用具有业务副作用的工具。

## 3. 代码检查

后端：

```powershell
cd services/api
python -m ruff check app tests
```

前端：

```powershell
pnpm install --frozen-lockfile
pnpm lint:web
pnpm build:web
```

## 4. GitHub Actions

`.github/workflows/ci.yml` 会在推送和 Pull Request 时执行：

1. Python 3.12 后端依赖安装。
2. Ruff 检查。
3. Pytest 全量测试。
4. 61 条确定性 Agent 评测。
5. Node.js 20 与 pnpm 前端依赖安装。
6. ESLint 与 Next.js 生产构建。

CI 不读取仓库 Secret，也不调用外部大模型，因此 Pull Request 可以安全复现核心结果。

## 5. 测试数据与安全

- 测试账户、联系人、验证码和交易均为虚构数据。
- `.env`、测试报告、数据库文件和日志不会提交到 Git。
- 禁止把真实银行账户、个人身份信息或生产密钥写入测试用例。
- 发现安全问题时请按 [SECURITY.md](../SECURITY.md) 的方式报告，不要在公开 Issue 中披露密钥或可利用细节。
