"""The text of an expense: `render.expense_text`."""

from datetime import date
from decimal import Decimal

from src.bot import render
from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from src.services.results import ExpenseCard

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)


def card(**fields) -> ExpenseCard:
    values = dict(
        expense_id=1,
        amount=Decimal("12.5"),
        currency="EUR",
        spent_at=date(2026, 10, 17),
        payee_key="mercadona",
        payee_name="Mercadona",
        payment_source_id=3,
        payment_source_name="VISA •0848",
        category="groceries",
        tags=["holiday", "kids"],
        receipt_id=None,
        can_edit_facts=True,
        deleted=False,
    )
    return ExpenseCard(**(values | fields))


def test_the_text_has_the_payee_the_facts_the_tags_and_the_hashtag():
    assert render.expense_text(card(), i18n).splitlines() == [
        "<b>Mercadona</b>",
        "",
        "17.10.2026",
        "Amount: <b>12.50 €</b>",
        "Paid with: VISA •0848",
        "Category: Groceries",
        "Tags: #holiday #kids",
        "",
        "#mercadona",
    ]


def test_no_tags_means_no_tags_line():
    assert "Tags" not in render.expense_text(card(tags=[]), i18n)


def test_names_are_escaped_and_a_missing_payee_and_source_are_named():
    text = render.expense_text(
        card(payee_key=None, payee_name=None, payment_source_name=None, tags=[]), i18n
    )

    assert text.startswith("<b>Unknown payee</b>")
    assert "Paid with: not specified" in text
    assert "#" not in text
    escaped = render.expense_text(card(payee_name="A<b>&Co", payment_source_name="<i>"), i18n)
    assert "<b>A&lt;b&gt;&amp;Co</b>" in escaped
    assert "Paid with: &lt;i&gt;" in escaped


def test_a_tag_becomes_a_hashtag_of_word_characters():
    text = render.expense_text(card(tags=["new year", "a-b", "café"]), i18n)

    assert "Tags: #new_year #a_b #café" in text
