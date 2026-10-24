"use client";
import { useQuery } from "@tanstack/react-query";
import { get } from "@/lib/api";
import type { AuditEntry, Case, CaseDetail, Lot, Page, Pickup, Recipient } from "@/types/api";

export interface Dashboard {
  kpis: { kg_at_risk: number; kg_recovered_today: number; meals_recovered_30d: number; co2e_avoided_kg_30d: number; active_cases: number; pending_approvals: number; pickups_today: number; recovery_success_rate: number | null; lots_at_risk: number; loss_imminent: number };
  trend: { day: string; kg: number }[]; recent_activity: AuditEntry[];
}
export const useDashboard = () => useQuery({ queryKey: ["dashboard"], queryFn: () => get<Dashboard>("/dashboard/summary") });
export const useLots = (qs: string) => useQuery({ queryKey: ["lots", qs], queryFn: () => get<Page<Lot>>(`/lots?${qs}`), placeholderData: (p) => p });
export const useCases = (qs: string) => useQuery({ queryKey: ["cases", qs], queryFn: () => get<Page<Case>>(`/recovery-cases?${qs}`), placeholderData: (p) => p });
export const useCase = (id: string) => useQuery({ queryKey: ["case", id], queryFn: () => get<CaseDetail>(`/recovery-cases/${id}`) });
export const usePickups = (qs = "") => useQuery({ queryKey: ["pickups", qs], queryFn: () => get<Page<Pickup>>(`/pickups?${qs}`) });
export const useRecipients = () => useQuery({ queryKey: ["recipients"], queryFn: () => get<Recipient[]>("/recipients") });
