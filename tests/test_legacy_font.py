"""Hindi typed in a legacy font reads as Latin gibberish; it must be told apart from English."""

from examhub_pipeline import extract
from examhub_pipeline.crawl import ingest

# The shape of a real SBI advertisement page: Latin letters with font debris, no English words.
LEGACY = ("AmnHo$ gnZm| H$m H$[a`a ^maVr` ñQ>oQ> ~¢H$ (Eg~rAmB©) go ewê$ hmoVm h¡. Amn {gµ\\©$ EH$ ~¢H$ go Zht Ow‹S>Vo, "
          "~pëH$ ^maV Ho$ g~go ^amogo_§X g§ñWm H$m {hñgm ~ZVo h¢, Omo Xoe H$s àJ{V _| `moJXmZ XoVm h¡ Am¡a ha {XZ ") * 4
ENGLISH = ("The candidates shall apply online for the post of Probationary Officer. The fee is payable by the "
           "candidate through the online mode and the last date for the application is as given in the schedule. ") * 4
UNICODE_HINDI = "भारतीय स्टेट बैंक में परिवीक्षाधीन अधिकारी के पद के लिए आवेदन करने की अंतिम तिथि ऑनलाइन है। " * 12


def test_a_legacy_font_page_is_detected():
    assert extract.is_legacy_hindi(LEGACY)


def test_english_and_real_unicode_hindi_are_not_flagged():
    assert not extract.is_legacy_hindi(ENGLISH)
    assert not extract.is_legacy_hindi(UNICODE_HINDI)


def test_a_short_page_is_never_flagged():
    assert not extract.is_legacy_hindi(LEGACY[:150])


def test_a_legacy_record_gets_its_own_final_status():
    record = {"notice": {"id": "x"}, "document": {"sha256": "ab", "pages": 3, "ocr": False}, "schema": 1,
              "warnings": [f"{extract.LEGACY_FONT_NOTE}: 3 of 3 pages (from page 1); an English edition is needed"]}
    assert ingest.index_line(record)["status"] == "legacy_font"
