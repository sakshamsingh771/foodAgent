# Demo
`make demo` loads simulated data: two manufacturers (Verdana Foods, Sahyadri Beverages), six recipients, lots in every freshness state, three live cases, 30 days of simulated history, plant, forecast and compliance records.

Password for all demo users: `FoodAgent#2026demo`

| Role | Email |
|---|---|
| Admin | admin@verdanafoods.demo |
| Operations | ops@verdanafoods.demo |
| Recovery manager | recovery@verdanafoods.demo |
| Logistics | logistics@verdanafoods.demo |
| Auditor | auditor@verdanafoods.demo |
| Recipient (Hindi default) | recipient@annapurna.demo |
| Other org (isolation test) | admin@sahyadribev.demo |

**Walkthrough:** ops → Live Operations → *Open recovery case* on a red lot → recovery manager reviews evidence, tries the what-if sliders, approves → recipient accepts (or declines to see automatic replanning) → ops schedules pickup → logistics marks in transit/arrived → handover → Sustainability and the audit chain update. Try *Scenarios* at any point, then *Reset*.

Also: `admin@sahyadribev.demo` (Sahyadri Beverages admin, cannot see Verdana data) and `platform@foodagent.demo` (platform administrator, approves new organizations). The sign-in page shows one-click demo shortcuts only when `ENVIRONMENT != production` and `DEMO_LOGIN_ENABLED=true`; they call the normal `/auth/login`. Do not run the demo seed in production.
