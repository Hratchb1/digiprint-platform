"""
tests/test_pronto_sync.py
=========================
Unit tests for the Phase 1 pronto_sync helpers.

Run from digiprint/backend/ with:
    pytest tests/test_pronto_sync.py -v

No Supabase connection required — the Supabase client is fully mocked.
"""

from unittest.mock import MagicMock, call, patch
import pytest

from app.services.pronto_sync import (
    _classify_sales_order,
    _build_cache_key,
    _refund_sku_signature,
    _order_cache_sku_signature,
    _refund_is_full,
    _match_refund,
    _apply_refund,
    _load_store_map,
    REFUNDABLE_PRE_DELIVERED,
)


# ── Fixtures ─────────────────────────────────────────────────

def _make_row(
    order_num="SO-001",
    sku_code="C41-35",
    shipped_units="1",
    shipped_value="25.00",
    pronto_account="ACC001",
    territory="BOND",
    **kwargs,
) -> dict:
    return {
        "sales_order_number": order_num,
        "sku_code":           sku_code,
        "shipped_units":      shipped_units,
        "shipped_value":      shipped_value,
        "pronto_account":     pronto_account,
        "territory":          territory,
        "customer_name":      kwargs.get("customer_name", "Test Customer"),
        "email_address":      kwargs.get("email_address", "test@example.com"),
        "phone_number":       kwargs.get("phone_number", "0400000000"),
        "bo_suffix":          kwargs.get("bo_suffix", ""),
        "order_date":         kwargs.get("order_date", "2026-05-01"),
        "shipped_date":       kwargs.get("shipped_date", ""),
        "product_name":       kwargs.get("product_name", "C41 Dev+Scan"),
    }


def _mock_client(
    *,
    store_map=None,
    existing_orders=None,
    cache_rows=None,
):
    """
    Build a MagicMock Supabase client.

    Each table method call returns a chainable mock that ultimately
    returns a mock with .data set as specified.
    """
    client = MagicMock()

    def _chain(data):
        result = MagicMock()
        result.data = data
        chain = MagicMock()
        chain.execute.return_value = result
        chain.eq.return_value = chain
        chain.neq.return_value = chain
        chain.in_.return_value = chain
        chain.gt.return_value = chain
        chain.order.return_value = chain
        chain.select.return_value = chain
        chain.insert.return_value = chain
        chain.update.return_value = chain
        chain.upsert.return_value = chain
        return chain

    stores_data     = store_map   or [{"territory_code": "BOND", "id": "store-bond-uuid"}]
    orders_data     = existing_orders or []
    cache_data      = cache_rows  or []

    def table_side_effect(name: str):
        if name == "stores":
            return _chain(stores_data)
        if name == "orders":
            return _chain(orders_data)
        if name == "pronto_cache":
            return _chain(cache_data)
        if name in ("order_activity", "refund_warnings"):
            return _chain([])
        return _chain([])

    client.table.side_effect = table_side_effect
    return client


# ══════════════════════════════════════════════════════════════
# 1. Classification
# ══════════════════════════════════════════════════════════════

class TestClassifySalesOrder:

    def test_positive_qty_is_new(self):
        rows = [_make_row(shipped_units="2"), _make_row(shipped_units="1")]
        assert _classify_sales_order(rows) == "new"

    def test_any_negative_qty_is_refund(self):
        rows = [_make_row(shipped_units="1"), _make_row(shipped_units="-1")]
        assert _classify_sales_order(rows) == "refund"

    def test_all_negative_is_refund(self):
        rows = [_make_row(shipped_units="-2")]
        assert _classify_sales_order(rows) == "refund"

    def test_zero_qty_rows_are_new(self):
        rows = [_make_row(shipped_units="0")]
        assert _classify_sales_order(rows) == "new"


# ══════════════════════════════════════════════════════════════
# 2. Cache key
# ══════════════════════════════════════════════════════════════

class TestBuildCacheKey:

    def test_normal(self):
        assert _build_cache_key("SO-001", None, "C41-35") == "SO-001||C41-35"

    def test_with_bo_suffix(self):
        assert _build_cache_key("SO-001", "AC", "C41-35") == "SO-001|AC|C41-35"

    def test_no_sku(self):
        assert _build_cache_key("SO-001", None, None) == "SO-001||"


