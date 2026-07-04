# digiPrint Product Specifications

Documentation of what the digiPrint Operations Platform does and how it works, written from the code as of **2026-07-04** (including work not yet committed at that date). When behaviour and these docs disagree, trust the code and update the doc.

## Reading guide by audience

| You are… | Start with | Then |
|---|---|---|
| **Management / stakeholder** | [01-product-overview.md](01-product-overview.md) | [04-workflows.md](04-workflows.md) §1 |
| **Store staff / operations** | [04-workflows.md](04-workflows.md) | The [screens/](screens/) doc for whichever screen you're on |
| **Developer / new engineer** | [02-architecture.md](02-architecture.md) | [03-database.md](03-database.md) → [05-api-reference.md](05-api-reference.md) → [06-roles-and-permissions.md](06-roles-and-permissions.md) |

## Contents

| Doc | What's in it |
|---|---|
| [01-product-overview.md](01-product-overview.md) | What digiPrint is, the problem it solves, who uses it |
| [02-architecture.md](02-architecture.md) | Tech stack, components, integrations, background jobs, deployment |
| [03-database.md](03-database.md) | Every table, the order/roll status models, twin-check rules |
| [04-workflows.md](04-workflows.md) | End-to-end flows: Pronto sync, intake, Drive watcher, emails, blanks, refunds |
| [05-api-reference.md](05-api-reference.md) | Every endpoint with auth requirements and behaviours |
| [06-roles-and-permissions.md](06-roles-and-permissions.md) | Roles, JWT scoping, operator initials, known auth gaps |
| [screens/login.md](screens/login.md) | Sign-in screen |
| [screens/dashboard.md](screens/dashboard.md) | Stats dashboard |
| [screens/orders.md](screens/orders.md) | Order list / search |
| [screens/order-detail.md](screens/order-detail.md) | Single-order workbench |
| [screens/intake.md](screens/intake.md) | Film booking flow |

## Conventions

- Each doc opens with an **Audience** tag so you know how technical it gets.
- **"Known gaps"** sections record honest discrepancies between intended and current behaviour (e.g. frontend screens still using the pre-migration-003 status names, unauthenticated drive/email endpoints). They double as a lightweight backlog.
- File paths like `app/services/drive_watcher.py` are relative to `backend/` unless prefixed with `frontend/`.
