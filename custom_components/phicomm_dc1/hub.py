"""TCP server and per-strip state for the Phicomm DC1 integration.

The Phicomm DC1 has no local API and cannot be polled by IP: the firmware
dials out to ``smartplugconnect.phicomm.com:8000`` and keeps that connection
open.  This module plays the role of the Phicomm cloud so the strip talks to
Home Assistant instead (see the README for the DNS step that makes that
happen).

Wire protocol - one JSON object per line::

    strip -> HA : {"action":"activate=", "uuid":"activate=484", "auth":"",
                   "params":{"device_type":"PLUG_DC1_7", "mac":"68:C6:3A:81:F7:E6", ...}}
    strip -> HA : {"msg":"get datapoint success", "uuid":"68:C6:3A:81:F7:E6",
                   "result":{"status":"1010", "V":220, "P":35}}
    HA -> strip : {"action":"datapoint",  "params":{},             "uuid":"<mac>", "auth":""}
    HA -> strip : {"action":"datapoint=", "params":{"status":1010}, "uuid":"<mac>", "auth":""}

Note the two quirks that cost the most time to find:

* on a registration packet ``uuid`` holds a nonce (``activate=484``) and the
  real MAC lives in ``params.mac``; on a datapoint reply ``uuid`` *is* the MAC.
* ``status`` is a bitmask written as if its binary digits were decimal, so
  ``1010`` means bits 1 and 3 are set and is sent as the JSON number 1010.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import SOCKET_BITS

LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# protocol helpers
# --------------------------------------------------------------------------- #
def normalize_mac(raw: Any) -> str | None:
    """Return an upper case colon separated MAC, or ``None`` when it is not one."""
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip().upper().replace("-", ":").replace(".", ":")
    if len(cleaned) != 17:
        return None
    return cleaned


def status_to_bits(status: Any) -> int | None:
    """Decode the strip's ``status`` field (binary digits written as a number)."""
    if status is None:
        return None
    try:
        return int(str(status).strip(), 2)
    except (TypeError, ValueError):
        return None


def bits_to_status(bits: int) -> int:
    """Encode a bitmask the way the strip expects it (binary digits as a number)."""
    return int(format(max(bits, 0) & 0b1111, "b"))


def extract_mac(obj: dict) -> str | None:
    """Find the MAC of an inbound packet, honouring the two field layouts."""
    params = obj.get("params") if isinstance(obj.get("params"), dict) else {}
    candidates: list[Any] = []
    if obj.get("action") == "activate=":
        candidates.append(params.get("mac"))
    candidates.append(obj.get("uuid"))
    candidates.append(params.get("mac"))
    for candidate in candidates:
        mac = normalize_mac(candidate)
        if mac:
            return mac
    return None


class JsonStream:
    """Split a byte stream into top level JSON objects.

    Tolerates partial packets, several packets in one read, stray binary
    prefixes and ``{``/``}`` inside string values.  Anything that opens a brace
    but does not parse is dropped one byte at a time so the stream always
    resynchronises instead of wedging on garbage.
    """

    MAX_BUFFER = 65536

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[dict]:
        self._buf.extend(data)
        out: list[dict] = []
        while True:
            if len(self._buf) > self.MAX_BUFFER:
                LOGGER.debug("phicomm_dc1: dropping %d unparsable bytes", len(self._buf))
                self._buf.clear()
                return out
            start = self._buf.find(b"{")
            if start < 0:
                self._buf.clear()
                return out
            if start:
                del self._buf[:start]
            end = self._match_object()
            if end is None:
                return out  # incomplete object, wait for more bytes
            blob = bytes(self._buf[:end])
            try:
                parsed = json.loads(blob.decode("utf-8", "replace"))
            except (ValueError, UnicodeDecodeError):
                # The closing brace we found does not complete a valid object.
                # Drop this '{' and look for the next one.
                del self._buf[:1]
                continue
            del self._buf[:end]
            if isinstance(parsed, dict):
                out.append(parsed)

    def _match_object(self) -> int | None:
        """Exclusive index just past the first balanced ``{...}``, or None."""
        depth = 0
        in_str = False
        escaped = False
        for idx, char in enumerate(self._buf):
            if in_str:
                if escaped:
                    escaped = False
                elif char == 0x5C:
                    escaped = True
                elif char == 0x22:
                    in_str = False
                continue
            if char == 0x22:
                in_str = True
            elif char == 0x7B:
                depth += 1
            elif char == 0x7D:
                depth -= 1
                if depth == 0:
                    return idx + 1
        return None


