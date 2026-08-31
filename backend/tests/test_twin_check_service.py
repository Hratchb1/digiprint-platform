"""
tests/test_twin_check_service.py
=================================
Unit tests for twin_check_service's pure logic, plus an optional live-DB
concurrency test for the allocate_twin_checks() Postgres function.

Run from digiprint/backend/ with:
    pytest tests/test_twin_check_service.py -v

The compute_process_mix tests need no DB connection — pure function, mocked
inputs, matching the existing repo convention (see test_pronto_sync.py).

The concurrency test opens two real asyncpg connections against
settings.DATABASE_URL and is skipped automatically if that's unreachable
(e.g. no .env configured, offline dev). It creates a throwaway store +
twin_check_sequences row, allocates through it from two connections in
parallel, asserts the two blocks never overlap, then deletes the throwaway
row — it never touches a real store's sequence.
"""

import asyncio
import uuid

import pytest

from app.services.twin_check_service import compute_process_mix


# ── compute_process_mix — the regression test that matters most ───────────
# "An order booked as DEV135 x 5 plus SCAN135 x 5 for the same five rolls
# allocates exactly five numbers, not ten." (acceptance criterion #10)

SKU_MAP = {
    "100020": {"requires_twin_check": True, "process_code": "C41"},
    "100003": {"requires_twin_check": True, "process_code": "C41"},
    "122191": {"requires_twin_check": True, "process_code": "BW"},
    "100008": {"requires_twin_check": True, "process_code": "BW"},
    "120152": {"requires_twin_check": True, "process_code": "RSC"},
    # Scanning add-ons ride along on an already twin-checked roll — NOT flagged.
    "123242": {"requires_twin_check": False, "process_code": None},
    "123243": {"requires_twin_check": False, "process_code": None},
    "123244": {"requires_twin_check": False, "process_code": None},
    "100022": {"requires_twin_check": False, "process_code": None},
    "100024": {"requires_twin_check": False, "process_code": None},
    # A SKU with requires_twin_check=True but no process_code configured yet.
    "999999": {"requires_twin_check": True, "process_code": None},
}


def _line(sku_code: str, qty: int) -> dict:
    return {"sku_code": sku_code, "shipped_units": qty}


class TestNoDoubleCount:
    def test_dev_plus_scan_same_five_rolls_counts_five_not_ten(self):
        """The exact scenario the brief calls out: Dev SKU x5 + its
        accompanying Scan SKU x5 for the same five physical rolls must
        allocate 5, not 10."""
        sku_lines = [_line("100020", 5), _line("123242", 5)]
        result = compute_process_mix(sku_lines, SKU_MAP)
        assert result["total"] == 5
        assert result["mix"] == [{"process_code": "C41", "count": 5}]
        assert result["unmapped"] is False

    def test_dev_scan_print_three_line_items_still_counts_rolls_once(self):
        sku_lines = [_line("100020", 3), _line("123242", 3), _line("100024", 3)]
        result = compute_process_mix(sku_lines, SKU_MAP)
        assert result["total"] == 3

    def test_scan_only_addon_alone_counts_zero(self):
        """A scan-only add-on with no accompanying Dev line (shouldn't
        happen commercially, but must never allocate on its own)."""
        sku_lines = [_line("123242", 5)]
        result = compute_process_mix(sku_lines, SKU_MAP)
        assert result["total"] == 0
        assert result["mix"] == []


class TestMixedProcess:
    def test_mixed_c41_and_bw_grouped_separately(self):
        sku_lines = [_line("100020", 3), _line("122191", 2)]
        result = compute_process_mix(sku_lines, SKU_MAP)
        assert result["total"] == 5
        assert {"process_code": "C41", "count": 3} in result["mix"]
        assert {"process_code": "BW", "count": 2} in result["mix"]


class TestRescanSku:
    def test_cut_neg_rescan_sku_allocates_and_maps_to_rsc(self):
        sku_lines = [_line("120152", 2)]
        result = compute_process_mix(sku_lines, SKU_MAP)
        assert result["total"] == 2
        assert result["mix"] == [{"process_code": "RSC", "count": 2}]


