import pytest

from apps.investments.isin import is_valid_isin


@pytest.mark.parametrize(
    "isin",
    ["INE002A01018", "INE010J01012", "INF209K01YM2", "US0378331005", "INF204KB14I2"],
)
def test_real_isins_are_valid(isin: str) -> None:
    assert is_valid_isin(isin)


@pytest.mark.parametrize(
    "isin",
    [
        "INE002A01019",
        "INE010J01013",
        "INF000000001",
        "TEJASNET",
        "US03783310055",
        "1S0378331005",
        "US037833100-",
        "us0378331005",
        "",
    ],
)
def test_made_up_or_mistyped_isins_are_not(isin: str) -> None:
    assert not is_valid_isin(isin)
