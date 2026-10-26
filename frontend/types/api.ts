export type Role = "ADMIN" | "OPERATIONS_MANAGER" | "RECOVERY_MANAGER" | "RECIPIENT" | "LOGISTICS" | "AUDITOR";
export type FreshState = "SAFE" | "ACT_SOON" | "LOSS_IMMINENT";
export type Method = "RULE" | "STATISTICAL" | "ML" | "LLM" | "SIMULATED";
export interface User { id: string; email: string; full_name: string; role: Role; org_id: string | null; recipient_id: string | null; language: string; is_platform_admin: boolean; is_active?: boolean; permissions: string[]; status?: AccountStatus; requested_role?: string | null; email_verified?: boolean; created_at?: string | null; last_login_at?: string | null }
export type AccountStatus = "ACTIVE" | "PENDING" | "REJECTED" | "DISABLED";
export interface InvitationRow { id: string; email: string; role: Role; status: "pending" | "used" | "expired" | "revoked"; expires_at: string; requires_approval: boolean; created_at: string; token?: string; invite_url?: string }
export interface Page<T> { items: T[]; total: number; page: number; page_size: number; pages: number }
export interface Freshness { remaining_minutes: number; percent: number; state: FreshState; method: Method }
export interface Lot {
  id: string; lot_code: string; status: string; quantity_kg: number; storage: string; safe_until: string; window_minutes: number; is_simulated: boolean;
  product: { id: string; name: string; sku: string; category: string }; plant: { id: string; name: string; city: string };
  freshness: Freshness; open_case: { id: string; case_number: string; status: string } | null;
}
export interface Option {
  rung: "R1" | "R2" | "R3" | "R4"; label: string; eligible: boolean; reason: string; confidence: number; p_success: number; est_recovery_kg: number;
  method: Method; recipient_id: string | null; recipient_name: string | null; is_recommended: boolean; is_hedge: boolean;
  factors: Record<string, number | boolean>; requires_food_safety_review: boolean;
}
export interface Case {
  id: string; case_number: string; status: string; selected_rung: string | null; quantity_kg: number; recovered_kg: number | null; plan_version: number;
  replan_count: number; pickup_delay_min: number; handover_buffer_min: number; recipient: { id: string; name: string } | null; lot: Lot; created_at: string;
}
export interface AuditEntry { id: string; seq: number; action: string; actor: string; summary: string; created_at: string; hash: string; prev_hash: string; resource_type: string }
export interface Pickup {
  id: string; case_id: string; case_number: string; status: string; scheduled_for: string; eta: string | null; delay_minutes: number; delay_reason: string;
  handed_over_at: string | null; received_kg: number | null; logistics_user: { id: string; name: string } | null; product: string; quantity_kg: number; recipient: string | null;
}
export interface CaseDetail extends Case {
  options: Option[]; evidence: { id: string; kind: string; original_name: string; size_bytes: number; sha256: string; uploaded_at: string }[];
  evidence_score: number; required_evidence: string[]; pickups: Pickup[]; timeline: AuditEntry[]; disclaimer: string;
  decisions: { decision: string; rung: string | null; note: string; at: string }[];
}
export interface Recipient { id: string; name: string; kind: string; accepts_rungs: string[]; acceptance_rate: number; capacity_kg: number; distance_km: number; city: string; phone: string }
export interface Notification { id: string; type: string; severity: string; title: string; body: string; read: boolean; created_at: string; resource_type: string | null; resource_id: string | null }

export interface AllocationRow {
  id: string; recipient_id: string; recipient_name: string; rung: string; quantity_kg: number; status: string; plan_version: number; strategy: string;
  engine_version: string; why: string; eta: string | null; delay_minutes: number; response_reason: string; received_kg: number | null;
  recipient_capacity_kg: number; recipient_remaining_kg: number;
}
export interface AllocationSummary {
  case_id: string; lot_quantity_kg: number; reserved_kg: number; unallocated_kg: number; kg_by_status: Record<string, number>; remaining_minutes: number;
  plan_version: number; replan_count: number; excluded_recipients: string[]; allocations: AllocationRow[];
}
export interface PlanLine { recipient_id: string; recipient_name: string; rung: string; quantity_kg: number; needed_minutes: number; margin_minutes: number; deadline_ok: boolean; why: string }
export interface AllocationPlan {
  engine_version: string; strategy: string; lot_quantity_kg: number; plannable_kg: number; allocated_kg: number; unallocated_kg: number; status: string;
  lines: PlanLine[]; rejected: { recipient_id: string; recipient_name: string; rung: string | null; reason: string; code: string }[]; warnings: string[];
  objective: { allocated_kg: number; pathway_value: number; recovery_pct: number; max_feasible_kg: number }; explanation: string; requires_human_review: boolean; heuristics: string[];
  label?: string;
}
export interface AllocationSim { simulated: true; scenario: string; changes: string[]; before: AllocationPlan; after: AllocationPlan; delta: { allocated_kg: number; unallocated_kg: number }; note: string }
export interface AllocationCompare { simulated: true; label: string; strategies: (AllocationPlan & { label: string })[]; baseline_single_recipient: { allocated_kg: number; rung: string | null } }
export interface AiStatus {
  configured: boolean;
  provider: string;
  model: string | null;
  message: string;
}
export interface AiAnswer {
  summary: string;
  facts: string[];
  hypotheses: string[];
  recommendations: string[];
  risks: string[];
  next_steps: string[];
  missing_information: string[];
  references: string[];
  warnings: string[];
}
export interface AiResult {
  ai_generated: true;
  kind: "chat" | "recommendations" | "failures" | "summary" | "explain";
  answer: AiAnswer;
  data: Record<string, unknown>;
  disclaimer: string;
}
