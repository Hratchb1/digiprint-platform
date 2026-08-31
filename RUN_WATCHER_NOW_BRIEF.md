# RollCall — Fix Brief: "Run Watcher Now" Button (Session 4 — Ops Usability)

**Prepared 11 Aug 2026.** Requested during Session 2 testing — staff (and Hratch) want to force a Drive-watcher run on demand instead of waiting for the 5-minute scheduled cycle. This feature does **not** exist yet; this brief is the build.

Real backend entry point: `app/main.py`. Standing prefs: full-file replacements, incremental, dev-server verify before commit.

---

## Current state (verified 11 Aug 2026)

- **Backend force-run endpoint already exists:** `POST /api/drive/sync` → `manual_drive_sync()` in `backend/app/api/drive.py:90`, which awaits `run_drive_watcher()`. So the capability is there; it's just not reachable from the app.
- **Frontend cannot call it:** `driveApi` in `frontend/src/lib/api.ts:114` only exposes `logForOrder` and `clearLogEntry` — there is no `sync` method.
- **No UI button** anywhere triggers it.
- **No run-level concurrency guard:** `run_drive_watcher()` (`backend/app/services/drive_watcher.py:388`) has no whole-cycle lock. The only guarding is per-folder inside `_process_store`. A manual trigger fired while the 5-minute scheduled cycle is mid-run would start a second, overlapping cycle. (The Session 4 plan assumed "guard concurrent runs via existing lock" — that lock does not currently exist and must be added.)

---

## What to build

### 1. Backend — add a run-level concurrency guard
In `drive_watcher.py`, add a module-level `asyncio.Lock` (or a simple `_is_running` flag) around the body of `run_drive_watcher()`. If a cycle is already running, a second invocation should **no-op and return immediately** (log "watcher already running — skipped"), not queue or overlap. Both the scheduler job and the manual endpoint call the same guarded function, so the scheduled 5-min cycle is protected too.

Have `manual_drive_sync` return a clear signal of what happened, e.g. `{"status": "started"}` vs `{"status": "already_running"}`, so the UI can message accurately.

### 2. Frontend — plumb the endpoint
Add to `driveApi` in `api.ts`:
```
sync: () => api.post('/drive/sync').then(r => r.data),
```

### 3. Frontend — the button
Add a **"Run watcher now"** button. Natural spot: the Dashboard header (visible to all staff) — implementer's call between there and the Orders page header. Behaviour:
- Disabled + spinner/label ("Running…") while the request is in flight.
- Toast on completion — success ("Watcher run complete") vs the already-running case ("Watcher is already running — try again shortly").
- Re-enable when done.

---

## Note (raise, don't silently decide)
`manual_drive_sync` runs **every enabled store's** watcher (it loops all `drive_config` rows with `enabled=true`), and the drive endpoints are not store-scoped — so a store login (`store_admin`) hitting the button kicks off all stores, not just its own. This is fine for now (the watcher is global by design and idempotent per folder), but flag it as a conscious choice. If store-scoped triggering is ever wanted, that's a follow-up — don't build it blind here.

---

## Verify
1. Dev server: click "Run watcher now" → button disables, request fires `POST /api/drive/sync`, toast on completion.
2. With the 5-min scheduler active, click the button mid-cycle (or click it twice fast) → the second run **no-ops** with the "already running" path; confirm the backend log shows the skip and no overlapping cycle ran.
3. Drop a real scan folder in a store Inbox, click the button → confirm it's picked up immediately instead of waiting for the next scheduled cycle.

## Done
- Button works, guarded against concurrent/overlapping runs, clear user feedback.
- Commit + push; add a one-line Session 4 note to the Notion Session Logs.

## Out of scope
- Store-scoped watcher triggering (noted above as a possible follow-up).
- Any change to the watcher's actual processing logic (7-rule safety system stays as-is).
