"""
tests/test_twincheck_label.py
==============================
Smoke tests for the (imported, not rewritten) twincheck/twincheck_label.py
module against the shape twin_check_service._build_print_job actually
passes it — no DB, no printer required.

Run from digiprint/backend/ with:
    pytest tests/test_twincheck_label.py -v
"""

import pytest

from twincheck.twincheck_label import LabelSpec, build_job, build_label


class TestFiveRollJob:
    """Acceptance criterion #8: 5-roll job -> 5 blocks, each ^PQ2, sequential
    numbers, correct n/m."""

    def test_five_roll_job_shape(self):
        numbers = [4821, 4822, 4823, 4824, 4825]
        rolls = [{"order": "48213", "film_type": "C41", "twin_check": n} for n in numbers]
        zpl = build_job(
            rolls=rolls,
            spec=LabelSpec(dpi=300, width_mm=23.0, height_mm=15.0),
            store="BOND", cycle=7, copies=2,
        )
        assert zpl.count("^PQ2") == 5
        assert zpl.count("^XA") == 5
        assert zpl.count("^XZ") == 5
        for n in numbers:
            assert str(n).zfill(4) in zpl
        assert "1/5" in zpl and "5/5" in zpl

    def test_two_across_media_uses_copies_one(self):
        rolls = [{"order": "1", "film_type": "C41", "twin_check": 1}]
        zpl = build_job(rolls=rolls, spec=LabelSpec(), store="BOND", cycle=1, copies=1)
        assert "^PQ1" in zpl
        assert "^PQ2" not in zpl


class TestLongestLine1Case:
    """Criterion #12: 5-digit order, longest service code, double-digit n/m
    at 23mm must render without truncation — shrink-to-fit, never raise."""

    def test_longest_realistic_line1_does_not_raise(self):
        zpl = build_label(
            order="48213-B", film_type="RSC", twin_check=9999,
            roll_index=10, roll_total=10,
            spec=LabelSpec(dpi=203, width_mm=23.0, height_mm=15.0),
            store="BOND", cycle=3, copies=1,
        )
        assert "9999" in zpl
        assert "10/10" in zpl

    def test_pathological_case_still_raises_rather_than_clip(self):
        """The generator's own floor — do not disable it. An absurdly long
        order number must fail loudly, not silently truncate on the label."""
        with pytest.raises(ValueError):
            build_label(
                order="X" * 60, film_type="RSC", twin_check=9999,
                spec=LabelSpec(width_mm=23.0, height_mm=15.0),
            )


class TestRescanLabel:
    """Criterion #11: RSC labels never carry a process code (C41/BW) —
    there is exactly one rescan code."""

    def test_rsc_label_has_no_chemistry_code(self):
        zpl = build_label(
            order="48213", film_type="RSC", twin_check=100,
            spec=LabelSpec(),
        )
        assert "RSC" in zpl
        assert "C41" not in zpl
        assert "BW" not in zpl

    def test_no_film_format_on_label(self):
        """film_type is always the short process code (C41/BW/RSC) — never
        format (35mm/120mm) or brand, per §3.5b. This module doesn't enforce
        that itself (it just renders what it's given), so this test locks
        the expectation for callers."""
        zpl = build_label(order="1", film_type="C41", twin_check=1, spec=LabelSpec())
        assert "35mm" not in zpl and "120mm" not in zpl
