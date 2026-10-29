# 第十一阶段：PWA 与飞书多渠道接入

## 已实现范围

- Next.js Web 已声明 Web App Manifest、主题色、图标和 Service Worker，可在 HTTPS 或 localhost 环境安装为 PWA。
- FastAPI 暴露飞书事件订阅入口 `POST /api/v1/channels/feishu/events`，支持 URL Verification、Verification Token 和 Encrypt Key 签名校验。
- 飞书文本消息被标准化为统一 Agent 请求，渠道固定标记为 `im`，继续使用现有 LLM 意图理解、白名单 DAG、Guardian 与三级权限控制。
- `channel_identities` 将飞书租户和 Open ID 映射到独立演示用户；首次对话自动克隆银行沙箱，避免不同体验者共享资金数据。
- `channel_message_receipts` 以飞书 Message ID 去重，并保存外部聊天、身份和 Agent Run 的可追踪关系。
- 需要补槽时，下一条 IM 文本会恢复当前 Run；黄色确认和红色强验证不会接受聊天文字确认，而是返回短时 HMAC 签名链接。
- 安全页使用 `GET/POST /api/v1/channels/secure/{token}` 读取并恢复指定 Run；红色操作仍必须输入六位强验证码。

## 飞书开放平台配置

1. 创建企业自建应用，启用机器人能力，并授予接收消息及以机器人身份回复消息所需权限。
2. 在事件订阅中配置请求地址：`https://你的域名/api/v1/channels/feishu/events`。
3. 订阅事件 `im.message.receive_v1`，填写与服务端一致的 Verification Token 和 Encrypt Key。
4. 在部署环境设置：

```dotenv
PUBLIC_WEB_BASE_URL=https://你的域名
CHANNEL_LINK_MINUTES=10
FEISHU_VERIFICATION_TOKEN=飞书验证Token
FEISHU_ENCRYPT_KEY=飞书EncryptKey
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=飞书AppSecret
FEISHU_DELIVERY_ENABLED=true
```

5. 重启 API，并确认 URL Verification 成功。临时 Cloudflare 隧道每次地址可能变化，需要在飞书后台更新回调 URL；固定域名部署无需重复修改。

当前实现同时支持飞书 2.0 明文 JSON 与 AES-256-CBC 加密事件体。URL Verification 按飞书握手协议解密并验证内部 Verification Token 后直接返回 Challenge；正常业务事件先验证原始请求体签名，再以 Encrypt Key 的 SHA-256 摘要派生密钥，读取密文前 16 字节 IV 并完成 PKCS7 解密。解密、验签或 Token 校验失败均不会进入 Agent 运行时。

## PWA 安装

- Android Chrome/Edge：打开 HTTPS 页面，选择“安装应用”或“添加到主屏幕”。
- iOS Safari：选择“分享” -> “添加到主屏幕”。
- Service Worker 只缓存页面壳和图标，不缓存 `/api/` 响应，避免账户数据落入离线缓存。

## 安全边界

IM 文本、用户名和外部消息字段均为不可信输入。飞书凭据只存在服务端环境变量；外部 Open ID 不作为银行用户 ID。安全链接包含 Run、沙箱用户和过期时间，并使用 `SECURITY_HMAC_SECRET` 生成 SHA-256 HMAC。链接过期、签名错误、Run 不属于绑定用户或 Run 已经结束时，服务端拒绝执行。

PWA/IM 均为竞赛沙箱渠道，不连接真实银行账户。生产化仍需接入银行统一身份认证、设备绑定、真实 MFA、密钥托管、消息失败重试队列和渠道风控策略。

## 验收

```powershell
cd services/api
.venv\Scripts\python.exe -m pytest tests/test_multichannel.py -q
```

自动化用例验证 URL Verification、错误 Token 拒绝、回调签名、消息幂等、独立 IM Run、黄色操作安全跳转和网页确认执行。前端使用 `pnpm --filter @banking-agent/web build` 验证 PWA 与安全操作页。
