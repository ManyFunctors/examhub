from examhub_pipeline import languages


def test_ocr_langs_follow_the_jurisdiction():
    assert languages.ocr_langs("mh") == "eng+hin+mar"
    assert languages.ocr_langs("wb") == "eng+hin+ben"
    assert languages.ocr_langs("up") == "eng+hin"
    assert languages.ocr_langs(None, "eng") == "eng+hin"
    assert languages.ocr_langs("kl", "eng+hin") == "eng+hin+mal"


def test_usable_drops_models_that_are_not_installed(monkeypatch):
    monkeypatch.setattr(languages, "installed", lambda: frozenset({"eng", "hin"}))
    assert languages.usable("eng+hin+mar") == "eng+hin"
    monkeypatch.setattr(languages, "installed", lambda: frozenset())
    assert languages.usable("eng+mar") == "eng+mar"  # no tesseract to ask: leave the request alone


def test_normalise_turns_indic_digits_and_months_into_english():
    assert languages.normalise("दिनांक २५ ऑक्टोबर २०२६") == "दिनांक 25 October 2026"
    assert languages.normalise("১২ মার্চ ২০২৬") == "12 মার্চ 2026"
    assert languages.normalise("25 October 2026") == "25 October 2026"
    # a longer word that merely contains a month's letters is left alone
    assert languages.normalise("मेहनत") == "मेहनत"
