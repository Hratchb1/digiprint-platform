# RollCall — Finish & Ship Brief (consolidated, 11 Aug 2026)

Execute all of the below in the Claude Code session (holds the uncommitted work + the build/git/dev-server loop). Ship as **separate, logical commits** — do not bundle unrelated changes. Full-file replacements; dev-server verify before each commit.

Four workstreams. A and B are already coded and just need verify + commit. C and D are new edits.

---

## A. Service-type reliability fix — CODED, needs verify + commit
Already implemented: `frontend/src/lib/serviceTypes.ts` (single source of truth), local arrays removed from `ProntoOrderSummary.tsx` + `IntakePage.tsx`, silent `|| x` fallback replaced with `toBackendServiceType()` + block-on-null, `scripts/check_service_types.mjs` guard.

Before committing:
1. Confirm the working tree is clean of the earlier 2-line Cowork hot-patch (`"Develop + Print"` was hand-added to the old `SERVICE_TYPE_MAP`/`SERVICE_TYPES` before the refactor). The `serviceTypes.ts` refactor supersedes it — make sure no orphaned/duplicate entries remain in the old locations.
2. Dev-server: book all **6** service types as `lab.bondi` via **both** the Pronto and manual-entry paths — all book, no 422. (Dev+Print and Dev+Scan already confirmed; still need Dev only, Dev+Scan+Print, Scan only, Print only.)
3. Negative test: temporarily add a fake label to the dropdown only (not the map) → confirm booking is **blocked with the message**, nothing hits the API → revert.
4. `npm run check:service-types` passes.
5. **Commit** (frontend + the guard script).

## B. "Run watcher now" button — CODED, needs verify + commit
Already implemented: `_watcher_lock` guard in `drive_watcher.py`, status-aware `manual_drive_sync`, `driveApi.sync()`, button in `DashboardPage.tsx`.

Before committing:
1. **Set `PAUSE_EMAILS=1` in `backend/.env` for this test** so the live watcher run can't email real customers, then dev-server test: click the button → disables + spinner → toast on completion.
2. Double-click / click mid-scheduled-cycle → second run no-ops via the `already_running` path (check backend log).
3. Drop a throwaway folder in a store Inbox → confirm immediate pickup.
4. Restore `PAUSE_EMAILS` to its intended value afterward.
5. **Commit** (backend + frontend).

## C. Email Reply-To header — NEW edit
In `backend/app/services/email_service.py`, the SMTP send block (~line 474) builds `msg` with `From`, `Subject`, `To` but **no `Reply-To`**. `store_reply_email` is already in scope in `send_order_email` (set ~line 342). Add, guarded for None:
```
if store_reply_email:
    msg["Reply-To"] = store_reply_email
```
So customer replies route to the store's public inbox regardless of which Gmail account authenticated the send. **Commit** (backend).

> **Manual step for Hratch (NOT code):** Bondi emails currently send *from* Hratch's personal address because the Bondi `drive_config` row's `gmail_address` + `gmail_app_password` are his. Fix in Supabase: set those to the lab's own mailbox + its app password. Reply-To above is the safety net; this is the real From fix.

## D. Manual-email status tracking + blank-send clarity — NEW edit
**Bug:** `send_manual_email` (`email_service.py` ~line 636–640) hardcodes `email_status = "sent"` for **every** template, so a blank or print-ready send lights up the "Delivery" row and leaves "Blank notice" / "Print ready" permanently "Not sent."

**Backend fix:** on success, update the status column that matches `template_key`:
- `blank_notification` → `blank_email_status = "sent"`
- `prints_ready` → `print_ready_email_status = "sent"`
- `scans_ready`, `prints_and_scans_ready`, `negatives_ready` (and any delivery) → `email_status = "sent"`
Keep the existing "advance to delivered" guard as-is. (Auto-send/watcher path is unaffected — this is the manual path only.)

**Frontend clarity (`OrderDetailPage.tsx`):** the status rows already read `blank_email_status` / `print_ready_email_status`, so they'll light up once the backend writes them. Additionally, when the order is **all-blank** (`rolls.length > 0 && rolls.every(r => r.is_blank)`), label the send/resend button **"Send blank notification"** (or "Resend blank notification" if `blank_email_status` is set) instead of the generic "Resend Email", so staff know what it does.

Verify: mark a test order's only roll blank → button reads "Send blank notification" → click → email sends AND the **"Blank notice"** row flips to sent (not "Delivery"). Repeat a normal Dev+Scan+Print send → "Delivery" row updates, blank row stays clear. **Commit** (backend + frontend).

---

## Ship order
A → B → C → D, each its own commit, dev-server verified per section, then **push** all to GitHub.

## After push (Hratch's manual items, not code)
- Bondi `drive_config` sender fix (workstream C note).
- Session 2 credential rotation (`JWT_SECRET` etc.) — still outstanding.
- Then tell Cowork to post the consolidated Notion Session Log covering: Session 1 smoke-test, service-type fix, watcher button, email Reply-To + status-tracking fix.

## Out of scope (do not touch)
- Light/dark theme toggle (Session 4, known infrastructure-only).
- Border-scan processing failing in test (environment-gated, expected).
- Store-scoped watcher triggering (noted as a possible future follow-up).
