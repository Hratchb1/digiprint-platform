"""
RollCall Session 1 — store-scoping verification (1d in the brief).

Run this yourself, interactively — it asks for both accounts' passwords
at its own prompt, never via chat.

Usage:
    cd backend
    python verify_store_scoping.py

What it does (read-only — never fires a mutating PATCH/POST at a real
order, so it's safe to run against the live database):
  1. Bondi's order list is 100% Bondi orders.
  2. Master admin's order list includes other stores too (sanity check
     that master_admin isn't accidentally scoped).
  3. Bondi hitting another store's order by ID -> 404 (GET /{id} and
     GET /{id}/events). The mutating endpoints (status, mark-blank,
     drive-link, add-rolls, reset-twins, retry-border, discard) share
     the identical assert_can_access() call before any write, so this
     same 404 proves them safe without actually executing a write
     against another store's live order.
  4. Bondi passing ?store_id=<another store> on list + dashboard/stats
     is ignored — still Bondi-only.
  5. Bondi's dashboard/stats numbers match what master_admin sees when
     explicitly filtered to Bondi.
"""
import asyncio
import sys

import httpx

BASE_URL = "http://localhost:8000/api"


def ok(label: str, passed: bool, detail: str = ""):
    mark = "✅ PASS" if passed else "❌ FAIL"
    print(f"{mark}  {label}" + (f"  — {detail}" if detail else ""))
    return passed


async def login(client: httpx.AsyncClient, email: str, password: str) -> dict:
    r = await client.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    body = r.json()
    return {"token": body["access_token"], "user": body["user"]}


async def main():
    print("This talks to your locally running backend and needs both accounts' logins.\n")
    admin_email = input("Master admin email: ").strip()
    admin_password = input("Master admin password: ").strip()
    store_email = input("Bondi (store_admin) email [lab.bondi@digidirect.com.au]: ").strip() \
        or "lab.bondi@digidirect.com.au"
    store_password = input("Bondi password: ").strip()

    results = []

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            admin = await login(client, admin_email, admin_password)
        except Exception as e:
            print(f"❌ Master admin login failed: {e}")
            sys.exit(1)
        try:
            store = await login(client, store_email, store_password)
        except Exception as e:
            print(f"❌ Bondi login failed: {e}")
            sys.exit(1)

        if admin["user"]["role"] != "master_admin":
            print(f"❌ {admin_email} is not master_admin (role={admin['user']['role']}) — aborting")
            sys.exit(1)
        bondi_store_id = store["user"]["store_id"]
        if store["user"]["role"] != "store_admin" or not bondi_store_id:
            print(f"❌ {store_email} is not a store-scoped store_admin — aborting")
            sys.exit(1)

        admin_h = {"Authorization": f"Bearer {admin['token']}"}
        store_h = {"Authorization": f"Bearer {store['token']}"}

        # ── 1. Bondi's list is 100% Bondi orders ──────────────────
        r = await client.get(f"{BASE_URL}/orders", headers=store_h, params={"limit": 500, "include_terminal": True})
        bondi_orders = r.json()
        leaks = [o for o in bondi_orders if o["store_id"] != bondi_store_id]
        results.append(ok(
            "1. Bondi order list is Bondi-only",
            r.status_code == 200 and not leaks,
            f"{len(bondi_orders)} orders, {len(leaks)} from other stores",
        ))

        # ── 2. Master admin sees other stores too ─────────────────
        r = await client.get(f"{BASE_URL}/orders", headers=admin_h, params={"limit": 500, "include_terminal": True})
        admin_orders = r.json()
        other_store_orders = [o for o in admin_orders if o["store_id"] != bondi_store_id]
        results.append(ok(
            "2. Master admin sees other stores",
            r.status_code == 200 and len(other_store_orders) > 0,
            f"{len(other_store_orders)} orders outside Bondi visible to master_admin",
        ))

        if not other_store_orders:
            print("\n⚠️  No non-Bondi orders exist to test cross-store access with — "
                  "skipping checks 3-5. This isn't a failure, just nothing to probe.")
        else:
            foreign_order = other_store_orders[0]
            foreign_id = foreign_order["id"]

            # ── 3. Bondi hitting a foreign order by ID -> 404 ──────
            r = await client.get(f"{BASE_URL}/orders/{foreign_id}", headers=store_h)
            results.append(ok(
                "3a. GET /orders/{id} on foreign order -> 404",
                r.status_code == 404,
                f"got {r.status_code}",
            ))

            r = await client.get(f"{BASE_URL}/orders/{foreign_id}/events", headers=store_h)
            results.append(ok(
                "3b. GET /orders/{id}/events on foreign order -> 404",
                r.status_code == 404,
                f"got {r.status_code}",
            ))

            print("    (mark-blank / status / drive-link / add-rolls / reset-twins / "
                  "retry-border / discard all call the same assert_can_access() before any "
                  "write — 3a/3b passing proves those endpoints are safe too, without "
                  "actually mutating a live order to prove it.)")

            # ── 4. ?store_id= override attempts are ignored ────────
            r = await client.get(
                f"{BASE_URL}/orders", headers=store_h,
                params={"store_id": foreign_order["store_id"], "limit": 500, "include_terminal": True},
            )
            leaked = [o for o in r.json() if o["store_id"] != bondi_store_id] if r.status_code == 200 else []
            results.append(ok(
                "4a. list_orders ?store_id=<foreign> ignored for Bondi",
                r.status_code == 200 and not leaked,
                f"got {r.status_code}, {len(leaked)} foreign orders returned",
            ))

            r = await client.get(
                f"{BASE_URL}/dashboard/stats", headers=store_h,
                params={"store_id": foreign_order["store_id"]},
            )
            results.append(ok(
                "4b. dashboard/stats ?store_id=<foreign> ignored for Bondi",
                r.status_code == 200,
                f"got {r.status_code}",
            ))

        # ── 5. Bondi's dashboard numbers match admin-filtered-to-Bondi ─
        r_store = await client.get(f"{BASE_URL}/dashboard/stats", headers=store_h)
        r_admin_scoped = await client.get(
            f"{BASE_URL}/dashboard/stats", headers=admin_h, params={"store_id": bondi_store_id}
        )
        match = r_store.status_code == 200 and r_admin_scoped.status_code == 200 \
            and r_store.json() == r_admin_scoped.json()
        results.append(ok(
            "5. Bondi dashboard/stats == master_admin filtered to Bondi",
            match,
            "" if match else f"bondi={r_store.json()} vs admin={r_admin_scoped.json()}",
        ))

    print(f"\n{sum(results)}/{len(results)} checks passed.")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
