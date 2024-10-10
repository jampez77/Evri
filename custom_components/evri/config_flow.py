"""Config flow for Royal Mail integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import callback

from .const import CONF_PARCELS, DOMAIN


class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Royal Mail."""

    VERSION = 1

    @callback
    def _entry_exists(self):
        """Check if an entry for this domain already exists."""
        existing_entries = self._async_current_entries()
        return len(existing_entries) > 0

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Handle the initial step (no user input)."""
        if self._entry_exists():
            return self.async_abort(reason="already_configured")
        await self.async_set_unique_id("Tracked Parcels")

        if user_input is not None:
            return self.async_create_entry(title="Evri", data={CONF_PARCELS: []})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
        )

    async def async_step_import(self, import_data=None) -> ConfigFlowResult:
        """Handle the import step for the service call."""

        if import_data is not None:
            try:
                entries = self.hass.config_entries.async_entries(DOMAIN)
                for entry in entries:
                    updated_data = entry.data.copy()
                    parcels = list(updated_data.get(CONF_PARCELS, []))

                    parcels.append(dict(import_data))

                    updated_data[CONF_PARCELS] = parcels

                    self.hass.config_entries.async_update_entry(
                        entry, data=updated_data
                    )

            except Exception as e:  # pylint: disable=broad-except
                return self.async_abort(reason="import_failed")

        # Explicitly handle the case where import_data is None
        return self.async_abort(reason="no_import_data")
