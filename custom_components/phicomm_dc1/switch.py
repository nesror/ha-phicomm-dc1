"""Switch entities for Phicomm DC1 power strips."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import CONF_MAC, DOMAIN, SOCKET_BITS, TRANSLATION_KEY_BY_BIT
from .entity import Dc1Entity
from .hub import Dc1Hub, Dc1Plug, normalize_mac

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend({})


def _hub(hass: HomeAssistant) -> Dc1Hub | None:
    """The shared server, if one is running."""
    current = hass.data.get(DOMAIN)
    return current.hub if current is not None else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the four sockets of the strip this config entry describes."""
    hub = _hub(hass)
    if hub is None:
        _LOGGER.error("phicomm_dc1: 服务尚未启动，无法创建开关实体")
        return
    plug = hub.plugs.get(normalize_mac(entry.data.get(CONF_MAC)) or "")
    if plug is None:
        _LOGGER.warning("phicomm_dc1: 插排 %s 尚未在服务器上注册", entry.data.get(CONF_MAC))
        return
    async_add_entities(Dc1Socket(hub, plug, bit) for bit in SOCKET_BITS)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Legacy YAML path: one switch per explicitly named socket."""
    from . import async_ensure_server  # here to avoid an import cycle at load time

    hub = await async_ensure_server(hass)
    if hub is None:
        return

    entities: list[Dc1Socket] = []
    for plug in hub.plugs.values():
        for bit, name in enumerate(plug.switch_names):
            if not name:
                continue
            entities.append(Dc1Socket(hub, plug, bit, explicit_name=name))
    if not entities:
        _LOGGER.warning("phicomm_dc1: YAML 配置里没有声明任何开关通道")
    async_add_entities(entities)


class Dc1Socket(Dc1Entity, SwitchEntity):
    """One socket, or the master switch, of a DC1 strip."""

    def __init__(self, hub: Dc1Hub, plug: Dc1Plug, bit: int, explicit_name: str | None = None) -> None:
        super().__init__(
            hub,
            plug,
            key=TRANSLATION_KEY_BY_BIT[bit],
            explicit_name=explicit_name,
            icon="mdi:power-standby" if bit == 0 else "mdi:power-socket-au",
        )
        self._bit = bit

    @property
    def is_on(self) -> bool | None:
        return self._plug.socket_on(self._bit)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"mac": self._plug.mac, "bit": self._bit}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._hub.async_set_bit(self._plug, self._bit, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.async_set_bit(self._plug, self._bit, False)
