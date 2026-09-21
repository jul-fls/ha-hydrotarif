"""Read public SISPEA commune pages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
import re

import aiohttp

from .const import SISPEA_URL

_WATER = re.compile(
    r"Eau potable\s+(\d+[.,]\d+)\s*€\s*TTC/m[³3]\s+"
    r"Prix du service d'eau potable au 1er janvier (\d{4}) en (\d{4})",
    re.IGNORECASE,
)
_SANITATION = re.compile(
    r"Assainissement collectif\s+(\d+[.,]\d+)\s*€\s*TTC/m[³3]\s+"
    r"Prix du service d'assainissement au 1er janvier (\d{4}) en (\d{4})",
    re.IGNORECASE,
)


class SispeaError(Exception):
    """A temporary SISPEA retrieval or parsing error."""


class _VisibleText(HTMLParser):
    """Extract visible text while ignoring scripts and styles."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "svg"):
            self.ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "svg") and self.ignored:
            self.ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)


@dataclass(frozen=True)
class Price:
    value: float
    year: int
    tariff_date: date
    source_url: str


@dataclass(frozen=True)
class Prices:
    water: Price | None
    sanitation: Price | None
    no_collective_service: bool
    checked_at: datetime

    @property
    def total(self) -> float | None:
        if not self.water or not self.sanitation:
            return None
        if self.water.tariff_date != self.sanitation.tariff_date:
            return None
        return round(self.water.value + self.sanitation.value, 2)

    @property
    def status(self) -> str:
        if self.no_collective_service:
            return "no_collective_service"
        if self.total is not None:
            return "complete"
        if self.water or self.sanitation:
            return "partial"
        return "missing"


def parse_commune_page(html: str, code: str, year: int) -> tuple[Price | None, Price | None, bool]:
    """Extract only labelled commune prices, never chart bounds or averages."""
    parser = _VisibleText()
    parser.feed(html)
    text = " ".join(" ".join(parser.parts).split())
    if f"Commune | {year}" not in text and f"Commune {year}" not in text:
        raise SispeaError("SISPEA page format changed or year is missing")

    url = SISPEA_URL.format(code=code, year=year)

    def extract(pattern: re.Pattern[str]) -> Price | None:
        match = pattern.search(text)
        if not match:
            return None
        value, reference_year, data_year = match.groups()
        if int(data_year) != year or int(reference_year) != year + 1:
            raise SispeaError("SISPEA price date is inconsistent")
        return Price(float(value.replace(",", ".")), year, date(year + 1, 1, 1), url)

    organisation = text.split("Organisation des services publics", 1)
    no_collective = bool(
        len(organisation) == 2
        and re.search(r"Assainissement collectif\s+Aucun service", organisation[1])
    )
    return extract(_WATER), extract(_SANITATION), no_collective


class SispeaClient:
    """Retrieve the latest usable prices for one commune."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session

    async def fetch(self, code: str) -> Prices:
        water = None
        sanitation = None
        no_collective = False
        newest_page_seen = False
        current_year = datetime.now(timezone.utc).year
        # The tariff for SISPEA year N starts on January 1 of N+1.
        for year in range(current_year - 1, max(2007, current_year - 7), -1):
            url = SISPEA_URL.format(code=code, year=year)
            try:
                async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                    if response.status == 404:
                        continue
                    response.raise_for_status()
                    html = await response.text()
            except (aiohttp.ClientError, TimeoutError) as err:
                raise SispeaError(f"Cannot load SISPEA: {err}") from err

            page_water, page_sanitation, page_no_collective = parse_commune_page(html, code, year)
            if not newest_page_seen:
                no_collective = page_no_collective
                newest_page_seen = True
            if water is None:
                water = page_water
            if sanitation is None and not no_collective:
                sanitation = page_sanitation
            if water and (sanitation or no_collective):
                break

        return Prices(water, sanitation, no_collective, datetime.now(timezone.utc))
