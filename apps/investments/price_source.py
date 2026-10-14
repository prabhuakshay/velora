"""The Price Sources: the only code that talks HTTP to AMFI and NSE.

Each Price Source hands back plain parsed rows and raises SourceUnavailable
when it has no file or can't be reached. Tests swap in an in-memory Source,
so nothing else here needs faking. When AMFI or NSE change their file
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
from enum import StrEnum
from http import HTTPStatus
from typing import TYPE_CHECKING, Protocol

from apps.investments.isin import is_valid_isin
from apps.investments.models import Instrument

if TYPE_CHECKING:
    from collections.abc import Callable

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


class SourceUnavailable(Exception):  # noqa: N818
    """A Price Source had no file for what was asked, or couldn't be reached."""

    class Reason(StrEnum):
        NO_FILE = "no file"
        UNREACHABLE = "unreachable"

    def __init__(self, reason: Reason, url: str = "") -> None:
        """Say why, and for which file if known."""
        super().__init__(f"{reason}: {url}" if url else reason)
        self.reason = reason


class Source(Protocol):
    """Where Prices are fetched from: AMFI or NSE, or a fake in tests."""

    def latest(self, day: date) -> list[PriceRow]:
        """The latest Prices published up to the day."""
        ...

    def history(self, start: date, end: date) -> list[PriceRow]:
        """The Prices on each day from start to end."""
        ...


def _get(url: str) -> bytes:
    """The body at the URL; raises SourceUnavailable on a 404 or a network failure.

    Other HTTP errors are unexpected and raised as they are.
    """
    request = urllib.request.Request(url, headers=HEADERS)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            body: bytes = response.read()
    except urllib.error.HTTPError as error:
        if error.code != HTTPStatus.NOT_FOUND:
            raise
        # Nothing reads its body, and one left open warns whenever it is collected.
        error.close()
        raise SourceUnavailable(SourceUnavailable.Reason.NO_FILE, url) from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise SourceUnavailable(SourceUnavailable.Reason.UNREACHABLE, url) from error
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


def _text(get: Callable[[str], bytes], url: str) -> str:
    return get(url).decode("utf-8", errors="replace")


class Amfi:
    """AMFI's NAVs for every mutual fund scheme."""

    def __init__(self, get: Callable[[str], bytes] = _get) -> None:
        """Fetch files with get, which raises SourceUnavailable as _get does."""
        self._get = get

    def latest(self, day: date) -> list[PriceRow]:  # noqa: ARG002
        """Every scheme's latest NAV; AMFI publishes only its newest file."""
        return parse_amfi(_text(self._get, AMFI_URL))

    def history(self, start: date, end: date) -> list[PriceRow]:
        """Every scheme's NAV on each day from start to end."""
        url = AMFI_HISTORY_URL.format(start=start, end=end)
        return parse_amfi_history(_text(self._get, url))


class Nse:
    """NSE's closing prices for every stock, ETF and SGB."""

    def __init__(self, get: Callable[[str], bytes] = _get) -> None:
        """Fetch files with get, which raises SourceUnavailable as _get does."""
        self._get = get

    def _bhavcopy(self, day: date) -> str:
        body = self._get(NSE_BHAVCOPY_URL.format(day=day))
        archive = zipfile.ZipFile(io.BytesIO(body))
        return archive.read(archive.namelist()[0]).decode("utf-8", errors="replace")

    def latest(self, day: date) -> list[PriceRow]:
        """Closing prices on the latest trading day up to day.

        NSE publishes a day's bhavcopy only after the market closes, and none on
        holidays, so the latest earlier one stands in until then. Raises
        SourceUnavailable when NSE has none in the last NSE_LOOKBACK_DAYS.
        """
        for back in range(NSE_LOOKBACK_DAYS):
            try:
                bhavcopy = self._bhavcopy(day - timedelta(days=back))
                break
            except SourceUnavailable as error:
                no_file = error.reason == SourceUnavailable.Reason.NO_FILE
                if not no_file or back == NSE_LOOKBACK_DAYS - 1:
                    raise
        return parse_nse(bhavcopy, _text(self._get, NSE_ETF_URL))

    def history(self, start: date, end: date) -> list[PriceRow]:
        """Closing prices on each weekday from start to end.

        Days with no bhavcopy in NSE's archive, such as holidays, are skipped.
        """
        etf_list = _text(self._get, NSE_ETF_URL)
        rows: list[PriceRow] = []
        day = start
        while day <= end:
            if day.weekday() < 5:  # noqa: PLR2004
                try:
                    rows.extend(parse_nse(self._bhavcopy(day), etf_list))
                except SourceUnavailable as error:
                    if error.reason != SourceUnavailable.Reason.NO_FILE:
                        raise
            day += timedelta(days=1)
        return rows
