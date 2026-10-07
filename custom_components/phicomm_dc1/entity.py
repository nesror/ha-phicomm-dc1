"""Shared entity behaviour for Phicomm DC1 strips."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, MODEL
from .hub import Dc1Hub, Dc1Plug

_LOGGER = logging.getLogger(__name__)


class Dc1Entity(Entity):
    """Base class: push updates, availability follows the TCP session.

    Two naming modes are supported on purpose:

    * ``translation_key`` + ``has_entity_name`` - the modern path used by
      entries added from the UI.  The device name becomes the prefix and the
      entity label comes from ``translations/<lang>.json``.
    * ``explicit_name`` - the legacy YAML path, where the caller supplies the
      exact object id so existing dashboards keep working.
    """

    _attr_should_poll = False

    def __init__(
        self,
        hub: Dc1Hub,
        plug: Dc1Plug,
        *,
        key: str,
        explicit_name: str | None = None,
        icon: str | None = None,
    ) -> None:
        self._hub = hub
        self._plug = plug
        self._key = key
        self._attr_unique_id = f"{DOMAIN}:{plug.mac}:{key}"
        if explicit_name:
            # ``Entity.suggested_object_id`` falls back to ``name``, so this also
            # pins the entity_id for the legacy YAML path.
            self._attr_has_entity_name = False
            self._attr_name = explicit_name
        else:
            self._attr_has_entity_name = True
            self._attr_translation_key = key
        if icon:
            self._attr_icon = icon

    # ---------------------------------------------------------- identity ---
    @property
    def device_info(self) -> dict[str, Any] | None:
        """Only meaningful for config entries; HA ignores it otherwise."""
        platform = getattr(self, "platform", None)
        if platform is None or platform.config_entry is None:
            return None
        return {
            "identifiers": {(DOMAIN, self._plug.mac)},
            "name": self._plug.name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "sw_version": "local (phicomm_dc1)",
            "serial_number": self._plug.mac,
        }

    @property
    def available(self) -> bool:
        return self._plug.connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"mac": self._plug.mac}

    # ------------------------------------------------------------ updates ---
    @callback
    def _async_handle_state_change(self) -> None:
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self._plug.add_listener(self._async_handle_state_change)
        self.async_on_remove(lambda: self._plug.remove_listener(self._async_handle_state_change))
