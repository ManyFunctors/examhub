"""Score the finder's first pick per field against the hand labels (no model).

    python tests/accuracy/score.py            every set
    python tests/accuracy/score.py held_out_2 registration_deadline
                                              one set, and list that field's misses
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "src"))

from labels import FIELDS, SETS  # noqa: E402

from examhub_pipeline.candidates import adjudicate, find_candidates  # noqa: E402
from examhub_pipeline.extract import _clean_text  # noqa: E402
from examhub_pipeline.record import _mode  # noqa: E402

NOTICES = json.loads((HERE / "notices.json").read_text(encoding="utf-8"))


def first_picks(doc: str) -> dict[str, str | None]:
    """The finder's chosen value per field for one notice."""
    notice = NOTICES[doc]
    adj = adjudicate(find_candidates(_clean_text(notice["text"]), notice["url"], pages=None))
    out: dict[str, str | None] = {}
    for f in FIELDS:
        chosen = adj[f].chosen if f in adj else None
        value = chosen.value if chosen else None
        out[f] = _mode(value) if f == "mode" and value else value
    return out


def score(labels: dict[str, dict[str, list[str]]], show: str = "") -> Counter:
    """right / wrong picks and facts found, over one label set."""
    tally: Counter = Counter()
    for doc, truth in labels.items():
        picks = first_picks(doc)
        for f in FIELDS:
            pick, want = picks[f], truth[f]
            tally["facts"] += bool(want)
            if pick is not None:
                tally["picks"] += 1
                tally["right" if pick in want else "wrong"] += 1
            if show == f and pick not in want and (pick or want):
                print(f"  {doc} {f}: picked {pick}, notice says {want or 'nothing'}")
    return tally


def main() -> None:
    names = [a for a in sys.argv[1:2] if a in SETS] or list(SETS)
    show = sys.argv[2] if len(sys.argv) > 2 else ""
    for name in names:
        t = score(SETS[name], show)
        print(f"{name:11s} picks right {t['right']}/{t['picks']} ({100 * t['right'] / max(1, t['picks']):.0f}%)"
              f"   facts found {t['right']}/{t['facts']} ({100 * t['right'] / max(1, t['facts']):.0f}%)")


if __name__ == "__main__":
    main()
