"""Config flow for the Phicomm DC1 integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithConfigEntry,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .const import CONF_AUTO_ADD, CONF_MAC, CONF_NAME, CONF_PORT, DEFAULT_PORT, DOMAIN
from .hub import normalize_mac

_LOGGER = logging.getLogger(__name__)

MANUAL = "__manual__"


def _entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return hass.config_entries.async_entries(DOMAIN)


def _entry_macs(hass: HomeAssistant) -> set[str]:
    """MACs added through the UI."""
    return {normalize_mac(entry.data.get(CONF_MAC)) or "" for entry in _entries(hass)} - {""}


def _yaml_macs(hass: HomeAssistant) -> set[str]:
    """MACs declared in the YAML block; these cannot be managed from the UI."""
    from . import hub_of

    hub = hub_of(hass)
    if hub is None:
        return set()
    return set(hub.plugs) - _entry_macs(hass)


def _configured_macs(hass: HomeAssistant) -> set[str]:
    """Every MAC that is already wired up, from either the UI or YAML."""
    return _entry_macs(hass) | _yaml_macs(hass)


def _taken_because(hass: HomeAssistant, mac: str) -> str | None:
    """Why this MAC is unavailable: ``already_configured``, ``configured_in_yaml`` or None.

    Saying "already added" for a MAC that is only declared in YAML sends people
    looking for a config entry that does not exist, so name the real cause.
    """
    if mac in _entry_macs(hass):
        return "already_configured"
    if mac in _yaml_macs(hass):
        return "configured_in_yaml"
    return None


def _detected(hass: HomeAssistant) -> list[tuple[str, str]]:
    """``(mac, label)`` for strips that dialed in but are not configured."""
    from . import hub_of

    hub = hub_of(hass)
    if hub is None:
        return []
    out: list[tuple[str, str]] = []
    for mac in sorted(set(hub.seen) - _configured_macs(hass)):
        seen = hub.seen[mac]
        parts = [mac]
        if seen.address:
            parts.append(seen.address)
        if seen.device_type:
            parts.append(seen.device_type)
        out.append((mac, " · ".join(parts)))
    return out


class Dc1ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a strip from the UI, or accept one that was discovered."""

    VERSION = 1

    def __init__(self) -> None:
        self._mac: str | None = None
        self._port: int = DEFAULT_PORT
        self._meta: dict[str, Any] = {}

    # ------------------------------------------------------------- user ----
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a strip that already dialed in, or type a MAC in."""
        detected = _detected(self.hass)
        if not detected:
            # Nothing has connected yet - go straight to the manual form, which
            # also collects the listen port for the very first strip.
            return await self.async_step_manual(user_input)

        if user_input is not None:
            chosen = user_input.get("pick")
            if chosen == MANUAL:
                return await self.async_step_manual()
            self._mac = normalize_mac(chosen)
            return await self._finish(name="")

        options: list[dict[str, str]] = [
            {"value": mac, "label": label} for mac, label in detected
        ]
        options.append({"value": MANUAL, "label": "手动输入 MAC…"})
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("pick"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, multiple=False)
                    )
                }
            ),
            description_placeholders={"count": str(len(detected))},
            last_step=False,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the MAC, and for the port when no server is running yet."""
        from . import hub_of

        hub = hub_of(self.hass)
        default_port = hub.port if hub else DEFAULT_PORT
        errors: dict[str, str] = {}

        if user_input is not None:
            mac = normalize_mac(user_input.get(CONF_MAC))
            if mac is None:
                errors[CONF_MAC] = "invalid_mac"
            else:
                self._mac = mac
                self._port = int(user_input.get(CONF_PORT) or default_port)
                return await self._finish(name=user_input.get(CONF_NAME) or "")

        schema: dict[Any, Any] = {
            vol.Required(CONF_MAC, default=self._mac or ""): cv.string,
            vol.Optional(CONF_NAME, default=""): cv.string,
        }
        if hub is None:
            schema[vol.Optional(CONF_PORT, default=default_port)] = cv.port

        return self.async_show_form(
            step_id="manual", data_schema=vol.Schema(schema), errors=errors, last_step=True
        )

    # -------------------------------------------------------- discovery ----
    async def async_step_discovery(
        self, discovery_info: dict[str, Any]
    ) -> ConfigFlowResult:
        """A strip dialed in and it is not configured yet."""
        from . import auto_add_enabled, hub_of

        mac = normalize_mac(discovery_info.get(CONF_MAC))
        if mac is None:
            return self.async_abort(reason="invalid_mac")

        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured()
        if (taken := _taken_because(self.hass, mac)) is not None:
            return self.async_abort(reason=taken)

        self._mac = mac
        self._meta = discovery_info
        hub = hub_of(self.hass)
        self._port = hub.port if hub else DEFAULT_PORT

        if auto_add_enabled(self.hass):
            return await self._finish(name="")

        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user name a discovered strip before adding it."""
        if user_input is not None:
            return await self._finish(name=user_input.get(CONF_NAME) or "")

        placeholders = {
            "mac": self._mac or "",
            "address": self._meta.get("address") or "-",
            "device_type": self._meta.get("device_type") or "-",
        }
        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=vol.Schema({vol.Optional(CONF_NAME, default=""): cv.string}),
            title_placeholders={"mac": self._mac or ""},
            description_placeholders=placeholders,
            last_step=True,
        )

    # ----------------------------------------------------------- shared ----
    async def _finish(self, name: str) -> ConfigFlowResult:
        """Validate, de-duplicate and create the entry."""
        from . import hub_of

        mac = self._mac
        if mac is None:
            return self.async_abort(reason="invalid_mac")

        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured()
        if (taken := _taken_because(self.hass, mac)) is not None:
            return self.async_abort(reason=taken)

        hub = hub_of(self.hass)
        if hub is not None and hub.port != self._port:
            # The port belongs to the shared listener, not to one strip.
            self._port = hub.port
            return self.async_show_form(
                step_id="manual",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_MAC, default=mac): cv.string,
                        vol.Optional(CONF_NAME, default=name): cv.string,
                    }
                ),
                errors={CONF_PORT: "port_conflict"},
                description_placeholders={"running_port": str(hub.port)},
                last_step=True,
            )

        title = name or mac
        return self.async_create_entry(
            title=title,
            data={CONF_MAC: mac, CONF_NAME: title, CONF_PORT: self._port},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> Dc1OptionsFlow:
        return Dc1OptionsFlow(config_entry)


class Dc1OptionsFlow(OptionsFlowWithConfigEntry):
    """Rename a strip, and switch hands-off auto adding on or off."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.config_entry

        if user_input is not None:
            mac = normalize_mac(entry.data.get(CONF_MAC)) or ""
            name = user_input.get(CONF_NAME) or mac
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_NAME: name}
            )
            # auto_add governs the shared discovery behaviour, so mirror it onto
            # every entry of this domain instead of keeping N copies in sync.
            enabled = bool(user_input.get(CONF_AUTO_ADD))
            for other in _entries(self.hass):
                if bool(other.options.get(CONF_AUTO_ADD)) != enabled:
                    self.hass.config_entries.async_update_entry(
                        other, options={**other.options, CONF_AUTO_ADD: enabled}
                    )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME, default=entry.data.get(CONF_NAME, "")): cv.string,
                    vol.Optional(
                        CONF_AUTO_ADD, default=bool(entry.options.get(CONF_AUTO_ADD))
                    ): cv.boolean,
                }
            ),
            description_placeholders={"mac": normalize_mac(entry.data.get(CONF_MAC)) or "-"},
            last_step=True,
        )
