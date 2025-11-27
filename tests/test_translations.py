from drive_audit.translations import TRANSLATIONS, translate


def test_translate_returns_localized_message():
    assert translate("en", "invalid_token") == TRANSLATIONS["en"]["invalid_token"]
    assert translate("ru", "invalid_token") == TRANSLATIONS["ru"]["invalid_token"]


def test_translate_falls_back_to_english_for_missing_language():
    assert translate("de", "invalid_token") == TRANSLATIONS["en"]["invalid_token"]


def test_translate_returns_key_when_missing():
    assert translate("en", "non_existing_key") == "non_existing_key"
