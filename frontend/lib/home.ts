import type { Role } from "@/types/api";
export const homeFor = (role: Role) => (role === "RECIPIENT" ? "/recipients" : role === "LOGISTICS" ? "/logistics" : "/dashboard");
