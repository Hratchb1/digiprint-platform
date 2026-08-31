# RollCall store print agent

Standalone script that runs on the store PC connected to the label printer.
Polls the backend every 2 seconds for pending twin-check label jobs and
sends the ZPL straight to the printer over TCP port 9100. Not part of the
web app — no relation to uvicorn/APScheduler.

Uses only the Python standard library — nothing to `pip install`.

## Prerequisites

- Migration `009_twin_check_allocation.sql` has been run (creates
  `store_settings.print_agent_token`, which this agent authenticates with).
- Python 3.9+ installed on the store PC (check with `python --version`).
- The label printer is on the same network as this PC and reachable on port
  9100 (its usual ZPL raw-socket port).
- The backend API is reachable from this PC (either `http://localhost:8000/api`
  if running on the same machine, or the deployed Railway URL).

## Setup (PowerShell, run on the store PC)

1. Copy this folder (`backend/print_agent/`) to the store PC — or clone the
   whole repo if that's simpler; only this folder and `backend/twincheck/`
   (its sibling) are actually needed at runtime.

2. Get this store's print agent token. From the Supabase SQL Editor:

   ```sql
   SELECT s.name, ss.print_agent_token
   FROM store_settings ss
   JOIN stores s ON s.id = ss.store_id
   WHERE s.name = 'Bondi';   -- adjust per store
   ```

3. Copy the example config and fill it in:

   ```powershell
   Copy-Item config.example.json config.json
   notepad config.json
   ```

   Set `store_id` (from the `stores` table), `api_token` (from step 2),
   `printer_ip` (the label printer's IP address), and `api_base_url`
   (`http://localhost:8000/api` for local testing, or the deployed URL).

4. Test a single poll cycle (does nothing if the queue is empty — that's
   success, it means the connection and auth worked):

   ```powershell
   python agent.py --config config.json --once
   ```

   Check `print_agent.log` in this folder for the result.

5. Run it continuously:

   ```powershell
   python agent.py --config config.json
   ```

   Leave this running in a terminal window, or set it up to run at login —
   see below.

## Running at login (optional)

A minimal Task Scheduler entry, so the agent starts automatically without a
logged-in terminal:

```powershell
$action = New-ScheduledTaskAction -Execute "python.exe" `
  -Argument "agent.py --config config.json" `
  -WorkingDirectory "C:\path\to\backend\print_agent"
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "RollCall Print Agent" -Action $action -Trigger $trigger
```

To stop it: `Stop-ScheduledTask -TaskName "RollCall Print Agent"` (find the
running `python.exe` process and stop it, or unregister the task with
`Unregister-ScheduledTask -TaskName "RollCall Print Agent"`).

This is intentionally not a Windows Service — add one only if Task
Scheduler proves unreliable in the pilot (§6 of the build brief).

## Behaviour

- Polls `GET /api/print-queue?store_id=<id>` every 2 seconds (configurable
  via `poll_interval_seconds`).
- For each pending job: sends the ZPL to `printer_ip:printer_port`, retrying
  up to `max_send_retries` times with exponential backoff before giving up.
- On success: acks the job as `sent`.
- On failure (printer offline, unreachable, etc.): acks the job as `failed`
  with the error message. The ZPL is never lost — it stays on the
  server-side `print_jobs` row, and staff can use **Reprint** from the
  order's roll list once the printer is confirmed back up.
- Logs to `print_agent.log` in this folder (rotates at 1MB, keeps 5 backups)
  and to the console.

## Troubleshooting

- **401 Unauthorized**: `api_token` in `config.json` doesn't match
  `store_settings.print_agent_token` for this store — re-check step 2.
- **Could not reach `<url>`**: check `api_base_url` and that the backend is
  running and network-reachable from this PC.
- **Printer send failed / OSError**: check `printer_ip`/`printer_port` and
  that the printer is powered on and on the network — `Test-NetConnection
  -ComputerName <printer_ip> -Port 9100` from PowerShell is a quick check.
