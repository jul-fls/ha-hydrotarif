"""Resolve French locations to the commune used by SISPEA."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

import aiohttp

from .const import ADDRESS_URL, GEO_URL


class InvalidLocation(Exception):
    """No confident French commune match was found."""


class AmbiguousLocation(Exception):
    """The input matches more than one commune."""


@dataclass(frozen=True)
class Location:
    code: str
    commune: str
    label: str
    source: str
    unique_id: str
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class PostalChoice:
    postcode: str
    code: str
    commune: str

    @property
    def value(self) -> str:
        return f"{self.postcode}:{self.code}"

    @property
    def label(self) -> str:
        return f"{self.postcode} - {self.commune} ({self.code})"


def _normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value.casefold()))


def _commune_code(code: str) -> str:
    """Map Paris, Lyon and Marseille arrondissements to their commune."""
    if re.fullmatch(r"751(0[1-9]|1[0-9]|20)", code):
        return "75056"
    if re.fullmatch(r"6938[1-9]", code):
        return "69123"
    if re.fullmatch(r"132(0[1-9]|1[0-6])", code):
        return "13055"
    return code


async def _get_json(session: aiohttp.ClientSession, url: str, params: dict | None = None):
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as response:
        if response.status == 404:
            raise InvalidLocation
        response.raise_for_status()
        return await response.json()


async def _canonical_commune(session: aiohttp.ClientSession, code: str) -> tuple[str, str]:
    code = _commune_code(code)
    if not re.fullmatch(r"[0-9AB]{5}", code):
        raise InvalidLocation
    data = await _get_json(session, f"{GEO_URL}/{code}", {"fields": "nom,code"})
    if not isinstance(data, dict) or not data.get("nom") or data.get("code") != code:
        raise InvalidLocation
    return code, data["nom"]


async def from_insee(session: aiohttp.ClientSession, code: str) -> Location:
    code, name = await _canonical_commune(session, code.strip().upper())
    return Location(code, name, name, "insee", f"insee:{code}")


async def from_coordinates(
    session: aiohttp.ClientSession, latitude: float, longitude: float, source: str = "gps"
) -> Location:
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise InvalidLocation
    results = await _get_json(
        session, GEO_URL, {"lat": latitude, "lon": longitude, "fields": "nom,code"}
    )
    if not isinstance(results, list) or len(results) != 1:
        raise InvalidLocation
    code, name = await _canonical_commune(session, results[0]["code"])
    label = f"Home Assistant ({name})" if source == "home" else f"{latitude:.6f}, {longitude:.6f} ({name})"
    unique_id = "home" if source == "home" else f"gps:{latitude:.6f}:{longitude:.6f}"
    return Location(code, name, label, source, unique_id, latitude, longitude)


async def search_postal_prefix(
    session: aiohttp.ClientSession, prefix: str
) -> list[PostalChoice]:
    """List every commune with a postal code beginning with the given digits."""
    prefix = prefix.strip()
    if not re.fullmatch(r"\d{2,5}", prefix):
        raise InvalidLocation
    results = await _get_json(
        session, GEO_URL, {"fields": "nom,code,codesPostaux"}
    )
    if not isinstance(results, list):
        raise InvalidLocation
    choices: dict[str, PostalChoice] = {}
    for candidate in results:
        code = candidate.get("code", "")
        name = candidate.get("nom", "")
        for postcode in candidate.get("codesPostaux") or []:
            if isinstance(postcode, str) and postcode.startswith(prefix) and code and name:
                choice = PostalChoice(postcode, code, name)
                choices[choice.value] = choice
    if not choices:
        raise InvalidLocation
    return sorted(choices.values(), key=lambda choice: (choice.postcode, _normalize(choice.commune), choice.code))


async def from_postal_choice(session: aiohttp.ClientSession, choice: PostalChoice) -> Location:
    code, name = await _canonical_commune(session, choice.code)
    return Location(
        code,
        name,
        f"{name} ({choice.postcode})",
        "postal_commune",
        f"postal:{choice.postcode}:{code}",
    )


async def from_address(session: aiohttp.ClientSession, address: str) -> Location:
    address = address.strip()
    if len(address) < 8:
        raise InvalidLocation
    result = await _get_json(
        session, ADDRESS_URL, {"q": address, "index": "address", "limit": 5}
    )
    features = result.get("features", []) if isinstance(result, dict) else []
    if not features:
        raise InvalidLocation
    first = features[0]
    props = first.get("properties", {})
    score = props.get("score", 0)
    code = props.get("citycode", "")
    label = props.get("label", "")
    if not isinstance(score, (float, int)) or score < 0.75 or not code or not label:
        raise InvalidLocation
    if re.match(r"^\d+\s", address) and props.get("type") != "housenumber":
        raise InvalidLocation
    for other in features[1:]:
        other_props = other.get("properties", {})
        if (
            _commune_code(other_props.get("citycode", "")) != _commune_code(code)
            and other_props.get("score", 0) >= score - 0.05
        ):
            raise AmbiguousLocation
    code, name = await _canonical_commune(session, code)
    coordinates = first.get("geometry", {}).get("coordinates", [])
    longitude, latitude = (coordinates[0], coordinates[1]) if len(coordinates) == 2 else (None, None)
    address_id = props.get("id") or _normalize(label)
    return Location(code, name, label, "address", f"address:{address_id}", latitude, longitude)
