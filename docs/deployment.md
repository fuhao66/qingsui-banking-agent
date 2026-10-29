# 部署说明

本文档覆盖三种运行方式：本地一键演示、本机临时公网体验、Linux 服务器固定域名部署。系统只处理竞赛沙箱数据，不得用于真实银行业务。

## 1. 环境要求

### 本地一键演示

- Windows 10/11 与 PowerShell 7
- Python 3.12+
- Node.js 20+
- pnpm 10.17.1

### Docker 部署

- Docker Engine 25+
- Docker Compose v2
- 固定域名部署需要可解析的域名以及开放的 TCP 80、TCP 443、UDP 443

## 2. 获取代码与配置

```powershell
git clone https://github.com/fuhao66/qingsui-banking-agent.git
cd qingsui-banking-agent
Copy-Item .env.example .env
```

按需填写 `.env` 中的 `DASHSCOPE_API_KEY` 或 `OPENAI_API_KEY`。未配置模型密钥时，系统会使用确定性中文适配器，仍可完成离线演示和自动化测试。

禁止提交 `.env`、`.env.public`、`.env.tunnel` 或任何真实凭据。仓库只保留不含密钥的示例配置。

## 3. Windows 本地一键演示

```powershell
.\scripts\start-demo.ps1
```

脚本会创建或复用 `services/api/.venv`，执行数据库迁移和种子数据初始化，并启动：

- Web：<http://localhost:3000>
- API：<http://localhost:8000>
- OpenAPI：<http://localhost:8000/docs>

停止服务：

```powershell
.\scripts\stop-demo.ps1
```

开发沙箱的默认演示验证码为 `246810`。它只能用于比赛演示。

## 4. Docker 本地运行

```powershell
docker compose up --build
```

查看状态和日志：

```powershell
docker compose ps
docker compose logs -f api web
```

停止服务：

```powershell
docker compose down
```

如需同时删除本地 Docker 数据卷，请先确认数据不再需要，再运行 `docker compose down -v`。

## 5. 本机临时公网体验

电脑可以持续开机时，可使用 Cloudflare Quick Tunnel 暂时开放 HTTPS 体验地址：

```powershell
.\scripts\start-public-tunnel.ps1
```

脚本会输出临时网址。停止隧道：

```powershell
.\scripts\stop-public-tunnel.ps1
```

临时地址在进程重启后可能变化。飞书事件回调地址也需要同步更新。详细限制见 [本机公网体验隧道](local-public-tunnel.md)。

## 6. Linux 固定域名公网部署

复制并填写公网配置：

```bash
cp .env.public.example .env.public
```

至少设置以下变量：

- `PUBLIC_DOMAIN`
- `POSTGRES_PASSWORD`
- `PUBLIC_INVITE_CODE`
- `ADMIN_API_TOKEN`
- `SECURITY_HMAC_SECRET`
- `DASHSCOPE_API_KEY` 或相应模型密钥
- 使用飞书时设置 `FEISHU_VERIFICATION_TOKEN`、`FEISHU_ENCRYPT_KEY`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET`

所有密码、令牌和 HMAC 密钥都应使用独立随机值。曾在聊天、截图或日志中出现过的密钥必须先在供应商后台轮换。

校验配置：

```bash
docker compose --env-file .env.public -f docker-compose.public.yml config --quiet
```

构建并启动：

```bash
docker compose --env-file .env.public -f docker-compose.public.yml up -d --build
```

检查服务：

```bash
docker compose --env-file .env.public -f docker-compose.public.yml ps
docker compose --env-file .env.public -f docker-compose.public.yml logs -f api web caddy
```

Caddy 会自动申请和续期 HTTPS 证书。PostgreSQL、Redis、API 和 Web 不直接暴露公网端口，外部流量只通过 Caddy 进入。

更新版本：

```bash
git pull --ff-only
docker compose --env-file .env.public -f docker-compose.public.yml up -d --build
```

## 7. 飞书回调

固定域名部署后，在飞书开放平台设置事件请求地址：

```text
https://你的域名/api/v1/channels/feishu/events
```

订阅 `im.message.receive_v1` 并确认应用版本已经发布。飞书配置细节见 [PWA 与飞书多渠道接入](stage-11-pwa-and-feishu-channel.md)。

## 8. 上线验收

```text
GET /health/live
GET /health/ready
GET /api/v1/security/policy-matrix
GET /api/v1/agent/tools
```

随后完成以下人工验收：

1. 查询余额可以直接返回沙箱数据库结果。
2. 一百元转账必须等待黄色确认。
3. 两千元转账必须进入红色强验证。
4. 注入指令不能绕过权限策略。
5. 同一外部事件不会重复执行。
6. 不同体验用户的数据相互隔离。

## 9. 生产边界

当前实现不具备真实银行生产资格。生产化至少还需要银行 IAM、设备可信证明、真实 MFA、KMS/HSM、不可篡改审计、核心银行与对账接口、反洗钱规则、灾备和合规评审。
