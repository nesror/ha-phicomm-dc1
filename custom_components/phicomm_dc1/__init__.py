"""斐讯 Phicomm DC1 智能插排 (Phicomm DC1 smart power strip).

The strip has no local API.  It dials out to ``smartplugconnect.phicomm.com``
port 8000 and holds that connection open, so this integration plays the role of
the Phicomm cloud: point the hostname at the Home Assistant host with a DNS
override on the router, listen on 8000, and the strips walk in by themselves.

Two configuration styles are supported and can coexist:

* **UI / config entry** - one entry per strip, discovered automatically as soon
  as a strip connects.  Recommended: you get a proper device with translated
  entity names.
* **YAML** - the original style, where every socket entity is named explicitly.
  Useful when dashboards are already bound to fixed entity_ids.

The listening socket is a shared, reference-counted resource: the first strip
to be set up opens it, the last one to be removed closes it.  All entries must
agree on the port, because one host can only have one listener on it.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, SOURCE_DISCOVERY
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_AUTO_ADD,
    CONF_MAC,
    CONF_NAME,
    CONF_PLUGS,
    CONF_PORT,
    CONF_POWER,
    CONF_QUERY_DEBOUNCE,
    CONF_REFRESH_INTERVAL,
    CONF_STALE_TIMEOUT,
    CONF_SWITCHES,
    CONF_VOLTAGE,
    DATA_YAML_PLUGS,
    DEFAULT_AUTO_ADD,
    DEFAULT_PORT,
    DEFAULT_QUERY_DEBOUNCE,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_STALE_TIMEOUT,
    DOMAIN,
    PLATFORMS,
    SOCKET_BITS,
)
from .hub import Dc1Hub, Dc1Plug, SeenStrip, normalize_mac

_LOGGER = logging.getLogger(__name__)

SOCKET_COUNT = len(SOCKET_BITS)

YAML_PLUG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MAC): cv.string,
        vol.Optional(CONF_NAME, default=""): cv.string,
        # Exactly four entries: bit0 = master, bit1..bit3 = socket 1..3.  Use
        # null to skip a socket.  The order *is* the bit order, which is how you
        # reproduce (or repair) a legacy entity_id layout.
        vol.Optional(CONF_SWITCHES, default=None): vol.Any(
            None,
            vol.All(cv.ensure_list, [vol.Any(cv.string, None)], vol.Length(min=4, max=4)),
        ),
        vol.Optional(CONF_VOLTAGE, default=None): vol.Any(cv.string, None),
        vol.Optional(CONF_POWER, default=None): vol.Any(cv.string, None),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(DOMAIN): vol.Schema(
            {
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
                vol.Optional(CONF_REFRESH_INTERVAL, default=DEFAULT_REFRESH_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=0)
                ),
                vol.Optional(CONF_STALE_TIMEOUT, default=DEFAULT_STALE_TIMEOUT): vol.All(
                    vol.Coerce(int), vol.Range(min=0)
                ),
                vol.Optional(CONF_QUERY_DEBOUNCE, default=DEFAULT_QUERY_DEBOUNCE): vol.Coerce(float),
                vol.Optional(CONF_AUTO_ADD, default=DEFAULT_AUTO_ADD): cv.boolean,
                vol.Required(CONF_PLUGS): vol.All(cv.ensure_list, [YAML_PLUG_SCHEMA]),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


@dataclasses.dataclass
class Runtime:
    """The shared TCP server plus the bookkeeping needed to ref-count it."""

    hub: Dc1Hub
    port: int
    entry_macs: dict[str, str] = dataclasses.field(default_factory=dict)


def hub_of(hass: HomeAssistant) -> Dc1Hub | None:
    """The active server, or ``None`` before the first strip is set up."""
    current: Runtime | None = hass.data.get(DOMAIN)
    return current.hub if current else None


def yaml_block(hass: HomeAssistant) -> dict[str, Any]:
    return hass.data.get(DATA_YAML_PLUGS) or {}


# --------------------------------------------------------------------------- #
# plug construction
# --------------------------------------------------------------------------- #
def default_switch_names(mac: str) -> list[str]:
    """Fallback names used when a YAML plug does not list ``switches``."""
    base = mac.replace(":", "").lower()
    return [f"{base}_switch", f"{base}_switch1", f"{base}_switch2", f"{base}_switch3"]


def yaml_plugs(conf: dict[str, Any]) -> list[Dc1Plug]:
    """Turn the YAML block into plug objects with explicit entity names."""
    plugs: list[Dc1Plug] = []
    seen: set[str] = set()
    for raw in conf.get(CONF_PLUGS) or []:
        mac = normalize_mac(raw.get(CONF_MAC))
        if mac is None:
            _LOGGER.error("phicomm_dc1: 非法的 mac %r，已跳过该插排", raw.get(CONF_MAC))
            continue
        if mac in seen:
            _LOGGER.error("phicomm_dc1: mac %s 重复配置，已跳过后一条", mac)
            continue
        seen.add(mac)
        # ``vol.Optional(..., default=None)`` means "no default" to voluptuous,
        # so every optional key has to be read with .get().
        switches = raw.get(CONF_SWITCHES)
        if switches is None:
            switches = default_switch_names(mac)
        plugs.append(
            Dc1Plug(
                mac=mac,
                name=raw.get(CONF_NAME) or mac,
                switch_names=list(switches),
                voltage_name=raw.get(CONF_VOLTAGE),
                power_name=raw.get(CONF_POWER),
            )
        )
    return plugs


def plug_for_entry(entry: ConfigEntry) -> Dc1Plug | None:
    """Build the plug object a config entry describes."""
    mac = normalize_mac(entry.data.get(CONF_MAC))
    if mac is None:
        return None
    return Dc1Plug(mac=mac, name=entry.data.get(CONF_NAME) or mac)


# --------------------------------------------------------------------------- #
# YAML bootstrap
# --------------------------------------------------------------------------- #
async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Expose the YAML block to the platforms."""
    conf: dict[str, Any] | None = config.get(DOMAIN)
    if conf is None:
        return True

    plugs = yaml_plugs(conf)
    if not plugs:
        _LOGGER.error("phicomm_dc1: YAML 配置里没有可用的插排")
        return False

    hass.data[DATA_YAML_PLUGS] = {
        "plugs": plugs,
        "port": conf[CONF_PORT],
        "refresh_interval": conf[CONF_REFRESH_INTERVAL],
        "stale_timeout": conf[CONF_STALE_TIMEOUT],
        "query_debounce": conf[CONF_QUERY_DEBOUNCE],
        "auto_add": conf[CONF_AUTO_ADD],
    }
    _LOGGER.info("phicomm_dc1: YAML 模式声明了 %d 个插排", len(plugs))
    return True


