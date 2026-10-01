"""The finder's accuracy on hand-labelled notices must not slip.

Floors sit a little under the scores of 30 Sep 2026 (picks right 98%,
facts found 81% over all 47 notices); tests/accuracy/score.py prints them.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "accuracy"))

from score import SETS, score  # noqa: E402

PICKS_RIGHT_FLOOR = 0.95
FACTS_FOUND_FLOOR = 0.78


def _all() -> Counter:
    total: Counter = Counter()
    for labels in SETS.values():
        total += score(labels)
    return total


def test_the_finder_keeps_its_accuracy():
    t = _all()
    assert t["right"] / t["picks"] >= PICKS_RIGHT_FLOOR, f"picks right {t['right']}/{t['picks']}"
    assert t["right"] / t["facts"] >= FACTS_FOUND_FLOOR, f"facts found {t['right']}/{t['facts']}"
