# Role and Permission Matrix

The backend definition in `backend/app/core/security.py` is authoritative. Frontend navigation is a convenience filter and never replaces backend authorization.

| Role | Dashboard | Inventory | Recovery | Logistics | Recipients | Scenarios | Reports | Audit | AI Assistant |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `ADMIN` | Read/write organization operations | Read/write/adjust | Create, approve, close | Schedule and manage | Read | Read/apply/reset | Export | Read | Read-only explanations |
| `OPERATIONS_MANAGER` | Read/write operations | Read/write/adjust | Create and evidence | Schedule and manage | Read | Read/apply/reset | Export | No audit log | Read-only explanations |
| `RECOVERY_MANAGER` | Read recovery metrics | Read | Approve, replan, close, evidence | Read | Read | Read/apply/reset | Export | Read | Read-only explanations |
| `RECIPIENT` | Own recipient experience | No | Own offers and responses | Own handover | Own offers | No | No | No | No |
| `LOGISTICS` | Read logistics dashboard | Read-only operational reads | Read authorized cases | Assigned/unassigned pickup work | Read where endpoint permits | No | No | No | No |
| `AUDITOR` | Read oversight dashboard | Read | Read cases/evidence | Read | Read | Read and preview only | Export | Read and verify | Read-only explanations |

## Sensitive permissions

| Permission | Granted roles |
|---|---|
| `ai:assistant` | Admin, Operations Manager, Recovery Manager, Auditor |
| `scenarios:run` | Admin, Operations Manager, Recovery Manager |
| `cases:approve` | Admin, Recovery Manager |
| `cases:close` | Admin, Recovery Manager |
| `users:manage` | Admin |
| `audit:read` | Admin, Recovery Manager, Auditor |
| `reports:export` | Admin, Operations Manager, Recovery Manager, Auditor |

## Organization and partner scope

Case, lot, allocation, pickup, audit, report, and AI context records are scoped to the authenticated user's organization. Recipients are partner organizations and may be cross-organization matching targets by design; recipient responses are restricted to the authenticated recipient account and assigned recipient record.
