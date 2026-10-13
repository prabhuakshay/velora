"""The price-source client: the only code that talks HTTP to AMFI and NSE.

It hands back plain parsed rows. Tests replace `amfi_rows` and `nse_rows` with
a fake, so nothing else here needs faking. When AMFI or NSE change their file
formats, only this module should need to change.
"""

import csv
import io
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from apps.investments.models import Instrument

AMFI_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
NSE_BHAVCOPY_URL = (
    "https://nsearchives.nseindia.com/content/cm/"
    "BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
)
NSE_ETF_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"
TIMEOUT_SECONDS = 60
# NSE refuses requests without a browser-like User-Agent.
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Velora"}
# Series that trade as ordinary shares; ETFs trade under EQ too.
EQUITY_SERIES = {"EQ", "BE"}
PLACES = Decimal("0.0001")


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
    return text if len(text) == 12 and text.isalnum() else None  # noqa: PLR2004


def parse_amfi(text: str) -> list[PriceRow]:
    """Rows from AMFI's NAVAll.txt; one per ISIN, skipping headings and gaps.

    A data line is `code;ISIN growth/payout;ISIN reinvestment;name;NAV;date`.
    """
    rows: list[PriceRow] = []
    for line in text.splitlines():
        fields = line.split(";")
        if len(fields) != 6:  # noqa: PLR2004
            continue
        _, *isins, name, nav, when = fields
        price = _price(nav)
        try:
            day = datetime.strptime(when.strip(), "%d-%b-%Y").date()  # noqa: DTZ007
        except ValueError:
            continue
        if price is None:
            continue
        rows.extend(
            PriceRow(isin, name.strip(), Instrument.Kind.MUTUAL_FUND, price, day)
            for isin in filter(None, map(_isin, isins))
        )
    return rows


def parse_nse(bhavcopy: str, etf_list: str) -> list[PriceRow]:
    """Stock and ETF rows from NSE's equity bhavcopy and its ETF list."""
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
        if isin not in etfs and (_field(line, "SctySrs") or "") not in EQUITY_SERIES:
            continue
        try:
            day = date.fromisoformat(_field(line, "TradDt") or "")
        except ValueError:
            continue
        kind = Instrument.Kind.ETF if isin in etfs else Instrument.Kind.STOCK
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


def nse_rows(day: date) -> list[PriceRow]:
    """Every NSE stock's and ETF's closing price on the day.

    Raises urllib.error.HTTPError when NSE has no bhavcopy for the day, such
    as on a holiday.
    """
    archive = zipfile.ZipFile(io.BytesIO(_get(NSE_BHAVCOPY_URL.format(day=day))))
    bhavcopy = archive.read(archive.namelist()[0]).decode("utf-8", errors="replace")
    etf_list = _get(NSE_ETF_URL).decode("utf-8", errors="replace")
    return parse_nse(bhavcopy, etf_list)