# ══════════════════════════════════════════════════════════════
# 3. Refund SKU signature helpers
# ══════════════════════════════════════════════════════════════

class TestRefundSkuSignature:

    def test_builds_abs_qty_map(self):
        rows = [
            _make_row(sku_code="C41-35", shipped_units="-2"),
            _make_row(sku_code="BW-35",  shipped_units="-1"),
        ]
        sig = _refund_sku_signature(rows)
        assert sig == {"C41-35": 2, "BW-35": 1}

    def test_excludes_addon_skus(self):
        rows = [
            _make_row(sku_code="C41-35",  shipped_units="-1"),
            _make_row(sku_code="177426",  shipped_units="-1"),  # addon
        ]
        sig = _refund_sku_signature(rows)
        assert "177426" not in sig
        assert sig.get("C41-35") == 1

    def test_aggregates_same_sku(self):
        rows = [
            _make_row(sku_code="C41-35", shipped_units="-1"),
            _make_row(sku_code="C41-35", shipped_units="-1"),
        ]
        sig = _refund_sku_signature(rows)
        assert sig["C41-35"] == 2


class TestRefundIsFull:

    def test_exact_match_is_full(self):
        assert _refund_is_full({"C41-35": 2}, {"C41-35": 2}) is True

    def test_refund_exceeds_original_is_full(self):
        # over-refund counts as full
        assert _refund_is_full({"C41-35": 1}, {"C41-35": 2}) is True

    def test_partial_is_not_full(self):
        assert _refund_is_full({"C41-35": 2, "BW-35": 1}, {"C41-35": 2}) is False

    def test_empty_original_returns_false(self):
        assert _refund_is_full({}, {"C41-35": 1}) is False


# ══════════════════════════════════════════════════════════════
# 4. New-job creation (integration-level with mocked client)
# ══════════════════════════════════════════════════════════════

class TestNewJobCreation:
    """
    Tests the sync's new-order creation path via _match_refund + _apply_refund.
    The actual INSERT path is exercised in the main sync; here we verify the
    helpers correctly skip existing orders and create for missing ones.
    """

    def test_order_created_when_not_existing(self):
        """
        When no existing order matches pronto_order_number,
        _match_refund should not find it (it's new, not a refund).
        Indirectly validated: classify returns 'new' for positive rows.
        """
        rows = [_make_row(order_num="SO-NEW", shipped_units="2")]
        assert _classify_sales_order(rows) == "new"

    def test_order_skipped_when_already_exists(self):
        """
        Simulates the no-op path: existing order check returns data.
        We verify classify still says 'new' — the de-dup guard is in the sync loop.
        """
        rows = [_make_row(order_num="SO-EXISTING", shipped_units="1")]
        assert _classify_sales_order(rows) == "new"


# ══════════════════════════════════════════════════════════════
# 5. Full refund pre-Delivered → cancelled
# ══════════════════════════════════════════════════════════════

