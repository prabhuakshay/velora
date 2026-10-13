from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.template import Context, Template

from apps.users.templatetags.amounts import MASK, PERCENT_MASK


def render(source: str, *, privacy_mode: bool = False, **values: object) -> str:
    user = SimpleNamespace(privacy_mode=privacy_mode, number_format="indian")
    template = Template("{% load amounts %}" + source)
    return template.render(Context({"user": user, **values}))


@pytest.mark.parametrize(
    ("value", "good", "expected"),
    [
        ("1000", "up", '<span class="text-emerald-600">+₹1,000.00</span>'),
        ("-1000", "up", "<span>-₹1,000.00</span>"),
        ("-1000", "down", '<span class="text-emerald-600">-₹1,000.00</span>'),
        ("1000", "down", "<span>+₹1,000.00</span>"),
        ("1000", "none", '<span class="text-slate-500">₹1,000.00</span>'),
        ("0", "up", "<span>₹0.00</span>"),
        ("0", "down", "<span>₹0.00</span>"),
    ],
)
def test_signed_amount_shows_sign_and_greens_the_good_way(
    value: str, good: str, expected: str
) -> None:
    html = render("{% signed_amount value good %}", value=Decimal(value), good=good)

    assert html == expected


def test_signed_amount_takes_up_as_good_by_default() -> None:
    html = render("{% signed_amount value %}", value=Decimal(5))

    assert html == '<span class="text-emerald-600">+₹5.00</span>'


@pytest.mark.parametrize("good", ["up", "down", "none"])
@pytest.mark.parametrize("value", ["1000", "-1000"])
def test_signed_amount_is_only_the_mask_in_privacy_mode(value: str, good: str) -> None:
    html = render(
        "{% signed_amount value good %}",
        privacy_mode=True,
        value=Decimal(value),
        good=good,
    )

    assert html == MASK


def test_amount_color_leaves_what_is_owed_uncoloured() -> None:
    assert render("{% amount_color -1 %}") == "text-red-600"
    assert render("{% amount_color -1 owes=True %}") == ""


@pytest.mark.parametrize(
    ("value", "owes", "expected"),
    [
        ("-5000", True, "₹5,000.00 in credit"),
        ("5000", True, "₹5,000.00"),
        ("-5000", False, "-₹5,000.00"),
    ],
)
def test_balance_shows_a_liability_below_zero_as_in_credit(
    value: str, *, owes: bool, expected: str
) -> None:
    html = render("{% balance value owes=owes %}", value=Decimal(value), owes=owes)

    assert html == expected


def test_balance_is_only_the_mask_in_privacy_mode() -> None:
    html = render(
        "{% balance value owes=True %}", privacy_mode=True, value=Decimal(-5000)
    )

    assert html == MASK


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("42.6087", '<span class="text-emerald-600">+42.61%</span>'),
        ("-20", "<span>-20.00%</span>"),
        ("0.001", "<span>0.00%</span>"),
        (None, "—"),
    ],
)
def test_signed_percent_shows_sign_and_greens_a_gain(
    value: str | None, expected: str
) -> None:
    number = None if value is None else Decimal(value)

    assert render("{% signed_percent value %}", value=number) == expected


def test_signed_percent_is_only_the_mask_in_privacy_mode() -> None:
    html = render("{% signed_percent value %}", privacy_mode=True, value=Decimal(5))

    assert html == PERCENT_MASK


@pytest.mark.parametrize(
    ("value", "number_format", "expected"),
    [
        ("25", "indian", "25%"),
        ("12.50", "indian", "12.5%"),
        ("33.333", "indian", "33.33%"),
        ("0", "indian", "0%"),
        ("123456.7", "indian", "1,23,456.7%"),
        ("123456.7", "international", "123,456.7%"),
        ("-2.5", "indian", "-2.5%"),
    ],
)
def test_percent_shows_up_to_two_decimals_in_the_number_format(
    value: str, number_format: str, expected: str
) -> None:
    user = SimpleNamespace(privacy_mode=False, number_format=number_format)
    template = Template("{% load amounts %}{% percent value %}")

    html = template.render(Context({"user": user, "value": Decimal(value)}))

    assert html == expected


def test_percent_is_only_the_mask_in_privacy_mode() -> None:
    html = render("{% percent value %}", privacy_mode=True, value=Decimal(5))

    assert html == PERCENT_MASK
