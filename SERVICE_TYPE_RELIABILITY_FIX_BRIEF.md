# RollCall — Fix Brief: Harden Service-Type Mapping (Intake)

**Prepared 11 Aug 2026.** Small reliability task, surfaced during the Session 2 smoke-test: booking a **Develop + Print** order as `lab.bondi` threw a backend 422 (`service_type` enum rejection) at the intake desk. Root cause is a fragile label→enum mapping pattern, not store-scoping or security.

Real backend entry point: `app/main.py`. Frontend dev server is Vite (hot-reload). Standing prefs: full-file replacements, incremental, dev-server verify before commit.

---

## Current state (read before starting)

There are **three** hand-maintained lists of film service types that must agree, plus a silent fallback that hides drift:

1. **Backend enum** — `backend/app/models/schemas.py`, `class ServiceType` (lines 10–16). The canonical values:
   `"Dev only"`, `"Dev+Scan"`, `"Dev+Scan+Print"`, `"Dev+Print"`, `"Scan only"`, `"Print only"`.
2. **Dropdown list** — `frontend/src/components/ProntoOrderSummary.tsx`, `SERVICE_TYPES` (lines 5–11). Display labels (`"Develop + Print"` etc.).
3. **Label→enum map** — `frontend/src/pages/IntakePage.tsx`, `SERVICE_TYPE_MAP` (lines 27–33).

**The fault:** the two conversion call sites use a silent fallback —
`frontend/src/pages/IntakePage.tsx:432` (manual-entry path) and `:479` (Pronto path):
```
const backendServiceType = SERVICE_TYPE_MAP[serviceType] || serviceType;
```
When a label isn't in the map, `|| serviceType` **sends the raw display label to the backend**, which then 422s. So a missing map key becomes a customer-facing error at the desk instead of failing safe.

**Already patched (uncommitted, in the working tree):** `"Develop + Print" → "Dev+Print"` was added to both `SERVICE_TYPE_MAP` and `SERVICE_TYPES` to unblock testing. This task **supersedes** that patch — the refactor below restructures those lists anyway, so fold it in rather than treating it as separate.

---

## What to change

### 1. Single source of truth (kill the drift between the two frontend lists)
Define the label→enum mapping **once** and derive the dropdown from it, so the two frontend lists can never disagree again. Suggested: a shared module (e.g. `frontend/src/lib/serviceTypes.ts`) exporting:
- `SERVICE_TYPE_MAP` (the 6 label→enum pairs), and
- `SERVICE_TYPES = Object.keys(SERVICE_TYPE_MAP)` for the dropdown.

Import both into `IntakePage.tsx` and `ProntoOrderSummary.tsx`. Delete the now-duplicate local `SERVICE_TYPES` array in `ProntoOrderSummary.tsx` and the local `SERVICE_TYPE_MAP` in `IntakePage.tsx`. The manual-entry `<select>` (`IntakePage.tsx:762`) should also source its options from this shared `SERVICE_TYPES`.

### 2. Remove the silent fallback (fail loud, not silent)
At both call sites (`IntakePage.tsx:432` and `:479`), replace `SERVICE_TYPE_MAP[x] || x` with a hard lookup: if the label is **not** in the map, do **not** submit — block the booking and surface a clear message (e.g. an intake error state / toast: *"Unrecognised service type '{label}' — cannot book. Check the service-type list."*). An unmapped value must never reach the API as a raw string.

### 3. (Recommended) A cheap guard so this can't regress silently
Add a lightweight check that every value in the frontend `SERVICE_TYPE_MAP` is a member of the backend `ServiceType` enum. Options, pick the lightest that fits the repo:
- a tiny frontend unit test asserting the 6 mapped values equal a hardcoded copy of the enum values, **or**
- a short script/test that reads the enum values and diffs them against the map.
Goal: if someone adds a service type to one side and not the other, a test fails in CI/dev rather than a booking failing in production.

---

## Verify
1. Vite dev server: as `lab.bondi`, book one order of **each** of the 6 service types (Dev only, Dev+Scan, Dev+Scan+Print, **Dev+Print**, Scan only, Print only) — all book in cleanly, no 422.
2. Confirm the manual-entry path (no Pronto lookup) also books all 6.
3. Temporarily add a fake label to the dropdown only (not the map) in a scratch edit → confirm the booking is **blocked with the clear message**, not posted to the backend. Revert the scratch edit.
4. The regression guard (step 3 above) passes; break it deliberately once to confirm it actually catches drift, then restore.

## Done
- Two frontend lists collapsed to one source of truth; silent `|| x` fallback gone; guard in place.
- All 6 service types book via both Pronto and manual paths.
- Discard the test orders afterward so they don't skew dashboard counts.
- Commit + push; add a one-line note to the Session 2 Notion log (or its own entry) — this was found and fixed during the Session 2 smoke-test.

## Out of scope
- Light/dark theme toggle (known Session 4 item — theme is infrastructure-only, pages hardcode dark hexes). Do not touch here.
- Aligning the Pronto view's `inferred_service_type` label vocabulary with the enum (bigger change; the map is the right seam for now).
