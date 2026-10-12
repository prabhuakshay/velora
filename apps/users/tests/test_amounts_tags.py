from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.template import Context, Template

from apps.users.templatetags.amounts import MASK


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