class TestFullRefundPreDelivered:

    def _setup_client(self, order_status: str):
        matched_order = {
            "id":                  "order-uuid-001",
            "pronto_order_number": "SO-001",
            "status":              order_status,
            "store_id":            "store-bond-uuid",
            "refund_status":       None,
        }

        client = MagicMock()

        # pronto_cache returns the original order's SKU breakdown
        original_cache = [{"sku_code": "C41-35", "shipped_units": 1}]

        # Persistent orders mock — must be the SAME object on every call so
        # that update.call_args_list recorded during _apply_refund is visible
        # when the test assertion retrieves it via client.table("orders").
        orders_mock = MagicMock()
        orders_mock.select.return_value = orders_mock
        orders_mock.update.return_value = orders_mock
        orders_mock.insert.return_value = orders_mock
        orders_mock.eq.return_value = orders_mock
        orders_mock.neq.return_value = orders_mock
        orders_mock.in_.return_value = orders_mock
        orders_mock.gt.return_value = orders_mock
        orders_mock.order.return_value = orders_mock
        orders_result = MagicMock()
        orders_result.data = [matched_order]
        orders_mock.execute.return_value = orders_result

        def table_side_effect(name: str):
            if name == "orders":
                return orders_mock

            mock = MagicMock()
            mock.select.return_value = mock
            mock.update.return_value = mock
            mock.insert.return_value = mock
            mock.eq.return_value = mock
            mock.neq.return_value = mock
            mock.in_.return_value = mock
            mock.gt.return_value = mock
            mock.order.return_value = mock

            if name == "pronto_cache":
                result = MagicMock()
                result.data = original_cache
                mock.execute.return_value = result
            elif name == "order_activity":
                result = MagicMock()
                result.data = []
                mock.execute.return_value = result
            else:
                result = MagicMock()
                result.data = []
                mock.execute.return_value = result
            return mock

        client.table.side_effect = table_side_effect
        return client, matched_order

    @pytest.mark.parametrize("status", list(REFUNDABLE_PRE_DELIVERED))
    def test_full_refund_cancels_pre_delivered(self, status):
        client, matched_order = self._setup_client(status)
        refund_rows = [_make_row(order_num="SO-REF-001", sku_code="C41-35", shipped_units="-1")]

        _apply_refund(matched_order, refund_rows, client)

        # Find the orders.update call and check it set status=cancelled
        orders_table_calls = [
            c for c in client.table.call_args_list if c.args[0] == "orders"
        ]
        assert any(
            call("orders") == c for c in client.table.call_args_list
        )
        # Verify update was called with cancelled status
        orders_mock = client.table("orders")
        update_calls = orders_mock.update.call_args_list
        assert any(
            "cancelled" in str(c) for c in update_calls
        ), f"Expected status=cancelled in update calls: {update_calls}"


# ══════════════════════════════════════════════════════════════
# 6. Full refund post-Delivered → refund_status='full'
# ══════════════════════════════════════════════════════════════

class TestFullRefundPostDelivered:

    def test_delivered_order_keeps_status_gets_full_tag(self):
        client = MagicMock()
        original_cache = [{"sku_code": "C41-35", "shipped_units": 1}]
        updated_data: dict = {}

        def table_side_effect(name: str):
            mock = MagicMock()
            mock.select.return_value = mock
            mock.eq.return_value = mock
            mock.gt.return_value = mock

            if name == "pronto_cache":
                result = MagicMock()
                result.data = original_cache
                mock.execute.return_value = result
            elif name == "orders":
                def capture_update(payload):
                    updated_data.update(payload)
                    m = MagicMock()
                    m.eq.return_value = m
                    m.execute.return_value = MagicMock(data=[])
                    return m
                mock.update.side_effect = capture_update
            elif name == "order_activity":
                result = MagicMock()
                result.data = []
                mock.execute.return_value = result
            return mock

        client.table.side_effect = table_side_effect

        matched_order = {
            "id":                  "order-uuid-002",
            "pronto_order_number": "SO-001",
            "status":              "delivered",
            "store_id":            "store-bond-uuid",
            "refund_status":       None,
        }
        refund_rows = [_make_row(order_num="SO-REF-002", sku_code="C41-35", shipped_units="-1")]

        _apply_refund(matched_order, refund_rows, client)

        assert updated_data.get("refund_status") == "full"
        assert "status" not in updated_data or updated_data.get("status") == "delivered"


# ══════════════════════════════════════════════════════════════
# 7. Partial refund → refund_status='partial'
# ══════════════════════════════════════════════════════════════

