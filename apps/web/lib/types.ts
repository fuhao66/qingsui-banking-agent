export type RiskLevel = "green" | "yellow" | "red" | string;

export type RunStatus =
  | "running"
  | "waiting_clarification"
  | "waiting_confirmation"
  | "waiting_auth"
  | "human_review"
  | "completed"
  | "cancelled"
  | "failed";

export interface AgentPlanNode {
  id: string;
  kind: string;
  tool_name: string | null;
  depends_on: string[];
  risk_level: RiskLevel;
  description: string;
}

export interface AgentStep {
  id: string;
  node_id: string;
  sequence: number;
  kind: string;
  tool_name: string | null;
  status: string;
  input_data: Record<string, unknown>;
  output_data: Record<string, unknown>;
  error_code: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface AgentHandoff {
  id: string;
  status: string;
  reason: string;
  resume_status: string;
  resolution: string | null;
  requested_at: string;
  resolved_at: string | null;
}

export interface PayeeOption {
  id: string;
  name: string;
  bank_name: string;
  account_masked: string;
  alias?: string | null;
}

export interface TransferDetails {
  amount?: string | number;
  currency?: string;
  source_account?: string;
  payee?: string;
  draft_id?: string;
  [key: string]: unknown;
}

export interface SubscriptionOption {
  id: string;
  merchant: string;
  product_name: string;
  amount: string | number;
  next_charge_at?: string | null;
}

export interface PendingAction {
  type: string;
  prompt?: string;
  options?: Array<PayeeOption | SubscriptionOption>;
  details?: TransferDetails;
  challenge_id?: string;
  fields?: string[];
  reason?: string;
}

export interface AgentRun {
  id: string;
  conversation_id: string;
  channel: string;
  user_message: string;
  intent: string;
  confidence: string | number;
  model_provider: string;
  status: RunStatus;
  plan: AgentPlanNode[];
  plan_hash: string;
  current_node_id: string | null;
  pending_action: PendingAction | null;
  result: Record<string, unknown> | null;
  response_text: string | null;
  error_code: string | null;
  version: number;
  steps: AgentStep[];
  handoff: AgentHandoff | null;
  guardian: GuardianAssessment | null;
  created_at: string;
  updated_at: string;
}

export interface GuardianAssessment {
  id: string;
  source_type: string;
  model_provider: string;
  scam_score: number;
  disposition: "allow" | "step_up" | "block";
  original_risk: RiskLevel;
  effective_risk: RiskLevel;
  signals: Array<{ code: string; label: string; weight: number; evidence: string }>;
  evidence_summary: string | null;
  counterfactual: { current?: string; without_signals?: string; changed_factors?: string[] };
  decision_receipt: Record<string, unknown>;
  receipt_hash: string | null;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  correlation_id: string;
  action: string;
  outcome: string;
  risk_level: RiskLevel | null;
  resource_type: string;
  resource_id: string;
  reason_codes: string[];
  details: Record<string, unknown>;
  previous_hash: string | null;
  event_hash: string;
  created_at: string;
}

export interface AuditEventList {
  items: AuditEvent[];
  total: number;
  chain_valid: boolean;
}

export interface SecurityStatus {
  locked: boolean;
  consecutive_failures: number;
  locked_until: string | null;
  policy_version: string;
}

export interface DemoResetResponse {
  status: "reset";
  reset_at: string;
  user_id: string;
  audit_event_id: string;
}

export interface ScheduledTask {
  id: string;
  run_id: string;
  source_account_id: string;
  task_type: string;
  title: string;
  status: "scheduled" | "paused" | "cancelled" | "completed" | "failed";
  execute_at: string;
  budget: string | number;
  reserved_amount: string | number;
  currency: string;
  risk_level: RiskLevel;
  plan: Array<Record<string, unknown>>;
  items: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
}

export interface ScheduledTaskList {
  items: ScheduledTask[];
  total: number;
  active_reserved_amount: string | number;
  currency: string;
}

export interface ExperienceLoginResponse {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  user_id: string;
  display_name: string;
}

export interface ExperienceProfile {
  user_id: string;
  display_name: string;
  expires_at: string;
  request_count: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  run?: AgentRun;
}
