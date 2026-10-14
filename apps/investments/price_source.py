"""The price-source client: the only code that talks HTTP to AMFI and NSE.

It hands back plain parsed rows. Tests replace `amfi_rows` and `nse_rows` with
a fake, so nothing else here needs faking. When AMFI or NSE change their file
formats, only this module should need to change.
"""

import csv
import io
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from http import HTTPStatus

from apps.investments.isin import is_valid_isin
from apps.investments.models import Instrument

AMFI_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
AMFI_HISTORY_URL = (
    "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"
    "?frmdt={start:%d-%b-%Y}&todt={end:%d-%b-%Y}"
)
NSE_BHAVCOPY_URL = (
    "https://nsearchives.nseindia.com/content/cm/"
    "BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
)
NSE_ETF_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"
TIMEOUT_SECONDS = 60
# NSE refuses requests without a browser-like User-Agent.
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Velora"}
# Series of ordinary shares; ETFs are listed under EQ too.
EQUITY_SERIES = {"EQ", "BE"}
SGB_SERIES = "GB"
PLACES = Decimal("0.0001")
# Covers a weekend plus a long run of market holidays.
NSE_LOOKBACK_DAYS = 7


@dataclass(frozen=True)
class PriceRow:
    """One Instrument's Price on a day, as the source reported it."""

    isin: str
    name: str
    kind: Instrument.Kind
    price: Decimal
    date: date


def _get(url: str) -> bytes:
    """The body at the URL; raises urllib.error.URLError on network failures."""
    request = urllib.request.Request(url, headers=HEADERS)  # noqa: S310
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        body: bytes = response.read()
    return body


def _price(text: str) -> Decimal | None:
    """The text as a Price rounded to 4 places, or None if it isn't one above 0."""
    try:
        value = Decimal(text.strip())
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0:
        return None
    return value.quantize(PLACES, rounding=ROUND_HALF_UP)


def _isin(text: str) -> str | None:
    text = text.strip().upper()
    return text if is_valid_isin(text) else None


def _amfi_rows(isins: list[str], name: str, nav: str, when: str) -> list[PriceRow]:
    """One row per valid ISIN of an AMFI line; none if its NAV or date is bad."""
    price = _price(nav)
    try:
        day = datetime.strptime(when.strip(), "%d-%b-%Y").date()  # noqa: DTZ007
    except ValueError:
        return []
    if price is None:
        return []
    return [
        PriceRow(isin, name.strip(), Instrument.Kind.MUTUAL_FUND, price, day)
        for isin in filter(None, map(_isin, isins))
    ]


def parse_amfi(text: str) -> list[PriceRow]:
    """Rows from AMFI's NAVAll.txt; one per ISIN, skipping headings and gaps.

    A data line is `code;ISIN growth/payout;ISIN reinvestment;name;NAV;date`.
    """
    rows: list[PriceRow] = []
    for line in text.splitlines():
        fields = line.split(";")
        if len(fields) == 6:  # noqa: PLR2004
            _, *isins, name, nav, when = fields
            rows.extend(_amfi_rows(isins, name, nav, when))
    return rows


def parse_amfi_history(text: str) -> list[PriceRow]:
    """Rows from AMFI's NAV history report; one per ISIN and day.

    A data line is `code;name;ISIN growth/payout;ISIN reinvestment;NAV;
    repurchase price;sale price;date`.
    """
    rows: list[PriceRow] = []
    for line in text.splitlines():
        fields = line.split(";")
        if len(fields) == 8:  # noqa: PLR2004
            _, name, *isins, nav, _, _, when = fields
            rows.extend(_amfi_rows(isins, name, nav, when))
    return rows


def parse_nse(bhavcopy: str, etf_list: str) -> list[PriceRow]:
    """Stock, ETF and SGB rows from NSE's equity bhavcopy and its ETF list."""
    etfs = {
        isin
        for line in csv.DictReader(io.StringIO(etf_list))
        if (isin := _isin(_field(line, "ISINNumber") or ""))
    }
    rows = []
    for line in csv.DictReader(io.StringIO(bhavcopy)):
        isin = _isin(_field(line, "ISIN") or "")
        price = _price(_field(line, "ClsPric") or "")
        if isin is None or price is None:
            continue
        series = _field(line, "SctySrs") or ""
        if isin not in etfs and series not in EQUITY_SERIES | {SGB_SERIES}:
            continue
        try:
            day = date.fromisoformat(_field(line, "TradDt") or "")
        except ValueError:
            continue
        if isin in etfs:
            kind = Instrument.Kind.ETF
        elif series == SGB_SERIES:
            kind = Instrument.Kind.BOND
        else:
            kind = Instrument.Kind.STOCK
        name = _field(line, "FinInstrmNm") or _field(line, "TckrSymb") or isin
        rows.append(PriceRow(isin, name, kind, price, day))
    return rows


def _field(line: dict[str, str | None], name: str) -> str | None:
    """The column's value, ignoring stray spaces NSE puts in its headers."""
    for key, value in line.items():
        if key and key.strip() == name:
            return value.strip() if value else value
    return None


def amfi_rows() -> list[PriceRow]:
    """Every mutual fund scheme's latest NAV from AMFI."""
    return parse_amfi(_get(AMFI_URL).decode("utf-8", errors="replace"))


def amfi_history_rows(start: date, end: date) -> list[PriceRow]:
    """Every mutual fund scheme's NAV on each day from start to end."""
    url = AMFI_HISTORY_URL.format(start=start, end=end)
    return parse_amfi_history(_get(url).decode("utf-8", errors="replace"))


def _bhavcopy(day: date) -> str:
    archive = zipfile.ZipFile(io.BytesIO(_get(NSE_BHAVCOPY_URL.format(day=day))))
    return archive.read(archive.namelist()[0]).decode("utf-8", errors="replace")


def _etf_list() -> str:
    return _get(NSE_ETF_URL).decode("utf-8", errors="replace")


def nse_rows(day: date) -> list[PriceRow]:
    """Every NSE stock, ETF and SGB's closing price on the latest trading day up to day.

    NSE publishes a day's bhavcopy only after the market closes, and none on
    holidays, so the latest earlier one stands in until then. Raises
    urllib.error.HTTPError when NSE has none in the last NSE_LOOKBACK_DAYS.
    """
    for back in range(NSE_LOOKBACK_DAYS):
        try:
            bhavcopy = _bhavcopy(day - timedelta(days=back))
            break
        except urllib.error.HTTPError as error:
            if error.code != HTTPStatus.NOT_FOUND or back == NSE_LOOKBACK_DAYS - 1:
                raise
            error.close()
    return parse_nse(bhavcopy, _etf_list())


def nse_history_rows(start: date, end: date) -> list[PriceRow]:
    """Every NSE stock, ETF and SGB's closing price on each weekday, start to end.

    Days with no bhavcopy in NSE's archive, such as holidays, are skipped.
    """
    etf_list = _etf_list()
    rows: list[PriceRow] = []
    day = start
    while day <= end:
        if day.weekday() < 5:  # noqa: PLR2004
            try:
                rows.extend(parse_nse(_bhavcopy(day), etf_list))
            except urllib.error.HTTPError as error:
                if error.code != HTTPStatus.NOT_FOUND:
                    raise
        day += timedelta(days=1)
    return rows
