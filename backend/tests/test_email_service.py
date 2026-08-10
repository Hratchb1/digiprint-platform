"""
tests/test_email_service.py
============================
Unit tests for email_service's template-selection and blank-roll-count
helpers.

Covers the bug fixed 10 Aug 2026: _derive_template_key() used to key off
order_type (a coarse category that never carries service info), which
silently defaulted almost every order to blank_notification — including
order 3939686, a real Dev+Scan order booked as order_type='film'. It now
derives from each roll's service_type, and blank_notification only fires
when every roll on the order is confirmed blank.

Also covers the same-day fix to blank_roll_count, which was always 0
because no caller ever set that key on the order dict passed into
send_order_email — _compute_blank_roll_count() now derives it from the
rolls list directly, the same pattern already used for rolls_count.

Run from digiprint/backend/ with:
    pytest tests/test_email_service.py -v

No SMTP, Supabase, or Jinja render is exercised — these test the pure
helper functions directly with in-memory roll/order dicts.
"""

from app.services.email_service import _derive_template_key, _compute_blank_roll_count


def _order(rolls):
    return {"id": "order-uuid-1", "order_number": "3939686", "rolls": rolls}


def _roll(service_type=None, is_blank=False):
    return {"service_type": service_type, "is_blank": is_blank}


class TestDeriveTemplateKeyServiceCombos:
    def test_dev_and_scan(self):
        order = _order([_roll("Dev+Scan")])
        assert _derive_template_key(order) == "scans_ready"

    def test_scan_only(self):
        order = _order([_roll("Scan only")])
        assert _derive_template_key(order) == "scans_ready"

    def test_dev_scan_and_print(self):
        order = _order([_roll("Dev+Scan+Print")])
        assert _derive_template_key(order) == "prints_and_scans_ready"

    def test_dev_and_print(self):
        order = _order([_roll("Dev+Print")])
        assert _derive_template_key(order) == "prints_ready"

    def test_print_only(self):
        order = _order([_roll("Print only")])
        assert _derive_template_key(order) == "prints_ready"

    def test_dev_only(self):
        order = _order([_roll("Dev only")])
        assert _derive_template_key(order) == "negatives_ready"

    def test_mixed_rolls_richest_combo_wins(self):
        # One roll is Dev only, another is Dev+Scan+Print — the order-level
        # template should reflect the richest service present.
        order = _order([_roll("Dev only"), _roll("Dev+Scan+Print")])
        assert _derive_template_key(order) == "prints_and_scans_ready"

    def test_real_world_regression_order_3939686(self):
        # order_type was 'film' on this order — must NOT influence the
        # result at all; only roll service_type matters now.
        order = _order([_roll("Dev+Scan")])
        order["order_type"] = "film"
        assert _derive_template_key(order) == "scans_ready"


class TestDeriveTemplateKeyBlankHandling:
    def test_all_blank_rolls_is_blank_notification(self):
        order = _order([_roll("Dev+Scan", is_blank=True), _roll("Dev+Scan", is_blank=True)])
        assert _derive_template_key(order) == "blank_notification"

    def test_single_blank_roll_is_blank_notification(self):
        order = _order([_roll("Dev only", is_blank=True)])
        assert _derive_template_key(order) == "blank_notification"

    def test_mixed_blank_and_good_is_not_blank_notification(self):
        # A mix of blank and good rolls must route to the normal template —
        # it renders its own blank-roll notice via blank_roll_count.
        order = _order([_roll("Dev+Scan", is_blank=True), _roll("Dev+Scan", is_blank=False)])
        result = _derive_template_key(order)
        assert result != "blank_notification"
        assert result == "scans_ready"


class TestDeriveTemplateKeyEmptyUnknown:
    def test_empty_rolls_never_defaults_to_blank(self):
        order = _order([])
        assert _derive_template_key(order) == "scans_ready"

    def test_unknown_service_type_never_defaults_to_blank(self):
        order = _order([_roll("Passport Photo"), _roll(None)])
        result = _derive_template_key(order)
        assert result == "scans_ready"
        assert result != "blank_notification"

    def test_missing_service_type_key(self):
        order = _order([{"is_blank": False}])
        assert _derive_template_key(order) != "blank_notification"


class TestComputeBlankRollCount:
    def test_all_blank(self):
        rolls = [_roll(is_blank=True), _roll(is_blank=True)]
        assert _compute_blank_roll_count(rolls) == 2

    def test_mixed(self):
        rolls = [_roll(is_blank=True), _roll(is_blank=False), _roll(is_blank=False)]
        assert _compute_blank_roll_count(rolls) == 1

    def test_no_blanks(self):
        rolls = [_roll(is_blank=False), _roll(is_blank=False)]
        assert _compute_blank_roll_count(rolls) == 0

    def test_empty_rolls(self):
        assert _compute_blank_roll_count([]) == 0
