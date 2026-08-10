"""
tests/test_drive_watcher.py
============================
Unit tests for the Drive watcher's twin-check folder-name normalization.

Covers the bug fixed 9 Aug 2026 (commit 5d45996d): Bondi/Miranda's scanning
app emits a fixed 0000 pad ahead of the twin (twin 0001 arrives as folder
00000001) that the old strict \\d{4} match rejected outright, and
independently, store_settings had zero rows so the prefix lookup was a
no-op for every store either way.

Run from digiprint/backend/ with:
    pytest tests/test_drive_watcher.py -v

No Google API credentials or Supabase connection required — _strip_prefix
only touches the in-memory _prefix_cache, which these tests set directly.
"""

import pytest

from app.services import drive_watcher
from app.services.drive_watcher import _strip_prefix


STORE_ID = "store-bond-uuid"


@pytest.fixture(autouse=True)
def _reset_prefix_cache():
    """Isolate each test's view of the module-level prefix cache."""
    original = drive_watcher._prefix_cache
    drive_watcher._prefix_cache = {}
    yield
    drive_watcher._prefix_cache = original


class TestNoPrefixConfigured:
    """store_settings has no twin_folder_prefix row for this store."""

    def test_exact_reported_case_extra_zero_pad(self):
        # Bondi/Miranda scanning app: twin 0001 arrives as folder 00000001.
        assert _strip_prefix("00000001", STORE_ID) == "0001"

    def test_another_padded_case(self):
        assert _strip_prefix("00005555", STORE_ID) == "5555"

    def test_no_padding_passthrough(self):
        assert _strip_prefix("0042", STORE_ID) == "0042"

    def test_single_digit_pads_to_four(self):
        assert _strip_prefix("7", STORE_ID) == "0007"

    def test_garbage_folder_rejected(self):
        assert _strip_prefix("Untitled folder", STORE_ID) is None

    def test_empty_string_rejected(self):
        assert _strip_prefix("", STORE_ID) is None

    def test_digit_overflow_rejected(self):
        # More significant digits than a twin can have (max 9999).
        assert _strip_prefix("123456789", STORE_ID) is None

    def test_alpha_prefix_digits_extracted(self):
        # Hypothetical Brisbane-style "A00" + twin folder, no configured
        # prefix — non-digit characters are stripped regardless of source.
        assert _strip_prefix("A000042", STORE_ID) == "0042"


class TestConfiguredPrefix:
    """store_settings.twin_folder_prefix is set for this store."""

    def test_configured_prefix_stripped_then_normalized(self):
        drive_watcher._prefix_cache[STORE_ID] = "BOND-"
        assert _strip_prefix("BOND-00000042", STORE_ID) == "0042"

    def test_configured_prefix_no_padding(self):
        drive_watcher._prefix_cache[STORE_ID] = "BOND-"
        assert _strip_prefix("BOND-0042", STORE_ID) == "0042"

    def test_folder_missing_configured_prefix_rejected(self):
        drive_watcher._prefix_cache[STORE_ID] = "BOND-"
        assert _strip_prefix("0042", STORE_ID) is None

    def test_store_aware_different_store_no_prefix(self):
        drive_watcher._prefix_cache[STORE_ID] = "BOND-"
        # A different store with no cache entry falls back to no-prefix path.
        assert _strip_prefix("00000099", "store-miranda-uuid") == "0099"
