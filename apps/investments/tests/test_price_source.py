from datetime import date
from decimal import Decimal

from apps.investments.models import Instrument
from apps.investments.price_source import (
    PriceRow,
    parse_amfi,
    parse_amfi_history,
    parse_nse,
)

NAV_ALL = """\
Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

Open Ended Schemes(Debt Scheme - Banking and PSU Fund)

Aditya Birla Sun Life Mutual Fund

119551;INF209KA12Z1;INF209KA13Z9;ABSL Banking PSU Debt - IDCW;101.41925;10-Oct-2026
119552;INF209K01YM2;-;ABSL Banking PSU Debt - Growth;350.1;10-Oct-2026
119553;-;-;Unpriced scheme;N.A.;10-Oct-2026
119554;INF209K01ZZ9;;Bad date scheme;12.5;sometime
"""  # noqa: E501

NAV_HISTORY = """\
Scheme Code;Scheme Name;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Repurchase Price;Sale Price;Date

Open Ended Schemes(Debt Scheme - Banking and PSU Fund)

119551;ABSL Banking PSU Debt - IDCW;INF209KA12Z1;-;101.41925;;;02-Mar-2026
119551;ABSL Banking PSU Debt - IDCW;INF209KA12Z1;-;101.5;;;03-Mar-2026
119553;Unpriced scheme;INF209K01ZZ9;-;N.A.;;;03-Mar-2026
119554;Bad date scheme;INF209K01ZZ9;;12.5;;;sometime
"""  # noqa: E501

BHAVCOPY = """\
TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,FinInstrmNm,ClsPric
2026-10-12,2026-10-12,CM,NSE,STK,2885,INE002A01018,RELIANCE,EQ,RELIANCE INDUSTRIES LTD,2950.15
2026-10-12,2026-10-12,CM,NSE,STK,1,INF204KB14I2,NIFTYBEES,EQ,NIP IND ETF NIFTY BEES,271.30
2026-10-12,2026-10-12,CM,NSE,STK,2,IN0020200039,GS2030,GS,GOVT STOCK 2030,101.00
2026-10-12,2026-10-12,CM,NSE,STK,3,INE000000002,BADPRICE,EQ,BAD PRICE LTD,-
"""  # noqa: E501

ETF_LIST = """\
Symbol, Underlying, SecurityName, DateofListing, MarketLot, ISINNumber, FaceValue
NIFTYBEES,Nifty 50,Nippon India ETF Nifty BeES,08-Jan-2002,1,INF204KB14I2,1
"""


def test_amfi_gives_a_mutual_fund_row_per_isin() -> None:
    day = date(2026, 10, 10)
    fund = Instrument.Kind.MUTUAL_FUND

    assert parse_amfi(NAV_ALL) == [
        PriceRow(
            "INF209KA12Z1",
            "ABSL Banking PSU Debt - IDCW",
            fund,
            Decimal("101.4193"),
            day,
        ),
        PriceRow(
            "INF209KA13Z9",
            "ABSL Banking PSU Debt - IDCW",
            fund,
            Decimal("101.4193"),
            day,
        ),
        PriceRow(
            "INF209K01YM2",
            "ABSL Banking PSU Debt - Growth",
            fund,
            Decimal("350.1"),
            day,
        ),
    ]


def test_amfi_history_gives_a_row_per_isin_and_day() -> None:
    fund = Instrument.Kind.MUTUAL_FUND
    name = "ABSL Banking PSU Debt - IDCW"

    assert parse_amfi_history(NAV_HISTORY) == [
        PriceRow("INF209KA12Z1", name, fund, Decimal("101.4193"), date(2026, 3, 2)),
        PriceRow("INF209KA12Z1", name, fund, Decimal("101.5"), date(2026, 3, 3)),
    ]


def test_nse_gives_stocks_and_etfs_by_the_etf_list() -> None:
    day = date(2026, 10, 12)

    assert parse_nse(BHAVCOPY, ETF_LIST) == [
        PriceRow(
            "INE002A01018",
            "RELIANCE INDUSTRIES LTD",
            Instrument.Kind.STOCK,
            Decimal("2950.15"),
            day,
        ),
        PriceRow(
            "INF204KB14I2",
            "NIP IND ETF NIFTY BEES",
            Instrument.Kind.ETF,
            Decimal("271.30"),
            day,
        ),
    ]
