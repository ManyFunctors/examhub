"""Shared fixtures.

Every test here is offline by default. Nothing in this directory touches the
network or loads the model unless it is explicitly marked, and the two marked
directories are the only ones that are allowed to be slow.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from examhub_pipeline.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings rooted entirely in a temp directory."""
    s = Settings(
        root=tmp_path,
        work_dir=tmp_path / "work",
        cache_dir=tmp_path / "work" / "cache",
        repo_dir=tmp_path / "work" / "ExamHub",
        host_delay_seconds=0.0,
        max_requests=50,
        respect_robots=False,
        enable_model=False,
        enable_ocr=False,
    )
    s.ensure_dirs()
    return s


@pytest.fixture
def today() -> dt.date:
    return dt.date(2026, 9, 27)


@pytest.fixture
def ssc_notice() -> str:
    """A synthetic notice with the shapes real ones use.

    Line-wrapped the way a PDF text layer wraps, with the dates in Indian
    dotted form and the labels in the phrasing SSC actually uses, because the
    point of the extraction tests is that they survive exactly that.
    """
    return """STAFF SELECTION COMMISSION
Government of India

1. VACANCIES: Total No. of Posts: 1,044 (Out of which 1044 are unreserved
and 300 are reserved for women).

2. SCHEDULE OF EXAMINATION
The Combined Graduate Level Examination, 2026 Tier-I will be held on
15.06.2026 at 10:00 AM and Tier-II on 28.09.2026.

3. ONLINE REGISTRATION
Commencement of online registration: 01.02.2026
Closing date of online application: 22.02.2026 up to 23:00 hours

4. APPLICATION FEE
The fee payable is Rs. 100/- for General and EWS candidates, Rs 50 for
SC/ST/PwD candidates and nil for ex-servicemen.

5. MODE OF EXAMINATION
The examination will be conducted in Computer Based Test (CBT) mode.

6. DURATION
The Tier-I paper is of 2 hours duration with 100 questions.

7. EXAMINATION CENTRES
Examination centres at 300 cities across India.

8. NEGATIVE MARKING
There will be one-fourth of the marks assigned for each wrong answer.

9. PAY
Posts carry Pay Matrix Level 7 (Rs 69250-134200).
"""