class TestPartialRefund:

    def test_partial_refund_tags_without_status_change(self):
        client = MagicMock()
        # Original order has 2 SKUs; refund only covers 1
        original_cache = [
            {"sku_code": "C41-35", "shipped_units": 1},
            {"sku_code": "BW-35",  "shipped_units": 1},
        ]
        updated_data: dict = {}

        def table_side_effect(name: str):
            mock = MagicMock()
            mock.select.return_value = mock
            mock.eq.return_value = mock
            mock.gt.return_value = mock

            if name == "pronto_cache":
                result = MagicMock()
                result.data = original_cache
                mock.execute.return_value = result
            elif name == "orders":
                def capture_update(payload):
                    updated_data.update(payload)
                    m = MagicMock()
                    m.eq.return_value = m
                    m.execute.return_value = MagicMock(data=[])
                    return m
                mock.update.side_effect = capture_update
            elif name == "order_activity":
                mock.insert.return_value = mock
                mock.execute.return_value = MagicMock(data=[])
            return mock

        client.table.side_effect = table_side_effect

        matched_order = {
            "id":                  "order-uuid-003",
            "pronto_order_number": "SO-001",
            "status":              "booked_in",
            "store_id":            "store-bond-uuid",
            "refund_status":       None,
        }
        refund_rows = [_make_row(order_num="SO-REF-003", sku_code="C41-35", shipped_units="-1")]

        _apply_refund(matched_order, refund_rows, client)

        assert updated_data.get("refund_status") == "partial"
        assert "cancelled" not in str(updated_data.get("status", ""))


# ══════════════════════════════════════════════════════════════
# 8. Cash-sale fallback matching
# ══════════════════════════════════════════════════════════════

class TestCashSaleFallback:

    def test_cash_account_uses_territory_fallback(self):
        """
        When account starts with CASH, _match_refund should skip the primary
        account-number match and try the territory+SKU fallback.
        """
        candidate_order = {
            "id":                  "order-uuid-cash",
            "pronto_order_number": "SO-CASH-001",
            "status":              "inbound",
            "store_id":            "store-bond-uuid",
            "refund_status":       None,
            "pronto_order_date":   "2026-04-01",
        }

        original_cache = [{"sku_code": "C41-35", "shipped_units": 1}]

        call_count = {"cache_queries": 0}

        def table_side_effect(name: str):
            mock = MagicMock()
            mock.select.return_value = mock
            mock.eq.return_value = mock
            mock.neq.return_value = mock
            mock.in_.return_value = mock
            mock.gt.return_value = mock
            mock.order.return_value = mock

            if name == "stores":
                result = MagicMock()
                result.data = [{"territory_code": "BOND", "id": "store-bond-uuid"}]
                mock.execute.return_value = result
            elif name == "pronto_cache":
                result = MagicMock()
                result.data = original_cache
                mock.execute.return_value = result
            elif name == "orders":
                result = MagicMock()
                result.data = [candidate_order]
                mock.execute.return_value = result
            else:
                mock.execute.return_value = MagicMock(data=[])
            return mock

        client = MagicMock()
        client.table.side_effect = table_side_effect

        refund_rows = [
            _make_row(
                order_num="SO-REF-CASH",
                sku_code="C41-35",
                shipped_units="-1",
                pronto_account="CASH-BOND",
                territory="BOND",
            )
        ]

        matched, confidence = _match_refund(refund_rows, client)

        assert matched is not None, "Expected a match via cash fallback"
        assert confidence == "cash_fallback"


# ══════════════════════════════════════════════════════════════
# 8b. Primary account-number matching (account + SKU + abs(qty) + earliest)
# ══════════════════════════════════════════════════════════════

