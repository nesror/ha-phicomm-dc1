"""Constants for the Phicomm DC1 integration."""
from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "phicomm_dc1"
PLATFORMS: Final = [Platform.SENSOR, Platform.SWITCH]

# --- config keys -------------------------------------------------------------
CONF_PORT: Final = "port"
CONF_PLUGS: Final = "plugs"
CONF_MAC: Final = "mac"
CONF_NAME: Final = "name"
CONF_AUTO_ADD: Final = "auto_add"
CONF_SWITCHES: Final = "switches"
CONF_VOLTAGE: Final = "voltage"
CONF_POWER: Final = "power"
CONF_REFRESH_INTERVAL: Final = "refresh_interval"
CONF_STALE_TIMEOUT: Final = "stale_timeout"
CONF_QUERY_DEBOUNCE: Final = "query_debounce"

# --- defaults ----------------------------------------------------------------
DEFAULT_PORT: Final = 8000
DEFAULT_AUTO_ADD: Final = False
AUTO_ADD_DEFAULT: Final = DEFAULT_AUTO_ADD
DEFAULT_REFRESH_INTERVAL: Final = 300
DEFAULT_STALE_TIMEOUT: Final = 900
DEFAULT_QUERY_DEBOUNCE: Final = 1.0

# --- protocol ----------------------------------------------------------------
# Bit position of each socket inside the 4 digit status word.
BIT_MASTER: Final = 0
BIT_SOCKET_1: Final = 1
BIT_SOCKET_2: Final = 2
BIT_SOCKET_3: Final = 3
SOCKET_BITS: Final = (BIT_MASTER, BIT_SOCKET_1, BIT_SOCKET_2, BIT_SOCKET_3)

# translation_key of every entity a strip exposes
TRANSLATION_KEY_BY_BIT: Final = {
    BIT_MASTER: "master",
    BIT_SOCKET_1: "socket_1",
    BIT_SOCKET_2: "socket_2",
    BIT_SOCKET_3: "socket_3",
}
TRANSLATION_KEY_VOLTAGE: Final = "voltage"
TRANSLATION_KEY_POWER: Final = "power"

# --- hass.data ---------------------------------------------------------------
DATA_YAML_PLUGS: Final = f"{DOMAIN}_yaml_plugs"

# --- device metadata ---------------------------------------------------------
MANUFACTURER: Final = "Phicomm 斐讯"
MODEL: Final = "DC1"
MODEL_ID: Final = "PLUG_DC1"
