import pytest

from apps.investments import instruments
from apps.investments.instruments import Refusal
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.tests.conftest import make_broker

FUND = "INF209KA12Z1"
UNKNOWN = "INF209KA13Z9"
GOLD = "Gold 24K (per gram)"

pytestmark = pytest.mark.django_db


@pytest.fixture
def known() -> None:
    Instrument.objects.create(isin=FUND, name="A fund", kind="mutual_fund")
    Instrument.objects.create(name=GOLD, kind="gold")


@pytest.mark.usefixtures("known")
@pytest.mark.parametrize(
    ("text", "name"),
    [
        (FUND, "A fund"),
        (FUND.lower(), "A fund"),
        (GOLD, GOLD),
        (GOLD.upper(), GOLD),
        (f"  {GOLD}  ", GOLD),
        ("a FUND", "A fund"),
    ],
)
def test_find_picks_by_full_isin_or_exact_name(text: str, name: str) -> None:
    found = instruments.find(text)

    assert isinstance(found, Instrument)
    assert found.name == name


@pytest.mark.usefixtures("known")
@pytest.mark.parametrize("text", [UNKNOWN, "Gold", "INF209", ""])
def test_find_refuses_what_picks_nothing(text: str) -> None:
    assert instruments.find(text) == Refusal.NO_MATCH


def test_find_refuses_a_name_two_instruments_with_an_isin_share() -> None:
    Instrument.objects.create(isin=FUND, name="Twin", kind="stock")
    Instrument.objects.create(isin=UNKNOWN, name="Twin", kind="stock")

    assert instruments.find("Twin") == Refusal.NO_MATCH


@pytest.mark.usefixtures("known")
@pytest.mark.parametrize(
    ("isin", "name", "expected"),
    [
        ("", "", Refusal.NO_NAME),
        ("", "  ", Refusal.NO_NAME),
        ("", GOLD.lower(), Refusal.TAKEN),
    ],
)
def test_add_refuses(isin: str, name: str, expected: Refusal) -> None:
    assert instruments.add(isin, name, "gold") == expected


@pytest.mark.usefixtures("known")
def test_add_gives_the_known_instrument_for_a_known_isin() -> None:
    assert instruments.add(FUND, "Any name", "stock") == Instrument.objects.get(
        isin=FUND
    )


@pytest.mark.usefixtures("known")
@pytest.mark.parametrize(("isin", "isin_kept"), [("", None), (UNKNOWN, UNKNOWN)])
def test_add_gives_a_new_unsaved_instrument(isin: str, isin_kept: str | None) -> None:
    new = instruments.add(isin, " Silver bar ", "other")

    assert isinstance(new, Instrument)
    assert not Instrument.objects.filter(name=new.name).exists()
    assert (new.isin, new.name, new.kind) == (isin_kept, "Silver bar", "other")


@pytest.mark.usefixtures("known")
@pytest.mark.parametrize(
    ("isin", "name", "creates", "expected"),
    [
        (UNKNOWN, "New fund", False, Refusal.NOT_KNOWN),
        (UNKNOWN, "", True, Refusal.UNKNOWN_ISIN),
        ("", "", True, Refusal.NO_ISIN),
    ],
)
def test_pick_refuses(isin: str, name: str, creates: bool, expected: Refusal) -> None:  # noqa: FBT001
    assert instruments.pick(isin, name, "stock", creates_from_isin=creates) == expected


@pytest.mark.usefixtures("known")
@pytest.mark.parametrize(
    ("isin", "name", "picked"),
    [(FUND, "", "A fund"), (FUND, "Other", "A fund"), ("", GOLD.lower(), GOLD)],
)
def test_pick_gives_the_known_instrument(isin: str, name: str, picked: str) -> None:
    found = instruments.pick(isin, name, "stock", creates_from_isin=False)

    assert isinstance(found, Instrument)
    assert found.pk is not None
    assert found.name == picked


@pytest.mark.usefixtures("known")
def test_pick_adds_an_unknown_isin_with_a_name() -> None:
    new = instruments.pick(UNKNOWN, "New fund", "mutual_fund", creates_from_isin=True)

    assert isinstance(new, Instrument)
    assert not Instrument.objects.filter(name=new.name).exists()
    assert (new.isin, new.name) == (UNKNOWN, "New fund")


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ((FUND, "A"), (FUND, "B"), True),
        ((FUND, "A"), (UNKNOWN, "A"), False),
        ((None, "Silver bar"), (None, "silver BAR"), True),
        ((None, "Silver bar"), (None, "Gold bar"), False),
        ((None, "A"), (FUND, "A"), False),
    ],
)
def test_same_compares_isins_or_names_in_any_case(
    a: tuple[str | None, str],
    b: tuple[str | None, str],
    same: bool,  # noqa: FBT001
) -> None:
    first = Instrument(isin=a[0], name=a[1])
    second = Instrument(isin=b[0], name=b[1])

    assert instruments.same(first, second) is same


@pytest.mark.usefixtures("known")
@pytest.mark.parametrize(
    ("isin", "name", "matched"),
    [(FUND.lower(), "", "A fund"), ("", GOLD.upper(), GOLD), ("", "A fund", None)],
)
def test_matching_filters_through_a_relation(
    isin: str, name: str, matched: str | None
) -> None:
    account = make_broker()
    for instrument in Instrument.objects.all():
        InvestmentEvent.objects.create(
            account=account,
            instrument=instrument,
            kind="buy",
            date="2026-03-01",
            units=1,
            amount=10,
        )

    events = InvestmentEvent.objects.filter(
        instruments.matching(isin, name, prefix="instrument__")
    )

    assert [e.instrument.name for e in events] == ([matched] if matched else [])


def test_save_if_new_saves_only_unsaved() -> None:
    new = Instrument(name="Silver bar", kind="other")

    instruments.save_if_new(new)
    instruments.save_if_new(new)
    instruments.save_if_new(None)

    assert Instrument.objects.get() == new
