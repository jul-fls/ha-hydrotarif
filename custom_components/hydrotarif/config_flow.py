"""UI setup for one HydroTarif location."""

from __future__ import annotations

import re

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SelectOptionDict,
)

from .const import (
    CONF_COMMUNE,
    CONF_INSEE,
    CONF_LATITUDE,
    CONF_LOCATION_LABEL,
    CONF_LOCATION_SOURCE,
    CONF_LONGITUDE,
    DOMAIN,
)
from .location import (
    AmbiguousLocation,
    InvalidLocation,
    Location,
    PostalChoice,
    from_address,
    from_coordinates,
    from_insee,
    from_postal_choice,
    search_postal_prefix,
)

CONF_POSTAL_CODE = "postal_code"
CONF_POSTAL_CHOICE = "postal_choice"
CONF_ADDRESS = "address"


class HydroTarifFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure an address or commune, defaulting to HA's location."""

    VERSION = 1

    def _session(self) -> aiohttp.ClientSession:
        return async_get_clientsession(self.hass)

    async def _resolve(self, operation):
        try:
            return await operation
        except InvalidLocation:
            return "invalid_location"
        except AmbiguousLocation:
            return "ambiguous_location"
        except (aiohttp.ClientError, TimeoutError):
            return "cannot_connect"
        except (KeyError, TypeError, ValueError):
            return "invalid_location"

    async def _finish(self, location: Location):
        await self.async_set_unique_id(location.unique_id)
        self._abort_if_unique_id_configured()
        data = {
            CONF_INSEE: location.code,
            CONF_COMMUNE: location.commune,
            CONF_LOCATION_SOURCE: location.source,
            CONF_LOCATION_LABEL: location.label,
        }
        if location.latitude is not None and location.longitude is not None:
            data[CONF_LATITUDE] = location.latitude
            data[CONF_LONGITUDE] = location.longitude
        return self.async_create_entry(title=location.label, data=data)

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            mode = user_input[CONF_LOCATION_SOURCE]
            if mode == "home":
                result = await self._resolve(
                    from_coordinates(
                        self._session(),
                        self.hass.config.latitude,
                        self.hass.config.longitude,
                        "home",
                    )
                )
                if isinstance(result, Location):
                    return await self._finish(result)
                errors["base"] = result
            else:
                steps = {
                    "gps": self.async_step_gps,
                    "postal_commune": self.async_step_postal_commune,
                    "address": self.async_step_address,
                    "insee": self.async_step_insee,
                }
                return await steps[mode]()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOCATION_SOURCE, default="home"): SelectSelector(
                        SelectSelectorConfig(
                            options=["home", "gps", "postal_commune", "address", "insee"],
                            translation_key=CONF_LOCATION_SOURCE,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_gps(self, user_input=None):
        errors = {}
        if user_input is not None:
            result = await self._resolve(
                from_coordinates(self._session(), user_input[CONF_LATITUDE], user_input[CONF_LONGITUDE])
            )
            if isinstance(result, Location):
                return await self._finish(result)
            errors["base"] = result
        return self.async_show_form(
            step_id="gps",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LATITUDE): vol.All(vol.Coerce(float), vol.Range(min=-90, max=90)),
                    vol.Required(CONF_LONGITUDE): vol.All(vol.Coerce(float), vol.Range(min=-180, max=180)),
                }
            ),
            errors=errors,
        )

    async def async_step_postal_commune(self, user_input=None):
        errors = {}
        if user_input is not None:
            prefix = user_input[CONF_POSTAL_CODE].strip()
            if not re.fullmatch(r"\d{2,5}", prefix):
                errors[CONF_POSTAL_CODE] = "invalid_postal_prefix"
            else:
                result = await self._resolve(search_postal_prefix(self._session(), prefix))
                if isinstance(result, list):
                    self._postal_choices: dict[str, PostalChoice] = {
                        choice.value: choice for choice in result
                    }
                    return await self.async_step_postal_select()
                errors["base"] = result
        return self.async_show_form(
            step_id="postal_commune",
            data_schema=vol.Schema({vol.Required(CONF_POSTAL_CODE): str}),
            errors=errors,
        )

    async def async_step_postal_select(self, user_input=None):
        choices = getattr(self, "_postal_choices", None)
        if not choices:
            return await self.async_step_postal_commune()
        errors = {}
        if user_input is not None:
            selected = choices.get(user_input.get(CONF_POSTAL_CHOICE))
            if selected is None:
                errors["base"] = "invalid_location"
            else:
                result = await self._resolve(from_postal_choice(self._session(), selected))
                if isinstance(result, Location):
                    return await self._finish(result)
                errors["base"] = result
        options = [SelectOptionDict(value=choice.value, label=choice.label) for choice in choices.values()]
        return self.async_show_form(
            step_id="postal_select",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POSTAL_CHOICE): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_address(self, user_input=None):
        errors = {}
        if user_input is not None:
            result = await self._resolve(from_address(self._session(), user_input[CONF_ADDRESS]))
            if isinstance(result, Location):
                return await self._finish(result)
            errors["base"] = result
        return self.async_show_form(
            step_id="address",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): str}),
            errors=errors,
        )

    async def async_step_insee(self, user_input=None):
        errors = {}
        if user_input is not None:
            result = await self._resolve(from_insee(self._session(), user_input[CONF_INSEE]))
            if isinstance(result, Location):
                return await self._finish(result)
            errors["base"] = result
        return self.async_show_form(
            step_id="insee",
            data_schema=vol.Schema({vol.Required(CONF_INSEE): str}),
            errors=errors,
        )
