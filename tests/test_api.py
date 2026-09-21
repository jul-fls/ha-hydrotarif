"""Focused checks for SISPEA page extraction."""

from datetime import date, datetime, timezone
import importlib
import sys
from pathlib import Path
from types import ModuleType
import unittest

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "hydrotarif"

# Import the pure parsing module without requiring a Home Assistant installation.
package = ModuleType("hydrotarif")
package.__path__ = [str(COMPONENT)]
sys.modules["hydrotarif"] = package
aiohttp_stub = ModuleType("aiohttp")
aiohttp_stub.ClientTimeout = lambda total: None
sys.modules["aiohttp"] = aiohttp_stub
api = importlib.import_module("hydrotarif.api")
location = importlib.import_module("hydrotarif.location")


def page(water: str, sanitation: str, organisation: str = "Service present") -> str:
    return f"""<html><body>
    <h1>Commune Castres-Gironde</h1><p>Commune | 2024</p>
    <h2>Zoom sur les prix</h2>
    <div>Eau potable</div><strong>{water}</strong>
    <p>Prix du service d'eau potable au 1er janvier 2025 en 2024 : Service A</p>
    <div>Assainissement collectif</div><strong>{sanitation}</strong>
    <p>Prix du service d'assainissement au 1er janvier 2025 en 2024 : Service B</p>
    <h2>Organisation des services publics</h2>
    <div>Eau potable Service A</div><div>Assainissement collectif {organisation}</div>
    </body></html>"""


class SispeaParsingTests(unittest.TestCase):
    def test_two_prices_and_total(self):
        water, sanitation, no_collective = api.parse_commune_page(
            page("2.00 € TTC/m³", "3.22 € TTC/m³"), "33109", 2024
        )
        self.assertFalse(no_collective)
        self.assertEqual(water.value, 2.0)
        self.assertEqual(sanitation.value, 3.22)
        self.assertEqual(water.tariff_date, date(2025, 1, 1))
        prices = api.Prices(water, sanitation, False, datetime.now(timezone.utc))
        self.assertEqual(prices.total, 5.22)

    def test_missing_collective_service_is_not_zero(self):
        water, sanitation, no_collective = api.parse_commune_page(
            page("2.56 € TTC/m³", "Donnée non disponible en 2024", "Aucun service"),
            "40223", 2024,
        )
        prices = api.Prices(water, sanitation, no_collective, datetime.now(timezone.utc))
        self.assertTrue(no_collective)
        self.assertIsNone(prices.total)
        self.assertEqual(prices.status, "no_collective_service")

    def test_different_tariff_dates_do_not_make_a_total(self):
        newer = api.Price(2.0, 2024, date(2025, 1, 1), "source")
        older = api.Price(3.0, 2023, date(2024, 1, 1), "source")
        self.assertIsNone(api.Prices(newer, older, False, datetime.now(timezone.utc)).total)

    def test_ignores_script_and_rejects_wrong_page(self):
        html = "<script>Eau potable 9.99 € TTC/m³ Prix du service d'eau potable au 1er janvier 2025 en 2024</script>"
        with self.assertRaises(api.SispeaError):
            api.parse_commune_page(html, "33109", 2024)


class FakeResponse:
    def __init__(self, data, status=200):
        self.data = data
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(self.status)

    async def json(self):
        return self.data


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return FakeResponse(self.responses.pop(0))


class LocationTests(unittest.IsolatedAsyncioTestCase):
    async def test_gps_paris_arrondissement_resolves_to_commune(self):
        session = FakeSession(
            [{"code": "75102", "nom": "Paris 2e Arrondissement"}],
            {"code": "75056", "nom": "Paris"},
        )
        found = await location.from_coordinates(session, 48.868, 2.331, "home")
        self.assertEqual(found.code, "75056")
        self.assertEqual(found.unique_id, "home")
        self.assertEqual(session.calls[1][0], "https://geo.api.gouv.fr/communes/75056")

    async def test_postal_commune_matches_name_and_keeps_distinct_entry(self):
        session = FakeSession(
            [{"code": "33109", "nom": "Castres-Gironde"}],
            {"code": "33109", "nom": "Castres-Gironde"},
        )
        found = await location.from_postal_commune(session, "33640", "castres gironde")
        self.assertEqual(found.code, "33109")
        self.assertEqual(found.unique_id, "postal:33640:33109")

    async def test_full_address_uses_ign_and_keeps_address_label(self):
        session = FakeSession(
            {"features": [{
                "properties": {"score": 0.96, "citycode": "75102", "label": "10 Rue de la Paix 75002 Paris", "type": "housenumber", "id": "ban-123"},
                "geometry": {"coordinates": [2.33, 48.87]},
            }]},
            {"code": "75056", "nom": "Paris"},
        )
        found = await location.from_address(session, "10 rue de la Paix 75002 Paris")
        self.assertEqual(found.code, "75056")
        self.assertEqual(found.unique_id, "address:ban-123")
        self.assertEqual(found.latitude, 48.87)

    async def test_ambiguous_address_is_rejected(self):
        session = FakeSession({"features": [
            {"properties": {"score": 0.90, "citycode": "33109", "label": "Rue A", "type": "street"}},
            {"properties": {"score": 0.88, "citycode": "33110", "label": "Rue A", "type": "street"}},
        ]})
        with self.assertRaises(location.AmbiguousLocation):
            await location.from_address(session, "Rue A, Gironde")

    async def test_low_confidence_address_is_rejected(self):
        session = FakeSession({"features": [
            {"properties": {"score": 0.5, "citycode": "33109", "label": "Rue A", "type": "street"}}
        ]})
        with self.assertRaises(location.InvalidLocation):
            await location.from_address(session, "Rue A, Gironde")


if __name__ == "__main__":
    unittest.main()
