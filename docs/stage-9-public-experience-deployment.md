# 公网体验部署阶段

## 已实现能力

- 邀请码换取限时随机 Bearer Token，数据库只保存 SHA-256 摘要。
- 公网模式完全禁用 `X-Demo-User-ID` 身份指定。
- 每次登录创建独立用户、账户、流水、联系人、卡片和订阅副本。
- 每分钟请求限流、最大活跃体验人数和会话自动过期。
- “重置数据”只清理当前体验者的业务数据，不影响其他访客。
- 管理员统计接口展示会话数、活跃人数、请求量、Agent 运行数和定时任务数。
- Caddy 自动申请 HTTPS 证书，并添加 HSTS、禁止嵌入等安全响应头。
- PostgreSQL、Redis、API 和 Web 均不直接暴露公网端口，只有 Caddy 开放 80/443。

## 上线前准备

1. 准备一台安装 Docker Engine 和 Compose 插件的 Linux 服务器。
2. 将域名 A/AAAA 记录指向服务器公网 IP。
3. 云防火墙只开放 TCP 80、TCP 443 和 UDP 443；SSH 端口限制管理来源。
4. 将代码复制到服务器。
5. 复制配置模板：

```bash
cp .env.public.example .env.public
```

6. 填写域名、数据库随机密码、邀请码、管理员令牌、HMAC 密钥和 Qwen Key。`.env.public` 已被 Git 忽略。

## 校验与启动

在 Windows PowerShell 管理终端：

```powershell
.\scripts\deploy-public.ps1 -ValidateOnly
.\scripts\deploy-public.ps1
```

在 Linux 服务器可直接运行：

```bash
docker compose --env-file .env.public -f docker-compose.public.yml config --quiet
docker compose --env-file .env.public -f docker-compose.public.yml up -d --build
```

Caddy 会根据 `PUBLIC_DOMAIN` 自动申请和续期 HTTPS 证书。DNS 生效且 80/443 能从公网访问后，体验地址为 `https://你的域名`。

## 管理员统计

```powershell
.\scripts\public-stats.ps1
```

或请求：

```http
GET /api/v1/admin/experience-stats
X-Admin-Token: <ADMIN_API_TOKEN>
```

禁止把管理员令牌放入网页代码或发给体验者。

## 安全边界

这是比赛沙箱，不是生产银行系统。固定 OTP、模拟商户和模拟资金必须在登录页与演示说明中保持可见。公开部署前应重新生成全部密钥，不得复用本地 `.env` 中的任何值。
