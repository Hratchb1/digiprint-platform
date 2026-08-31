"""
RollCall store print agent.

Standalone script — NOT part of the FastAPI app, not imported by it, and
not started by uvicorn/APScheduler. Runs on the store's Windows PC (the one
with the label printer attached to the network), polling the backend for
pending print jobs and sending the rendered ZPL straight to the printer over
TCP 9100.

Deliberately simple: polling at 2s is indistinguishable from a push-based
design at ~85 jobs/day. No queueing, no printer status reporting, no
Windows service wrapper — add those only if polling proves inadequate in
the pilot.

Dependencies: Python 3.9+ standard library only (urllib, socket, logging) —
nothing to `pip install` on the store PC.

Usage:
    python agent.py --config config.json
    python agent.py --config config.json --once     # single poll cycle, for testing

See config.example.json for the config shape and README.md for setup.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# backend/twincheck/twincheck_label.py is a sibling package one level up —
# make it importable regardless of the working directory this script is
# launched from (double-click, Task Scheduler, or `python agent.py` from
# print_agent/ itself all land here differently).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from twincheck.twincheck_label import send_to_printer  # noqa: E402


DEFAULTS = {
    "poll_interval_seconds": 2,
    "max_send_retries": 5,
    "retry_backoff_seconds": 1.0,
    "http_timeout_seconds": 5.0,
    "log_file": "print_agent.log",
    "log_max_bytes": 1_048_576,
    "log_backup_count": 5,
    "printer_port": 9100,
}


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)
    merged = {**DEFAULTS, **config}
    for required in ("store_id", "api_base_url", "api_token", "printer_ip"):
        if not merged.get(required):
            raise ValueError(f"config missing required field: {required}")
    return merged


def setup_logging(config: dict) -> logging.Logger:
    logger = logging.getLogger("print_agent")
    logger.setLevel(logging.INFO)

    log_path = Path(config["log_file"])
    if not log_path.is_absolute():
        log_path = Path(__file__).resolve().parent / log_path

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=config["log_max_bytes"], backupCount=config["log_backup_count"],
    )
    console_handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler.setFormatter(fmt)
    console_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


class ApiError(Exception):
    pass


def _api_request(config: dict, method: str, path: str, body: Optional[dict] = None) -> dict:
    url = f"{config['api_base_url'].rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-Print-Agent-Token", config["api_token"])
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=config["http_timeout_seconds"]) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise ApiError(f"HTTP {e.code} from {method} {path}: {detail}") from e
    except urllib.error.URLError as e:
        raise ApiError(f"Could not reach {url}: {e.reason}") from e


def fetch_pending_jobs(config: dict) -> list[dict]:
    path = f"/print-queue?store_id={config['store_id']}"
    result = _api_request(config, "GET", path)
    # GET /print-queue returns a plain list per PrintQueueJobRead — see
    # backend/app/api/twin_checks.py.
    return result if isinstance(result, list) else result.get("jobs", [])


def ack_job(config: dict, job_id: str, status: str, error: Optional[str] = None) -> None:
    _api_request(config, "POST", f"/print-queue/{job_id}/ack", {"status": status, "error": error})


def send_with_retry(config: dict, zpl: str, logger: logging.Logger) -> tuple[bool, Optional[str]]:
    """
    Attempts to send `zpl` to the configured printer, retrying with
    exponential backoff on failure. Returns (success, last_error) — the ZPL
    itself is never discarded on failure; it stays on the server-side
    print_jobs row (status becomes 'failed', not deleted) so a Reprint can
    always regenerate it once the printer is confirmed back up.
    """
    last_error: Optional[str] = None
    for attempt in range(1, config["max_send_retries"] + 1):
        try:
            send_to_printer(zpl, config["printer_ip"], config["printer_port"])
            return True, None
        except OSError as e:
            last_error = str(e)
            logger.warning(
                f"Printer send failed (attempt {attempt}/{config['max_send_retries']}): {last_error}"
            )
            if attempt < config["max_send_retries"]:
                time.sleep(config["retry_backoff_seconds"] * (2 ** (attempt - 1)))
    return False, last_error


def run_once(config: dict, logger: logging.Logger) -> None:
    try:
        jobs = fetch_pending_jobs(config)
    except ApiError as e:
        logger.error(f"Could not fetch print queue: {e}")
        return

    for job in jobs:
        job_id = job["id"]
        zpl = job["zpl"]
        logger.info(f"Sending print job {job_id} ({len(zpl)} bytes ZPL)")

        success, error = send_with_retry(config, zpl, logger)

        try:
            if success:
                ack_job(config, job_id, "sent")
                logger.info(f"Job {job_id} sent and acked")
            else:
                ack_job(config, job_id, "failed", error)
                logger.error(f"Job {job_id} failed after retries: {error}")
        except ApiError as e:
            # The printer send outcome is already decided; a failed ack just
            # means the server won't know yet — it'll still show as
            # 'pending' and be re-fetched (and re-sent) next poll. Logged
            # loudly so a persistent ack failure (e.g. bad token) is visible.
            logger.error(f"Could not ack job {job_id} (success={success}): {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RollCall store print agent")
    parser.add_argument("--config", default="config.json", help="Path to config JSON")
    parser.add_argument("--once", action="store_true", help="Run a single poll cycle and exit (testing)")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path(__file__).resolve().parent / config_path

    config = load_config(config_path)
    logger = setup_logging(config)
    logger.info(f"Print agent starting — store {config['store_id']}, printer {config['printer_ip']}:{config['printer_port']}")

    if args.once:
        run_once(config, logger)
        return

    while True:
        try:
            run_once(config, logger)
        except Exception as e:
            # Never let an unexpected error kill the poll loop — log and
            # keep going, matching "recovers cleanly from the printer being
            # offline" as a general resilience posture, not just the one
            # documented failure mode.
            logger.exception(f"Unexpected error in poll cycle: {e}")
        time.sleep(config["poll_interval_seconds"])


if __name__ == "__main__":
    main()