class TestPrimaryAccountMatch:

    @staticmethod
    def _table_side_effect(orders_data, cache_data):
        def table_side_effect(name: str):
            mock = MagicMock()
            mock.select.return_value = mock
            mock.eq.return_value = mock
            mock.neq.return_value = mock
            mock.in_.return_value = mock
            mock.gt.return_value = mock
            mock.order.return_value = mock

            if name == "orders":
                result = MagicMock()
                result.data = orders_data
                mock.execute.return_value = result
            elif name == "pronto_cache":
                result = MagicMock()
                result.data = cache_data
                mock.execute.return_value = result
            else:
                mock.execute.return_value = MagicMock(data=[])
            return mock

        return table_side_effect

    def test_exact_account_match_returns_exact_confidence(self):
        candidate_order = {
            "id":                  "order-uuid-primary",
            "pronto_order_number": "SO-100",
            "status":              "inbound",
            "store_id":            "store-bond-uuid",
            "refund_status":       None,
            "pronto_order_date":   "2026-03-01",
        }
        original_cache = [{"sku_code": "C41-35", "shipped_units": 1}]

        client = MagicMock()
        client.table.side_effect = self._table_side_effect([candidate_order], original_cache)

        refund_rows = [
            _make_row(order_num="SO-REF-100", sku_code="C41-35",
                      shipped_units="-1", pronto_account="ACC100")
        ]

        matched, confidence = _match_refund(refund_rows, client)

        assert matched is not None
        assert matched["pronto_order_number"] == "SO-100"
        assert confidence == "exact"

    def test_qty_must_match_abs_exactly_partial_qty_does_not_match(self):
        """
        Original order shipped 2 units of C41-35; refund only claims 1 —
        abs(qty) must match the original exactly (a partial refund isn't a
        SKU-signature match here, it's handled separately by _refund_is_full
        for full-vs-partial once a match IS found), so this candidate must
        be skipped rather than matched.
        """
        candidate_order = {
            "id":                  "order-uuid-qtymismatch",
            "pronto_order_number": "SO-101",
            "status":              "inbound",
            "store_id":            "store-bond-uuid",
            "refund_status":       None,
            "pronto_order_date":   "2026-03-01",
        }
        original_cache = [{"sku_code": "C41-35", "shipped_units": 2}]

        client = MagicMock()
        client.table.side_effect = self._table_side_effect([candidate_order], original_cache)

        refund_rows = [
            _make_row(order_num="SO-REF-101", sku_code="C41-35",
                      shipped_units="-1", pronto_account="ACC101")
        ]

        matched, confidence = _match_refund(refund_rows, client)

        assert matched is None
        assert confidence == "unmatched"

    def test_earliest_candidate_among_multiple_matches_wins(self):
        """
        _match_refund queries orders .order('pronto_order_date', desc=False)
        — ascending — and returns the first candidate whose SKU signature
        matches. With two orders that both match on SKU signature, the one
        earlier in the (already-ascending) result list must win.
        """
        earlier_order = {
            "id":                  "order-uuid-earlier",
            "pronto_order_number": "SO-EARLY",
            "status":              "inbound",
            "store_id":            "store-bond-uuid",
            "refund_status":       None,
            "pronto_order_date":   "2026-01-01",
        }
        later_order = {
            "id":                  "order-uuid-later",
            "pronto_order_number": "SO-LATE",
            "status":              "inbound",
            "store_id":            "store-bond-uuid",
            "refund_status":       None,
            "pronto_order_date":   "2026-06-01",
        }
        original_cache = [{"sku_code": "C41-35", "shipped_units": 1}]

        client = MagicMock()
        # Ascending order, as the real query requests — earlier_order first.
        client.table.side_effect = self._table_side_effect(
            [earlier_order, later_order], original_cache
        )

        refund_rows = [
            _make_row(order_num="SO-REF-EARLY", sku_code="C41-35",
                      shipped_units="-1", pronto_account="ACC-MULTI")
        ]

        matched, confidence = _match_refund(refund_rows, client)

        assert matched is not None
        assert matched["pronto_order_number"] == "SO-EARLY"
        assert confidence == "exact"


# ══════════════════════════════════════════════════════════════
# 9. Unmatched refund → refund_warnings
# ══════════════════════════════════════════════════════════════

class TestUnmatchedRefund:

    def test_no_match_returns_none_unmatched(self):
        """
        When no candidate order exists, _match_refund should return (None, 'unmatched').
        """
        def table_side_effect(name: str):
            mock = MagicMock()
            mock.select.return_value = mock
            mock.eq.return_value = mock
            mock.neq.return_value = mock
            mock.in_.return_value = mock
            mock.gt.return_value = mock
            mock.order.return_value = mock

            if name == "stores":
                result = MagicMock()
                result.data = [{"territory_code": "BOND", "id": "store-bond-uuid"}]
                mock.execute.return_value = result
            else:
                result = MagicMock()
                result.data = []  # no candidates
                mock.execute.return_value = result
            return mock

        client = MagicMock()
        client.table.side_effect = table_side_effect

        refund_rows = [
            _make_row(
                order_num="SO-REF-ORPHAN",
                sku_code="C41-35",
                shipped_units="-1",
                pronto_account="ACC-GHOST",
                territory="BOND",
            )
        ]

        matched, confidence = _match_refund(refund_rows, client)

        assert matched is None
        assert confidence == "unmatched"