# --------------------------------------------------------------------------- #
# device state
# --------------------------------------------------------------------------- #
@dataclass
class SeenStrip:
    """A strip that dialed in but is not configured yet."""

    mac: str
    address: str | None
    device_type: str | None
    first_seen: datetime
    last_seen: datetime


@dataclass
class Dc1Plug:
    """One DC1 power strip."""

    mac: str
    name: str
    switch_names: list[str | None] = field(default_factory=lambda: [None] * 4)
    voltage_name: str | None = None
    power_name: str | None = None
    status: int | None = None
    voltage: float | None = None
    power: float | None = None
    last_seen: datetime | None = None
    writer: asyncio.StreamWriter | None = None

    _listeners: list[Callable[[], None]] = field(default_factory=list, repr=False)
    _query_handle: asyncio.TimerHandle | None = field(default=None, repr=False)

    # ------------------------------------------------------------- state ----
    @property
    def connected(self) -> bool:
        return self.writer is not None and not self.writer.is_closing()

    def socket_on(self, bit: int) -> bool | None:
        if self.status is None:
            return None
        return bool((self.status >> bit) & 1)

    def add_listener(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self) -> None:
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:  # noqa: BLE001 - one bad listener must not kill the loop
                LOGGER.exception("phicomm_dc1: listener failed for %s", self.mac)

    # ----------------------------------------------------------- updates ----
    def apply_datapoint(self, result: dict) -> bool:
        """Merge one ``result`` payload into the cached state. Changed?"""
        changed = False
        if "status" in result:
            bits = status_to_bits(result.get("status"))
            if bits is not None and bits != self.status:
                self.status = bits
                changed = True
        for key, attr in (("V", "voltage"), ("P", "power")):
            if key in result:
                value = result.get(key)
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    value = None
                if value != getattr(self, attr):
                    setattr(self, attr, value)
                    changed = True
        self.last_seen = dt_util.utcnow()
        if changed:
            self._notify()
        return changed

    def mark_connected(self, writer: asyncio.StreamWriter) -> bool:
        was = self.connected
        self.writer = writer
        self.last_seen = dt_util.utcnow()
        if not was:
            self._notify()
        return not was

    def mark_disconnected(self) -> None:
        self.writer = None
        self._notify()

    # ---------------------------------------------------------- outgoing ----
    def _write(self, payload: dict) -> None:
        if self.writer is None or self.writer.is_closing():
            raise HomeAssistantError(f"Phicomm DC1 {self.name} ({self.mac}) 当前未连接")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        self.writer.write(body.encode("utf-8"))

    async def async_flush(self) -> None:
        if self.writer is not None and not self.writer.is_closing():
            try:
                await self.writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError):
                LOGGER.debug("phicomm_dc1: drain failed for %s", self.mac)

    def request_datapoint(self) -> None:
        self._write({"action": "datapoint", "params": {}, "uuid": self.mac, "auth": ""})

    def schedule_datapoint(self, loop: asyncio.AbstractEventLoop, delay: float) -> None:
        """Coalesce bursts of inbound packets into one query (Node-RED parity)."""
        if self._query_handle is not None:
            self._query_handle.cancel()

        def fire() -> None:
            self._query_handle = None
            try:
                self.request_datapoint()
            except HomeAssistantError:
                LOGGER.debug("phicomm_dc1: %s vanished before the query", self.mac)

        self._query_handle = loop.call_later(delay, fire)

    def set_bit(self, bit: int, on: bool, loop: asyncio.AbstractEventLoop) -> int:
        """Send a new status word and adopt it optimistically."""
        base = self.status if self.status is not None else 0
        new_bits = (base | (1 << bit)) if on else (base & ~(1 << bit))
        new_bits &= 0b1111
        LOGGER.debug(
            "phicomm_dc1: -> %s bit%d %s (%s -> %s)",
            self.mac, bit, "on" if on else "off", format(base, "04b"), format(new_bits, "04b"),
        )
        self._write(
            {
                "action": "datapoint=",
                "params": {"status": bits_to_status(new_bits)},
                "uuid": self.mac,
                "auth": "",
            }
        )
        # The original Node-RED flow kept the stale cached mask until the strip
        # replied, so two toggles inside one poll interval cancelled each other
        # out. Adopting the commanded mask makes rapid toggling behave.
        if new_bits != self.status:
            self.status = new_bits
            self._notify()
        self.schedule_datapoint(loop, 0.5)
        return new_bits