class TestUnmappedAndUnflagged:
    def test_print_only_order_allocates_nothing(self):
        sku_lines = [_line("100024", 2)]
        result = compute_process_mix(sku_lines, SKU_MAP)
        assert result["total"] == 0
        assert result["unmapped"] is False

    def test_flagged_sku_with_null_process_code_sets_unmapped_flag(self):
        """Never default to C41 — the caller must block and prompt."""
        sku_lines = [_line("999999", 4)]
        result = compute_process_mix(sku_lines, SKU_MAP)
        assert result["total"] == 4
        assert result["unmapped"] is True

    def test_sku_not_in_sku_map_at_all_is_ignored(self):
        sku_lines = [_line("000000", 7)]
        result = compute_process_mix(sku_lines, SKU_MAP)
        assert result["total"] == 0
        assert result["unmapped"] is False

    def test_no_deploy_needed_for_a_new_flagged_sku(self):
        """Adding a SKU to the sku_map dict with requires_twin_check=True
        changes allocation immediately — no code path here references a
        specific SKU code (criterion #11b)."""
        extended = dict(SKU_MAP)
        extended["555555"] = {"requires_twin_check": True, "process_code": "C41"}
        result = compute_process_mix([_line("555555", 6)], extended)
        assert result["total"] == 6


# ── Concurrency — allocate_twin_checks() must never overlap under load ────
# (acceptance criterion #1). Requires a live DATABASE_URL; skipped otherwise.

def _database_url():
    try:
        from app.core.config import settings
        return settings.DATABASE_URL
    except Exception:
        return None


async def _pg_reachable(dsn: str) -> bool:
    try:
        import asyncpg
        conn = await asyncio.wait_for(asyncpg.connect(dsn.replace("+asyncpg", "")), timeout=3)
        await conn.close()
        return True
    except Exception:
        return False


def _db_available() -> bool:
    dsn = _database_url()
    if not dsn:
        return False
    try:
        return asyncio.run(_pg_reachable(dsn))
    except Exception:
        return False


@pytest.mark.skipif(not _db_available(), reason="No reachable DATABASE_URL — skipping live concurrency test")
class TestConcurrentAllocation:
    def test_parallel_allocations_never_overlap(self):
        asyncio.run(self._run())

    async def _run(self):
        import asyncpg
        dsn = _database_url().replace("+asyncpg", "")

        setup_conn = await asyncpg.connect(dsn)
        test_store_id = str(uuid.uuid4())
        try:
            # Throwaway store + sequence row — never touches a real store.
            await setup_conn.execute(
                "INSERT INTO stores (id, name, label, email, is_active) "
                "VALUES ($1, $2, $2, 'test@example.com', true)",
                test_store_id, f"__test_store_{test_store_id[:8]}",
            )
            await setup_conn.execute(
                "INSERT INTO twin_check_sequences (store_id) VALUES ($1)",
                test_store_id,
            )

            async def allocate(n: int):
                conn = await asyncpg.connect(dsn)
                try:
                    rows = await conn.fetch(
                        "SELECT number, cycle FROM allocate_twin_checks($1, $2)",
                        test_store_id, n,
                    )
                    return [(r["number"], r["cycle"]) for r in rows]
                finally:
                    await conn.close()

            # 10 parallel callers each grabbing a block of 5 — 50 numbers
            # total. If the row lock in allocate_twin_checks() failed to
            # serialise these, some numbers would repeat across callers.
            results = await asyncio.gather(*[allocate(5) for _ in range(10)])

            all_numbers = [n for block in results for (n, _cycle) in block]
            assert len(all_numbers) == 50
            assert len(set(all_numbers)) == 50, "Overlapping numbers allocated under concurrency"

            # Each individual block must itself be contiguous.
            for block in results:
                numbers = sorted(n for n, _ in block)
                assert numbers == list(range(numbers[0], numbers[0] + 5))
        finally:
            await setup_conn.execute("DELETE FROM twin_checks WHERE store_id = $1", test_store_id)
            await setup_conn.execute("DELETE FROM twin_check_sequences WHERE store_id = $1", test_store_id)
            await setup_conn.execute("DELETE FROM stores WHERE id = $1", test_store_id)
            await setup_conn.close()
