# 本机公网体验隧道

该方式让本机继续运行 Web 与 API，并通过 Cloudflare Quick Tunnel 提供临时 HTTPS 地址，不需要购买服务器或域名。

## 启动和停止

```powershell
.\scripts\start-public-tunnel.ps1
.\scripts\stop-public-tunnel.ps1
```

首次启动会生成 `.env.tunnel`，其中包含随机邀请码、管理员令牌和审计 HMAC 密钥。该文件已被 Git 忽略，不得上传或发送给体验者。体验者只需要临时公网地址和邀请码。

## 使用限制

- 本机、网络、API、Web 和隧道进程必须持续运行。
- Quick Tunnel 地址在隧道重建后可能改变。
- 适合邀请少量评委或同学体验，不作为生产银行系统使用。
- 电脑休眠、断网、重启或关闭脚本都会使链接失效。
- 外发时必须注明固定验证码和资金均为比赛沙箱模拟。
