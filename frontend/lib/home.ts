import type { Role } from "@/types/api";
import { HOME_BY_ROLE } from "@/lib/rbac";

export const homeFor = (role: Role) => HOME_BY_ROLE[role];