async def async_ensure_server(hass: HomeAssistant) -> Dc1Hub | None:
    """Start the shared server for YAML plugs, or join the running one.

    Called from the legacy YAML platform setup, which is otherwise never able to
    bring the server up.
    """
    current: Runtime | None = hass.data.get(DOMAIN)
    if current is not None:
        return current.hub

    conf = yaml_block(hass)
    plugs = conf.get("plugs") or []
    if not plugs:
        return None

    hub = _new_hub(hass, conf["port"])
    hub.set_plugs(plugs)
    try:
        await hub.async_start()
    except OSError as err:
        _log_bind_error(hub, conf["port"], err)
        return None

    runtime = Runtime(hub=hub, port=conf["port"], entry_macs={})
    hass.data[DOMAIN] = runtime
    _listen_for_stop(hass)
    return hub


# --------------------------------------------------------------------------- #
# config entries
# --------------------------------------------------------------------------- #
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one strip added through the UI (or via discovery)."""
    plug = plug_for_entry(entry)
    if plug is None:
        _LOGGER.error("phicomm_dc1: 配置条目 %s 里的 mac 无效", entry.entry_id)
        return False

    port = int(entry.data.get(CONF_PORT) or DEFAULT_PORT)
    current: Runtime | None = hass.data.get(DOMAIN)

    if current is None:
        hub = _new_hub(hass, port)
        try:
            await hub.async_start()
        except OSError as err:
            _log_bind_error(hub, port, err)
            return False
        current = Runtime(hub=hub, port=port, entry_macs={})
        hass.data[DOMAIN] = current
        _listen_for_stop(hass)
    elif current.port != port:
        _LOGGER.error(
            "phicomm_dc1: 端口冲突 - 服务已在 %d 上监听，配置条目 %s 却要求 %d。"
            "一台主机只能有一个进程占用该端口，请把该条目的端口改回 %d。",
            current.port, entry.entry_id, port, current.port,
        )
        return False

    current.entry_macs[entry.entry_id] = plug.mac
    _apply_plugs(hass, current)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and close the server once nothing needs it."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    current: Runtime | None = hass.data.get(DOMAIN)
    if current is None:
        return True

    current.entry_macs.pop(entry.entry_id, None)
    if not current.entry_macs and not yaml_block(hass).get("plugs"):
        await current.hub.async_stop()
        hass.data.pop(DOMAIN, None)
        _LOGGER.info("phicomm_dc1: 已没有插排，停止 %d 端口监听", current.port)
        return True

    _apply_plugs(hass, current)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Re-set-up when the strip name or the options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _apply_plugs(hass: HomeAssistant, current: Runtime) -> None:
    """Rebuild the hub's plug table from the config entries (YAML names win)."""
    known: dict[str, Dc1Plug] = {}
    for entry_id, mac in list(current.entry_macs.items()):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            current.entry_macs.pop(entry_id, None)
            continue
        plug = plug_for_entry(entry)
        if plug is not None:
            known[plug.mac] = plug
    for plug in yaml_block(hass).get("plugs", []):
        known[plug.mac] = plug
    current.hub.set_plugs(known.values())


