"use client";

import { useEffect, useState } from "react";
import type { AgentRun } from "@/lib/types";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");

async function channelRequest(token: string, payload?: Record<string, unknown>): Promise<AgentRun> {
  const response = await fetch(`${API_BASE}/api/v1/channels/secure/${encodeURIComponent(token)}${payload ? "/resume" : ""}`, {
    method: payload ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: payload ? JSON.stringify(payload) : undefined,
    cache: "no-store",
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.detail?.message || "安全链接无效或已过期");
  return data as AgentRun;
}

export function SecureChannelAction({ token }: { token: string }) {
  const [run, setRun] = useState<AgentRun | null>(null);
  const [otp, setOtp] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    channelRequest(token).then(setRun).catch((e: Error) => setError(e.message));
  }, [token]);

  const submit = async (confirmed: boolean) => {
    setBusy(true);
    setError("");
    try {
      setRun(await channelRequest(token, {
        confirmed,
        ...(run?.status === "waiting_auth" ? { auth_code: otp } : {}),
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="secure-channel-shell">
      <section className="secure-channel-card">
        <div className="secure-channel-brand"><img src="/banking-agent-icon.svg" alt="" />青穗银行安全确认</div>
        <p className="secure-channel-kicker">来自 IM 渠道的受保护操作</p>
        {error && <div className="secure-channel-error">{error}</div>}
        {!run && !error && <p>正在验证一次性安全链接…</p>}
        {run && (
          <>
            <h1>{run.status === "completed" ? "操作已完成" : "请核对操作详情"}</h1>
            <p className="secure-channel-copy">{run.response_text}</p>
            <dl>
              <div><dt>业务意图</dt><dd>{run.intent}</dd></div>
              <div><dt>风险级别</dt><dd>{run.guardian?.effective_risk || "按策略判定"}</dd></div>
              <div><dt>运行编号</dt><dd className="mono">{run.id.slice(0, 12)}</dd></div>
            </dl>
            {run.status === "waiting_auth" && (
              <label className="secure-otp"><span>短信验证码 / 演示强验证</span><input inputMode="numeric" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} placeholder="请输入 6 位验证码" /></label>
            )}
            {(run.status === "waiting_confirmation" || run.status === "waiting_auth") && (
              <div className="secure-channel-actions">
                <button disabled={busy} className="secondary-button" onClick={() => submit(false)}>取消</button>
                <button disabled={busy || (run.status === "waiting_auth" && otp.length !== 6)} className="primary-button" onClick={() => submit(true)}>{busy ? "处理中…" : "确认并执行"}</button>
              </div>
            )}
            {!(["waiting_confirmation", "waiting_auth"] as string[]).includes(run.status) && <div className="secure-channel-finished">该请求当前状态：{run.status}</div>}
          </>
        )}
        <small>安全链接短时有效，请勿转发。Agent 不会在 IM 对话中直接执行黄色或红色操作。</small>
      </section>
    </main>
  );
}
