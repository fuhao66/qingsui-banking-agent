import type { AgentRun, AuditEventList, DemoResetResponse, ExperienceLoginResponse, ExperienceProfile, ScheduledTask, ScheduledTaskList, SecurityStatus } from "./types";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");
const TOKEN_KEY = "banking-agent-experience-token";

function accessToken(): string | null {
  return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
}

class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}/api/v1${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken() ? { Authorization: `Bearer ${accessToken()}` } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { message?: string } | string } | null;
    const detail = typeof payload?.detail === "string" ? payload.detail : payload?.detail?.message;
    throw new ApiError(detail || `请求失败（${response.status}）`, response.status);
  }

  return response.json() as Promise<T>;
}

export async function loginExperience(inviteCode: string, displayName: string): Promise<ExperienceLoginResponse> {
  const response = await request<ExperienceLoginResponse>("/auth/experience", {
    method: "POST",
    body: JSON.stringify({ invite_code: inviteCode, display_name: displayName }),
  });
  window.localStorage.setItem(TOKEN_KEY, response.access_token);
  return response;
}

export function getExperienceProfile(): Promise<ExperienceProfile> {
  return request<ExperienceProfile>("/auth/me");
}

export async function logoutExperience(): Promise<void> {
  await request<{ status: string }>("/auth/logout", { method: "POST" }).catch(() => undefined);
  window.localStorage.removeItem(TOKEN_KEY);
}

export function clearExperienceToken(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(TOKEN_KEY);
}

export function createRun(message: string, conversationId?: string): Promise<AgentRun> {
  return request<AgentRun>("/agent/runs", {
    method: "POST",
    body: JSON.stringify({ message, conversation_id: conversationId, channel: "app" }),
  });
}

export function createEvidenceRun(
  message: string,
  evidenceText?: string,
  imageDataUrl?: string,
  conversationId?: string,
): Promise<AgentRun> {
  return request<AgentRun>("/agent/evidence-runs", {
    method: "POST",
    body: JSON.stringify({
      message,
      evidence_text: evidenceText || undefined,
      image_data_url: imageDataUrl || undefined,
      conversation_id: conversationId,
      channel: "app",
    }),
  });
}

export function resumeRun(runId: string, payload: Record<string, unknown>): Promise<AgentRun> {
  return request<AgentRun>(`/agent/runs/${runId}/resume`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function requestHandoff(runId: string, reason: string): Promise<AgentRun> {
  return request<AgentRun>(`/agent/runs/${runId}/handoff`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function getAuditEvents(limit = 8): Promise<AuditEventList> {
  return request<AuditEventList>(`/security/audit-events?limit=${limit}`);
}

export function getSecurityStatus(): Promise<SecurityStatus> {
  return request<SecurityStatus>("/security/status");
}

export function resetDemoData(): Promise<DemoResetResponse> {
  return request<DemoResetResponse>("/demo/reset", {
    method: "POST",
    body: JSON.stringify({ confirmation: "RESET_DEMO_DATA" }),
  });
}

export function getScheduledTasks(): Promise<ScheduledTaskList> {
  return request<ScheduledTaskList>("/scheduled-tasks");
}

export function updateScheduledTask(taskId: string, action: "pause" | "resume" | "cancel"): Promise<ScheduledTask> {
  return request<ScheduledTask>(`/scheduled-tasks/${taskId}/actions`, {
    method: "POST",
    body: JSON.stringify({ action, confirmed: true }),
  });
}
