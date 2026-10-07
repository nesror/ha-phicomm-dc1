"""Sensor entities (voltage / power) for Phicomm DC1 power strips."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricPotential, UnitOfPower
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import CONF_MAC, DOMAIN, TRANSLATION_KEY_POWER, TRANSLATION_KEY_VOLTAGE
from .entity import Dc1Entity
from .hub import Dc1Hub, Dc1Plug, normalize_mac

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend({})

# key -> (plug attribute, device class, unit, icon)
KINDS: dict[str, tuple[str, SensorDeviceClass, str, str]] = {
    TRANSLATION_KEY_VOLTAGE: (
        "voltage",
        SensorDeviceClass.VOLTAGE,
        UnitOfElectricPotential.VOLT,
        "mdi:flash",
    ),
    TRANSLATION_KEY_POWER: (
        "power",
        SensorDeviceClass.POWER,
        UnitOfPower.WATT,
        "mdi:flash-auto",
    ),
}


def _hub(hass: HomeAssistant) -> Dc1Hub | None:
    current = hass.data.get(DOMAIN)
    return current.hub if current is not None else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the voltage and power sensor of the strip in this entry."""
    hub = _hub(hass)
    if hub is None:
        _LOGGER.error("phicomm_dc1: 服务尚未启动，无法创建传感器实体")
        return
    plug = hub.plugs.get(normalize_mac(entry.data.get(CONF_MAC)) or "")
    if plug is None:
        _LOGGER.warning("phicomm_dc1: 插排 %s 尚未在服务器上注册", entry.data.get(CONF_MAC))
        return
    async_add_entities(Dc1Sensor(hub, plug, key) for key in KINDS)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Legacy YAML path: sensors only when the plug names them explicitly."""
    from . import async_ensure_server  # here to avoid an import cycle at load time

    hub = await async_ensure_server(hass)
    if hub is None:
        return

    entities: list[Dc1Sensor] = []
    for plug in hub.plugs.values():
        if plug.voltage_name:
            entities.append(
                Dc1Sensor(hub, plug, TRANSLATION_KEY_VOLTAGE, explicit_name=plug.voltage_name)
            )
        if plug.power_name:
            entities.append(
                Dc1Sensor(hub, plug, TRANSLATION_KEY_POWER, explicit_name=plug.power_name)
            )
    async_add_entities(entities)


class Dc1Sensor(Dc1Entity, SensorEntity):
    """A numeric readout reported by the strip."""

    def __init__(
        self,
        hub: Dc1Hub,
        plug: Dc1Plug,
        key: str,
        explicit_name: str | None = None,
    ) -> None:
        attr, device_class, unit, icon = KINDS[key]
        super().__init__(hub, plug, key=key, explicit_name=explicit_name, icon=icon)
        self._attr = attr
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> Any:
        return getattr(self._plug, self._attr)