# --------------------------------------------------------------------------- #
# the hub
# --------------------------------------------------------------------------- #
class Dc1Hub:
    """Owns the listening socket, the configured strips and the seen list."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        port: int,
        refresh_interval: int,
        stale_timeout: int,
        query_debounce: float,
        on_unknown_mac: Callable[[SeenStrip], None] | None = None,
    ) -> None:
        self.hass = hass
        self.port = port
        self.refresh_interval = refresh_interval
        self.stale_timeout = stale_timeout
        self.query_debounce = query_debounce
        self.on_unknown_mac = on_unknown_mac
        self.plugs: dict[str, Dc1Plug] = {}
        self.seen: dict[str, SeenStrip] = {}
        self._warned_unknown: set[str] = set()
        self._warned_shapes: set[tuple] = set()
        self._server: asyncio.AbstractServer | None = None
        self._poll_task: asyncio.Task | None = None

    # -------------------------------------------------------------- setup ---
    def set_plugs(self, plugs: Iterable[Dc1Plug]) -> None:
        """Reconcile the configured strips.

        Existing :class:`Dc1Plug` objects are **reused**, never replaced: live
        entities hold a reference to them, so swapping the object would silently
        freeze their state.  Adding a second strip must not break the first one.
        """
        wanted = {plug.mac: plug for plug in plugs}

        for mac in list(self.plugs):
            if mac not in wanted:
                stale = self.plugs.pop(mac)
                stale.mark_disconnected()

        for mac, incoming in wanted.items():
            existing = self.plugs.get(mac)
            if existing is None:
                self.plugs[mac] = incoming
                self.seen.pop(mac, None)
                continue
            existing.name = incoming.name
            # Adopt explicit YAML entity names when the incoming definition has
            # any; UI entries leave them all None and rely on translation keys.
            if any(incoming.switch_names):
                existing.switch_names = list(incoming.switch_names)
            if incoming.voltage_name:
                existing.voltage_name = incoming.voltage_name
            if incoming.power_name:
                existing.power_name = incoming.power_name

    async def async_start(self) -> None:
        self._server = await asyncio.start_server(self._handle_connection, "0.0.0.0", self.port)
        if self.refresh_interval:
            # Must be a *background* task: a task created during async_setup is
            # awaited by the bootstrap stage and makes HA log
            # "Setup timed out for bootstrap waiting on ...".
            self._poll_task = self.hass.async_create_background_task(
                self._async_poll_loop(), "phicomm_dc1 poll", eager_start=False
            )
        LOGGER.info(
            "phicomm_dc1: listening on 0.0.0.0:%d for %d strip(s): %s",
            self.port, len(self.plugs), ", ".join(sorted(self.plugs)) or "(none yet)",
        )

    async def async_stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:  # noqa: BLE001
                LOGGER.debug("phicomm_dc1: error closing the server", exc_info=True)
            self._server = None
        for plug in list(self.plugs.values()):
            if plug._query_handle is not None:  # noqa: SLF001
                plug._query_handle.cancel()  # noqa: SLF001
                plug._query_handle = None
            if plug.writer is not None:
                try:
                    plug.writer.close()
                except Exception:  # noqa: BLE001
                    pass
                plug.writer = None

    # ------------------------------------------------------------ inbound ---
    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        address = peer[0] if isinstance(peer, tuple) and peer else None
        stream = JsonStream()
        plug: Dc1Plug | None = None
        first_chunk = True
        LOGGER.debug("phicomm_dc1: connection from %s", peer)
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                if first_chunk:
                    first_chunk = False
                    LOGGER.debug("phicomm_dc1: %s first packet %r", address, data[:300])
                for obj in stream.feed(data):
                    plug = await self._handle_object(obj, writer, plug, address)
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        except Exception:  # noqa: BLE001
            LOGGER.exception("phicomm_dc1: connection %s failed", peer)
        finally:
            if plug is not None and plug.writer is writer:
                plug.mark_disconnected()
                LOGGER.debug("phicomm_dc1: %s (%s) disconnected", plug.name, plug.mac)
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    async def _handle_object(
        self,
        obj: dict,
        writer: asyncio.StreamWriter,
        known: Dc1Plug | None,
        address: str | None,
    ) -> Dc1Plug | None:
        LOGGER.debug("phicomm_dc1: <- %s", obj)
        action = obj.get("action")
        msg = obj.get("msg")
        mac = extract_mac(obj) or (known.mac if known is not None else None)

        plug = self.plugs.get(mac) if mac else None
        if plug is None:
            if mac:
                self._note_seen(mac, address, obj)
            else:
                shape = (tuple(sorted(obj.keys())), action, msg)
                if shape not in self._warned_shapes:
                    self._warned_shapes.add(shape)
                    params = obj.get("params") if isinstance(obj.get("params"), dict) else {}
                    LOGGER.warning(
                        "phicomm_dc1: 报文里没有可用的 MAC，已忽略。字段=%s action=%r msg=%r params=%s",
                        sorted(obj.keys()), action, msg, sorted(params.keys()),
                    )
            return known

        if plug.mark_connected(writer):
            LOGGER.info("phicomm_dc1: %s (%s) 已连接", plug.name, plug.mac)

        if action == "activate=" or msg == "get datapoint success":
            plug.schedule_datapoint(self.hass.loop, self.query_debounce)

        if msg == "get datapoint success" and isinstance(obj.get("result"), dict):
            plug.apply_datapoint(obj["result"])

        return plug

    def _note_seen(self, mac: str, address: str | None, obj: dict) -> None:
        """Remember an unconfigured strip and let the integration discover it."""
        now = dt_util.utcnow()
        params = obj.get("params") if isinstance(obj.get("params"), dict) else {}
        existing = self.seen.get(mac)
        if existing is None:
            self.seen[mac] = SeenStrip(
                mac=mac,
                address=address,
                device_type=params.get("device_type"),
                first_seen=now,
                last_seen=now,
            )
            if mac not in self._warned_unknown:
                self._warned_unknown.add(mac)
                LOGGER.warning(
                    "phicomm_dc1: 发现未配置的插排 %s（来自 %s），可在"
                    " 设置 > 设备与服务 > Phicomm DC1 > 配置 里添加",
                    mac, address,
                )
            if self.on_unknown_mac is not None:
                try:
                    self.on_unknown_mac(self.seen[mac])
                except Exception:  # noqa: BLE001 - discovery is best effort
                    LOGGER.exception("phicomm_dc1: discovery callback failed for %s", mac)
        else:
            existing.last_seen = now
            existing.address = address or existing.address

    # ----------------------------------------------------------- outbound ---
    async def async_set_bit(self, plug: Dc1Plug, bit: int, on: bool) -> None:
        if bit not in SOCKET_BITS:
            raise HomeAssistantError(f"phicomm_dc1: 非法的通道号 {bit}")
        # StreamWriter.write() has to run on the event loop, so no executor here.
        plug.set_bit(bit, on, self.hass.loop)
        await plug.async_flush()

    async def async_refresh(self, plug: Dc1Plug) -> None:
        plug.request_datapoint()
        await plug.async_flush()

    # -------------------------------------------------------------- house ---
    async def _async_poll_loop(self) -> None:
        step = max(min(self.refresh_interval or 300, 60), 30)
        while True:
            try:
                await asyncio.sleep(step)
            except asyncio.CancelledError:
                return
            now = dt_util.utcnow()
            for plug in list(self.plugs.values()):
                try:
                    if not plug.connected or plug.last_seen is None:
                        continue
                    idle = now - plug.last_seen
                    if self.stale_timeout and idle > timedelta(seconds=self.stale_timeout):
                        LOGGER.info(
                            "phicomm_dc1: %s 静默超过 %ds，断开以触发重连", plug.name, self.stale_timeout
                        )
                        if plug.writer is not None:
                            plug.writer.close()
                        continue
                    if self.refresh_interval and idle > timedelta(seconds=self.refresh_interval):
                        await self.async_refresh(plug)
                except Exception:  # noqa: BLE001
                    LOGGER.exception("phicomm_dc1: poll error for %s", plug.mac)
