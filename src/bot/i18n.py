from pathlib import Path

from fluent_compiler.bundle import FluentBundle
from fluentogram import FluentTranslator, TranslatorHub

LOCALES_DIR = Path(__file__).parent / "locales"
DEFAULT_LOCALE = "en"


def create_translator_hub() -> TranslatorHub:
    translators = []
    for locale_dir in sorted(p for p in LOCALES_DIR.iterdir() if p.is_dir()):
        files = sorted((locale_dir / "LC_MESSAGES").glob("*.ftl"))
        bundle = FluentBundle.from_files(
            locale_dir.name, filenames=[str(f) for f in files], use_isolating=False
        )
        translators.append(FluentTranslator(locale_dir.name, bundle))
    return TranslatorHub(
        {DEFAULT_LOCALE: (DEFAULT_LOCALE,)}, translators=translators, root_locale=DEFAULT_LOCALE
    )
