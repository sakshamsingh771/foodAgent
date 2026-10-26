import {
  Activity,
  Boxes,
  ClipboardCheck,
  Factory,
  FlaskConical,
  HeartHandshake,
  LayoutDashboard,
  Leaf,
  LineChart,
  Settings,
  FileDown,
  Users,
  ShieldCheck,
  Truck,
  Sparkles,
} from "lucide-react";
import type { ComponentType } from "react";
import type { Role } from "@/types/api";

export interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  roles: readonly Role[];
  /** Backend permission required (any role check AND this permission). Backend remains authoritative. */
  perm?: string;
}

const ALL = ["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER", "AUDITOR"] as const;
const ADMIN_OPS = ["ADMIN", "OPERATIONS_MANAGER"] as const;
const CASE_TEAM = ["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER", "AUDITOR"] as const;

export const NAV: readonly NavItem[] = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard, roles: ["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER", "AUDITOR", "LOGISTICS"] },
  { href: "/operations", label: "Live Operations", icon: Activity, roles: ADMIN_OPS },
  { href: "/inventory", label: "Inventory", icon: Boxes, roles: ADMIN_OPS },
  { href: "/recovery", label: "Recovery", icon: ClipboardCheck, roles: CASE_TEAM },
  { href: "/planning", label: "Planning", icon: LineChart, roles: ADMIN_OPS },
  { href: "/plant", label: "Plant", icon: Factory, roles: ADMIN_OPS },
  { href: "/recipients", label: "Recipients", icon: HeartHandshake, roles: ["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER", "RECIPIENT"] },
  { href: "/logistics", label: "Logistics", icon: Truck, roles: ["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER", "LOGISTICS"] },
  { href: "/sustainability", label: "Sustainability", icon: Leaf, roles: ADMIN_OPS },
  { href: "/compliance", label: "Compliance & audit", icon: ShieldCheck, roles: ["ADMIN", "RECOVERY_MANAGER", "AUDITOR"] },
  { href: "/scenarios", label: "Scenarios", icon: FlaskConical, roles: ["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER", "AUDITOR"] },
  { href: "/users", label: "Users & roles", icon: Users, roles: ["ADMIN"], perm: "users:manage" },
  { href: "/reports", label: "Reports", icon: FileDown, roles: ["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER", "AUDITOR"], perm: "reports:export" },
  { href: "/assistant", label: "AI Assistant", icon: Sparkles, roles: ["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER", "AUDITOR"], perm: "ai:assistant" },
  { href: "/settings", label: "Settings", icon: Settings, roles: ["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER", "AUDITOR", "LOGISTICS", "RECIPIENT"] },
];

export const HOME_BY_ROLE: Record<Role, string> = {
  ADMIN: "/dashboard",
  OPERATIONS_MANAGER: "/operations",
  RECOVERY_MANAGER: "/recovery",
  RECIPIENT: "/recipients",
  LOGISTICS: "/logistics",
  AUDITOR: "/compliance",
};

export const can = (perms: readonly string[] | undefined, perm: string) => !!perms && perms.includes(perm);

export const navFor = (role: Role | undefined, perms?: readonly string[]) =>
  NAV.filter((item) => !!role && item.roles.includes(role) && (!item.perm || can(perms, item.perm)));