def _new_hub(hass: HomeAssistant, port: int) -> Dc1Hub:
    conf = yaml_block(hass)
    return Dc1Hub(
        hass,
        port=port,
        refresh_interval=conf.get("refresh_interval", DEFAULT_REFRESH_INTERVAL),
        stale_timeout=conf.get("stale_timeout", DEFAULT_STALE_TIMEOUT),
        query_debounce=conf.get("query_debounce", DEFAULT_QUERY_DEBOUNCE),
        on_unknown_mac=_make_discovery_callback(hass),
    )


def _log_bind_error(hub: Dc1Hub, port: int, err: OSError) -> None:
    _LOGGER.error(
        "phicomm_dc1: 无法监听 %d 端口 (%s)。请确认没有其他程序（例如仍在运行的 "
        "Node-RED DC1 流程）占用它，然后重启 Home Assistant。", port, err,
    )


@callback
def _listen_for_stop(hass: HomeAssistant) -> None:
    @callback
    def _async_on_stop(_event: Any) -> None:
        current: Runtime | None = hass.data.get(DOMAIN)
        if current is not None:
            hass.async_create_task(current.hub.async_stop())

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_on_stop)


def auto_add_enabled(hass: HomeAssistant) -> bool:
    """Whether newly seen strips should be added without asking."""
    conf = yaml_block(hass)
    if conf:
        return bool(conf.get("auto_add", DEFAULT_AUTO_ADD))
    return any(
        bool(entry.options.get(CONF_AUTO_ADD, DEFAULT_AUTO_ADD))
        for entry in hass.config_entries.async_entries(DOMAIN)
    )


def _make_discovery_callback(hass: HomeAssistant):
    """Surface every unknown strip as a Home Assistant discovery flow."""

    def _on_unknown(seen: SeenStrip) -> None:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_DISCOVERY},
                data={
                    CONF_MAC: seen.mac,
                    "address": seen.address,
                    "device_type": seen.device_type,
                },
            )
        )

    return _on_unknown
