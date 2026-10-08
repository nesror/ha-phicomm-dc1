#!/usr/bin/env python3
"""Offline self-check for the phicomm_dc1 integration.

Home Assistant is not required: the handful of HA modules the integration
imports are stubbed here, which lets us

  * byte-compile every module,
  * exercise the wire protocol against packets captured from real hardware,
  * validate the YAML CONFIG_SCHEMA,
  * drive the config flow end to end (manual, detected, discovery, auto-add),
  * build every entity in both naming modes,
  * and check manifest / strings / translation consistency.

Run:  python tools/selfcheck.py
"""
from __future__ import annotations

import asyncio
import json
import re
import os
import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace

import voluptuous as vol

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, 'custom_components', 'phicomm_dc1')

FAILURES: list[str] = []
CHECKS = 0


def check(label: str, got, want) -> None:
    global CHECKS
    CHECKS += 1
    ok = got == want
    if not ok:
        FAILURES.append(f"{label}: got {got!r} want {want!r}")
    print(f'{"PASS" if ok else "FAIL"}  {label}' + ('' if ok else f'\n        got={got!r}\n        want={want!r}'))


def check_true(label: str, value) -> None:
    check(label, bool(value), True)


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


# --------------------------------------------------------------------------- #
# Home Assistant stubs
# --------------------------------------------------------------------------- #
def install_ha_stubs() -> None:
    ha = types.ModuleType('homeassistant')

    core = types.ModuleType('homeassistant.core')

    class HomeAssistant:
        pass

    def callback(func):
        return func

    core.HomeAssistant = HomeAssistant
    core.callback = callback

    const = types.ModuleType('homeassistant.const')
    const.EVENT_HOMEASSISTANT_STOP = 'homeassistant_stop'
    const.CONF_NAME = 'name'
    const.CONF_PORT = 'port'

    class Platform:
        SENSOR = 'sensor'
        SWITCH = 'switch'

    const.Platform = Platform

    class _Unit(str):
        """HA's unit enums are ``str`` subclasses; behave like them."""

        def __new__(cls, value):
            return super().__new__(cls, value)

    const.UnitOfElectricPotential = SimpleNamespace(VOLT=_Unit('V'))
    const.UnitOfPower = SimpleNamespace(WATT=_Unit('W'))

    exceptions = types.ModuleType('homeassistant.exceptions')

    class HomeAssistantError(Exception):
        pass

    exceptions.HomeAssistantError = HomeAssistantError

    util = types.ModuleType('homeassistant.util')
    dt = types.ModuleType('homeassistant.util.dt')
    dt.utcnow = lambda: datetime.now(timezone.utc)
    util.dt = dt

    helpers = types.ModuleType('homeassistant.helpers')

    cv = types.ModuleType('homeassistant.helpers.config_validation')
    cv.string = vol.Schema(str)
    cv.boolean = vol.Boolean()
    cv.port = vol.All(vol.Coerce(int), vol.Range(min=1, max=65535))
    cv.ensure_list = lambda value: value if isinstance(value, list) else [value]
    cv.PLATFORM_SCHEMA = vol.Schema(
        {vol.Required('platform'): str}, extra=vol.ALLOW_EXTRA
    )
    helpers.config_validation = cv

    typing_mod = types.ModuleType('homeassistant.helpers.typing')
    typing_mod.ConfigType = dict
    typing_mod.DiscoveryInfoType = dict

    entity_helpers = types.ModuleType('homeassistant.helpers.entity')

    class Entity:
        def __init__(self):
            self.hass = None
            self.platform = None
            self.entity_id = None
            self._on_remove = []

        @property
        def name(self):
            return getattr(self, '_attr_name', None)

        async def async_added_to_hass(self):  # pragma: no cover - overridden
            pass

        def async_write_ha_state(self):
            pass

        def async_on_remove(self, func):
            self._on_remove.append(func)

    entity_helpers.Entity = Entity

    eplatform = types.ModuleType('homeassistant.helpers.entity_platform')
    eplatform.AddEntitiesCallback = object

    selector = types.ModuleType('homeassistant.helpers.selector')

    class SelectSelectorConfig:
        def __init__(self, options=None, multiple=False, translation_key=None):
            self.options = options
            self.multiple = multiple
            self.translation_key = translation_key

    class SelectorBase:
        """HA selectors are callable, which is what makes them usable as schemas."""

        def __init__(self, config):
            self.config = config

        def __call__(self, value):
            return value

    class SelectSelector(SelectorBase):
        pass

    selector.SelectSelector = SelectSelector
    selector.SelectSelectorConfig = SelectSelectorConfig

    config_entries = types.ModuleType('homeassistant.config_entries')
    config_entries.SOURCE_DISCOVERY = 'discovery'
    config_entries.SOURCE_USER = 'user'
    config_entries.ConfigEntry = SimpleNamespace
    config_entries.ConfigFlowResult = dict

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

        def __init__(self):
            self.hass = None
            self.context = {}

        async def async_set_unique_id(self, unique_id, **kwargs):
            self._unique_id = unique_id

        def _abort_if_unique_id_configured(self):
            return None

        def async_show_form(self, **kwargs):
            return {'type': 'form', **kwargs}

        def async_create_entry(self, **kwargs):
            return {'type': 'create_entry', **kwargs}

        def async_abort(self, **kwargs):
            return {'type': 'abort', **kwargs}

    config_entries.ConfigFlow = ConfigFlow

    class OptionsFlowWithConfigEntry:
        def __init__(self, config_entry):
            self.config_entry = config_entry
            self.hass = None

        def async_show_form(self, **kwargs):
            return {'type': 'form', **kwargs}

        def async_create_entry(self, **kwargs):
            return {'type': 'create_entry', **kwargs}

    config_entries.OptionsFlowWithConfigEntry = OptionsFlowWithConfigEntry

    components = types.ModuleType('homeassistant.components')
    switch_comp = types.ModuleType('homeassistant.components.switch')

    class SwitchEntity(Entity):
        pass

    switch_comp.SwitchEntity = SwitchEntity

    sensor_comp = types.ModuleType('homeassistant.components.sensor')

    class SensorEntity(Entity):
        pass

    class SensorDeviceClass:
        VOLTAGE = 'voltage'
        POWER = 'power'

    class SensorStateClass:
        MEASUREMENT = 'measurement'

    sensor_comp.SensorEntity = SensorEntity
    sensor_comp.SensorDeviceClass = SensorDeviceClass
    sensor_comp.SensorStateClass = SensorStateClass

    data_entry_flow = types.ModuleType('homeassistant.data_entry_flow')

    modules = {
        'homeassistant': ha,
        'homeassistant.core': core,
        'homeassistant.const': const,
        'homeassistant.exceptions': exceptions,
        'homeassistant.util': util,
        'homeassistant.util.dt': dt,
        'homeassistant.helpers': helpers,
        'homeassistant.helpers.config_validation': cv,
        'homeassistant.helpers.typing': typing_mod,
        'homeassistant.helpers.entity': entity_helpers,
        'homeassistant.helpers.entity_platform': eplatform,
        'homeassistant.helpers.selector': selector,
        'homeassistant.config_entries': config_entries,
        'homeassistant.components': components,
        'homeassistant.components.switch': switch_comp,
        'homeassistant.components.sensor': sensor_comp,
        'homeassistant.data_entry_flow': data_entry_flow,
    }
    for name, module in modules.items():
        sys.modules[name] = module

    ha.core = core
    ha.const = const
    ha.exceptions = exceptions
    ha.util = util
    ha.helpers = helpers
    ha.config_entries = config_entries
    ha.components = components
    ha.data_entry_flow = data_entry_flow


install_ha_stubs()

pkg = types.ModuleType('phicomm_dc1')
pkg.__path__ = [PKG]
sys.modules['phicomm_dc1'] = pkg


def load(name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f'phicomm_dc1.{name}', os.path.join(PKG, f'{name}.py')
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f'phicomm_dc1.{name}'] = module
    spec.loader.exec_module(module)
    return module


section('1. 源码编译与模块导入')
py_files = sorted(f for f in os.listdir(PKG) if f.endswith('.py'))
for fname in py_files:
    path = os.path.join(PKG, fname)
    try:
        compile(open(path, encoding='utf-8').read(), path, 'exec')
        print(f'      compiled {fname}')
    except SyntaxError as err:
        FAILURES.append(f'compile {fname}: {err}')
        print(f'FAIL  compile {fname}: {err}')

const = load('const')
hub = load('hub')
entity = load('entity')
init = load('__init__')
# Relative imports such as ``from . import hub_of`` inside the platform and
# config-flow modules resolve against the package, so make the package BE the
# loaded __init__ module.
init.__path__ = [PKG]
sys.modules['phicomm_dc1'] = init
switch = load('switch')
sensor = load('sensor')
config_flow = load('config_flow')
check('module count', len(py_files) >= 7, True)

section('2. 协议：MAC 与 status 位掩码')
check('normalize_mac lower', hub.normalize_mac('68:c6:3a:81:f7:e6'), '68:C6:3A:81:F7:E6')
check('normalize_mac dash', hub.normalize_mac('68-c6-3a-81-f7-e6'), '68:C6:3A:81:F7:E6')
check('normalize_mac nonce rejected', hub.normalize_mac('activate=484'), None)
check('normalize_mac short', hub.normalize_mac('ab:cd'), None)
check('normalize_mac none', hub.normalize_mac(None), None)
for bits in range(16):
    check(f'status roundtrip {bits:04b}', hub.status_to_bits(hub.bits_to_status(bits)), bits)
check('status from string', hub.status_to_bits('1010'), 10)
check('status from number', hub.status_to_bits(1010), 10)
check('status leading zeros', hub.status_to_bits('0111'), 7)
check('status garbage', hub.status_to_bits('nope'), None)
check('wire digits for 8', hub.bits_to_status(0b1000), 1000)
check('wire digits for 0', hub.bits_to_status(0), 0)

section('3. 协议：真实抓到的报文')
REAL_ACTIVATE = (
    b'{"action":"activate=","uuid":"activate=484","auth":"",'
    b'"params":{"device_type":"PLUG_DC1_7","mac":"68:C6:3A:81:F7:E6","ssid":"iOT"}}\n'
)
REAL_REPLY = (
    b'{"msg":"get datapoint success","uuid":"68:C6:3A:81:F7:E6",'
    b'"result":{"status":"0010","V":221,"P":37}}\n'
)
objs = hub.JsonStream().feed(REAL_ACTIVATE + REAL_REPLY)
check('two packets recovered', len(objs), 2)
check('activate= MAC comes from params.mac', hub.extract_mac(objs[0]), '68:C6:3A:81:F7:E6')
check('reply MAC comes from uuid', hub.extract_mac(objs[1]), '68:C6:3A:81:F7:E6')

s2 = hub.JsonStream()
check('partial buffered', s2.feed(b'{"msg":"get datapoint success","uui'), [])
check('partial completed', len(s2.feed(b'd":"AA:BB:CC:DD:EE:FF"}')), 1)
check('braces in strings', len(hub.JsonStream().feed(b'{"a":"x{y}z","b":1}\n')), 1)
check('binary prefix skipped', len(hub.JsonStream().feed(b'\x00\x01{"uuid":"x"}')), 1)
check('garbage resyncs', len(hub.JsonStream().feed(b'{{not json}}{"uuid":"ok"}')), 1)
check('empty stream', hub.JsonStream().feed(b''), [])

section('4. 控制帧字节级比对')


class FakeWriter:
    def __init__(self):
        self.frames: list[bytes] = []

    def write(self, data):
        self.frames.append(data)

    def is_closing(self):
        return False


async def drive_control():
    loop = asyncio.get_running_loop()
    plug = hub.Dc1Plug('68:C6:3A:81:F7:E6', '客厅', ['dc1_swiitch', 'dc1_swiitch1', 'dc1_swiitch3', 'dc1_swiitch2'])
    plug.writer = FakeWriter()
    plug.apply_datapoint({'status': '0010'})
    plug.set_bit(1, False, loop)   # 0010 -> 0000
    plug.set_bit(0, True, loop)    # 0000 -> 0001
    plug.set_bit(3, True, loop)    # 0001 -> 1001
    return plug


plug = asyncio.run(drive_control())
decoded = [json.loads(f.decode()) for f in plug.writer.frames]
check('three control frames', len(decoded), 3)
check('frame0 status', decoded[0]['params']['status'], 0)
check('frame1 status', decoded[1]['params']['status'], 1)
check('frame2 status', decoded[2]['params']['status'], 1001)
check('frames newline terminated', all(f.endswith(b'\n') for f in plug.writer.frames), True)
check(
    'exact wire bytes',
    plug.writer.frames[2].decode().strip(),
    '{"action":"datapoint=","params":{"status":1001},"uuid":"68:C6:3A:81:F7:E6","auth":""}',
)
check('optimistic status adopted', plug.status, 0b1001)

async def drive_query():
    fake_hub = hub.Dc1Hub.__new__(hub.Dc1Hub)
    p = hub.Dc1Plug('68:C6:3A:81:F7:E6', '客厅', ['a', 'b', 'c', 'd'])
    fake_hub.plugs = {p.mac: p}
    fake_hub.seen = {}
    fake_hub.query_debounce = 0.0
    fake_hub._warned_unknown = set()
    fake_hub._warned_shapes = set()
    fake_hub.on_unknown_mac = None
    fake_hub.hass = SimpleNamespace(loop=asyncio.get_running_loop())
    w = FakeWriter()
    current = None
    for obj in objs:
        current = await fake_hub._handle_object(obj, w, current, '192.168.31.155')
    return p, w, current, fake_hub


p, w, current, fake_hub = asyncio.run(drive_query())
check('known strip recognised', current is p, True)
check('strip marked connected', p.connected, True)
check('datapoint query sent', len(w.frames), 1)
check(
    'query frame',
    json.loads(w.frames[0].decode()),
    {'action': 'datapoint', 'params': {}, 'uuid': '68:C6:3A:81:F7:E6', 'auth': ''},
)
check('status applied', p.status, 0b0010)
check('voltage applied', p.voltage, 221.0)
check('power applied', p.power, 37.0)
check('seen list stays empty for known mac', len(fake_hub.seen), 0)

async def drive_unknown():
    captured: list = []
    h = hub.Dc1Hub.__new__(hub.Dc1Hub)
    h.plugs = {}
    h.seen = {}
    h.query_debounce = 0.0
    h._warned_unknown = set()
    h._warned_shapes = set()
    h.on_unknown_mac = captured.append
    h.hass = SimpleNamespace(loop=asyncio.get_running_loop())
    await h._handle_object(json.loads(REAL_ACTIVATE.decode()), FakeWriter(), None, '192.168.31.77')
    await h._handle_object(json.loads(REAL_ACTIVATE.decode()), FakeWriter(), None, '192.168.31.77')
    return captured, h


captured, h = asyncio.run(drive_unknown())
check('unknown strip recorded once', len(captured), 1)
check('unknown strip in seen', list(h.seen), ['68:C6:3A:81:F7:E6'])
check('seen keeps source address', h.seen['68:C6:3A:81:F7:E6'].address, '192.168.31.77')
check('seen keeps device_type', h.seen['68:C6:3A:81:F7:E6'].device_type, 'PLUG_DC1_7')

async def drive_unattributable():
    h2 = hub.Dc1Hub.__new__(hub.Dc1Hub)
    h2.plugs = {}
    h2.seen = {}
    h2.query_debounce = 0.0
    h2._warned_unknown = set()
    h2._warned_shapes = set()
    h2.on_unknown_mac = None
    h2.hass = SimpleNamespace(loop=asyncio.get_running_loop())
    out = await h2._handle_object({'action': 'weird'}, FakeWriter(), None, '1.2.3.4')
    return out


check('unattributable packet ignored', asyncio.run(drive_unattributable()), None)

section('5. YAML CONFIG_SCHEMA')
good = {
    'phicomm_dc1': {
        'plugs': [
            {'mac': '68:C6:3A:81:F7:E6', 'name': '客厅',
             'switches': ['dc1_swiitch', 'dc1_swiitch1', 'dc1_swiitch3', 'dc1_swiitch2'],
             'voltage': 'dc1_dianya', 'power': 'dc1_dianliu'},
            {'mac': '84:f3:eb:07:c2:ec'},
        ]
    }
}
validated = init.CONFIG_SCHEMA(good)
check('yaml port default', validated['phicomm_dc1']['port'], 8000)
check('yaml refresh default', validated['phicomm_dc1']['refresh_interval'], 300)
check('yaml auto_add default', validated['phicomm_dc1']['auto_add'], False)
plugs = init.yaml_plugs(validated['phicomm_dc1'])
check('two plugs parsed', len(plugs), 2)
check('legacy bit order preserved', plugs[0].switch_names,
      ['dc1_swiitch', 'dc1_swiitch1', 'dc1_swiitch3', 'dc1_swiitch2'])
check('mac normalised', plugs[1].mac, '84:F3:EB:07:C2:EC')
check('implicit switch names', plugs[1].switch_names[0], '84f3eb07c2ec_switch')
check('implicit voltage name unset', plugs[1].voltage_name, None)

for label, bad in [
    ('wrong switch count', {'phicomm_dc1': {'plugs': [{'mac': 'AA:BB:CC:DD:EE:FF', 'switches': ['a', 'b']}]}}),
    ('missing mac', {'phicomm_dc1': {'plugs': [{'name': 'x'}]}}),
    ('bad port', {'phicomm_dc1': {'port': 99999, 'plugs': [{'mac': 'AA:BB:CC:DD:EE:FF'}]}}),
    ('no plugs', {'phicomm_dc1': {}}),
]:
    try:
        init.CONFIG_SCHEMA(bad)
        check(label + ' rejected', 'accepted', 'rejected')
    except vol.Invalid:
        check(label + ' rejected', True, True)

check('unrelated config passes through', init.CONFIG_SCHEMA({'logger': {'default': 'warn'}}),
      {'logger': {'default': 'warn'}})

check('bad mac skipped', len(init.yaml_plugs({'plugs': [{'mac': 'nonsense'}]})), 0)
check('duplicate mac skipped', len(init.yaml_plugs(
    {'plugs': [{'mac': 'AA:BB:CC:DD:EE:FF'}, {'mac': 'aa:bb:cc:dd:ee:ff'}]})), 1)

section('6. 实体：两种命名模式')
h_for_entities = SimpleNamespace(plugs={}, async_set_bit=lambda *a: None)
yaml_plug = hub.Dc1Plug('68:C6:3A:81:F7:E6', '客厅',
                        ['dc1_swiitch', 'dc1_swiitch1', 'dc1_swiitch3', 'dc1_swiitch2'],
                        'dc1_dianya', 'dc1_dianliu')

legacy = [switch.Dc1Socket(h_for_entities, yaml_plug, bit, explicit_name=yaml_plug.switch_names[bit])
          for bit in range(4)]
check('legacy names', [e.name for e in legacy],
      ['dc1_swiitch', 'dc1_swiitch1', 'dc1_swiitch3', 'dc1_swiitch2'])
check('legacy has_entity_name off', legacy[2]._attr_has_entity_name, False)
check('legacy unique ids', [e._attr_unique_id for e in legacy],
      ['phicomm_dc1:68:C6:3A:81:F7:E6:' + k
       for k in ('master', 'socket_1', 'socket_2', 'socket_3')])
check('legacy device_info suppressed without entry', legacy[0].device_info, None)
legacy[0].platform = SimpleNamespace(config_entry=object())
check_true('device_info present with a config entry', legacy[0].device_info)
legacy[0].platform = None

ui_plug = hub.Dc1Plug('2C:3A:E8:3C:41:F5', '书房B', [None] * 4)
modern = [switch.Dc1Socket(h_for_entities, ui_plug, bit) for bit in range(4)]
check('modern translation keys', [e._attr_translation_key for e in modern],
      ['master', 'socket_1', 'socket_2', 'socket_3'])
check('modern has_entity_name on', modern[0]._attr_has_entity_name, True)
check('modern name unset', getattr(modern[0], '_attr_name', None), None)
check('modern icons', [e._attr_icon for e in modern],
      ['mdi:power-standby', 'mdi:power-socket-au', 'mdi:power-socket-au', 'mdi:power-socket-au'])

ui_plug.status = 0b1010
check('is_on bit1', modern[1].is_on, True)
check('is_on bit2', modern[2].is_on, False)
check('is_on bit3', modern[3].is_on, True)
ui_plug.status = None
check('is_on unknown before first report', modern[0].is_on, None)
check('unavailable before first contact', modern[0].available, False)
check('switch attrs', modern[1].extra_state_attributes, {'mac': '2C:3A:E8:3C:41:F5', 'bit': 1})

sensors = [sensor.Dc1Sensor(h_for_entities, yaml_plug, key, explicit_name=name)
           for key, name in (('voltage', 'dc1_dianya'), ('power', 'dc1_dianliu'))]
check('sensor names', [s.name for s in sensors], ['dc1_dianya', 'dc1_dianliu'])
check('sensor units', [s._attr_native_unit_of_measurement for s in sensors], ['V', 'W'])
check('sensor device classes', [s._attr_device_class for s in sensors], ['voltage', 'power'])
yaml_plug.voltage = 220.5
check('sensor value', sensors[0].native_value, 220.5)
modern_sensors = [sensor.Dc1Sensor(h_for_entities, ui_plug, key) for key in sensor.KINDS]
check('modern sensor keys', [s._attr_translation_key for s in modern_sensors], ['voltage', 'power'])

section('6b. 增删插排时实体不能被冻结')


def make_hub():
    return hub.Dc1Hub(
        SimpleNamespace(loop=asyncio.new_event_loop()),
        port=8000, refresh_interval=0, stale_timeout=0, query_debounce=0.0,
    )


h_live = make_hub()
plug_a = hub.Dc1Plug('68:C6:3A:81:F7:E6', 'A', [None] * 4)
h_live.set_plugs([plug_a])
entity_a = switch.Dc1Socket(h_live, h_live.plugs['68:C6:3A:81:F7:E6'], 1)
fired: list[int] = []
h_live.plugs['68:C6:3A:81:F7:E6'].add_listener(lambda: fired.append(1))

plug_a_renamed = hub.Dc1Plug('68:C6:3A:81:F7:E6', 'A 改名', [None] * 4)
plug_b = hub.Dc1Plug('2C:3A:E8:3C:41:F5', 'B', [None] * 4)
h_live.set_plugs([plug_a_renamed, plug_b])

check('existing plug object reused', h_live.plugs['68:C6:3A:81:F7:E6'] is plug_a, True)
check('name updated in place', plug_a.name, 'A 改名')
check('second strip added', sorted(h_live.plugs), ['2C:3A:E8:3C:41:F5', '68:C6:3A:81:F7:E6'])
plug_a.apply_datapoint({'status': '1111'})
check('entity still sees updates after a resync', entity_a.is_on, True)
check('listener survived the resync', len(fired), 1)

h_live.set_plugs([plug_b])
check('removed strip dropped', list(h_live.plugs), ['2C:3A:E8:3C:41:F5'])
check('removed strip marked disconnected', plug_b.writer is None, True)

yaml_named = hub.Dc1Plug('AA:BB:CC:DD:EE:FF', 'Y', ['n0', 'n1', 'n2', 'n3'], 'nv', 'np')
h_live.set_plugs([yaml_named])
h_live.set_plugs([hub.Dc1Plug('AA:BB:CC:DD:EE:FF', 'Y', [None] * 4)])
check('yaml names not wiped by a UI resync', h_live.plugs['AA:BB:CC:DD:EE:FF'].switch_names,
      ['n0', 'n1', 'n2', 'n3'])
check('yaml sensor names not wiped', h_live.plugs['AA:BB:CC:DD:EE:FF'].voltage_name, 'nv')

section('7. 配置流程')


class FakeConfigEntries:
    def __init__(self, entries=None):
        self._entries = entries or []
        self.created: list[dict] = []
        self.flows_started: list[dict] = []

    def async_entries(self, domain=None):
        return list(self._entries)

    def async_get_entry(self, entry_id):
        for entry in self._entries:
            if entry.entry_id == entry_id:
                return entry
        return None

    def async_update_entry(self, entry, **kwargs):
        for key, value in kwargs.items():
            setattr(entry, key, value)

    class _Flow:
        def __init__(self, owner):
            self._owner = owner

        async def async_init(self, domain, context=None, data=None):
            self._owner.flows_started.append({'domain': domain, 'context': context, 'data': data})

    @property
    def flow(self):
        return self._Flow(self)


class FakeHass:
    def __init__(self, entries=None, data=None):
        self.config_entries = FakeConfigEntries(entries)
        self.data = data if data is not None else {}
        self.bus = SimpleNamespace(async_listen_once=lambda *a: None)
        self.loop = asyncio.get_running_loop()

    def async_create_task(self, coro):
        asyncio.ensure_future(coro)


def make_flow(hass):
    flow = config_flow.Dc1ConfigFlow()
    flow.hass = hass
    return flow


async def flow_scenarios():
    # --- manual, first ever strip: the port is asked for -------------------
    hass = FakeHass()
    started = hass.data[const.DOMAIN] = SimpleNamespace(
        hub=SimpleNamespace(port=8000, plugs={}, seen={}), port=8000, entry_macs={})
    hass.data[const.DOMAIN] = None  # no server yet
    flow = make_flow(hass)
    form = await flow.async_step_user(None)
    check('first run goes to manual step', form['step_id'], 'manual')
    check_true('manual step asks for the port', 'port' in str(form['data_schema'].schema))

    result = await flow.async_step_user(
        {'mac': '68:c6:3a:81:f7:e6', 'name': '客厅', 'port': 9000})
    check('manual creates an entry', result['type'], 'create_entry')
    check('entry title', result['title'], '客厅')
    check('entry data', result['data'],
          {'mac': '68:C6:3A:81:F7:E6', 'name': '客厅', 'port': 9000})

    # --- manual with a junk MAC ------------------------------------------
    flow = make_flow(FakeHass())
    bad = await flow.async_step_user({'mac': 'not-a-mac', 'name': '', 'port': 8000})
    check('bad mac shows an error', bad.get('errors', {}).get('mac'), 'invalid_mac')

    # --- detected strip ---------------------------------------------------
    server_hub = hub.Dc1Hub.__new__(hub.Dc1Hub)
    server_hub.port = 8000
    server_hub.plugs = {}
    server_hub.seen = {'2C:3A:E8:3D:89:B4': hub.SeenStrip(
        mac='2C:3A:E8:3D:89:B4', address='192.168.31.99', device_type='PLUG_DC1_7',
        first_seen=None, last_seen=None)}
    hass = FakeHass()
    hass.data[const.DOMAIN] = SimpleNamespace(hub=server_hub, port=8000, entry_macs={})
    flow = make_flow(hass)
    form = await flow.async_step_user(None)
    check('detected strip offered', form['step_id'], 'user')
    options = list(form['data_schema'].schema.values())[0].config.options
    check('options list', [o['value'] for o in options], ['2C:3A:E8:3D:89:B4', '__manual__'])
    result = await flow.async_step_user({'pick': '2C:3A:E8:3D:89:B4'})
    check('detected pick creates entry', result['type'], 'create_entry')
    check('title falls back to mac', result['title'], '2C:3A:E8:3D:89:B4')
    check('port reused from the running server', result['data']['port'], 8000)

    # --- discovery, asking first -----------------------------------------
    hass = FakeHass()
    hass.data[const.DOMAIN] = None
    flow = make_flow(hass)
    out = await flow.async_step_discovery({'mac': '84:F3:EB:07:C2:EC', 'address': '192.168.31.60',
                                           'device_type': 'PLUG_DC1_7'})
    check('discovery asks for confirmation', out['type'], 'form')
    check('confirm step id', out['step_id'], 'discovery_confirm')
    check('placeholders carry the mac', out['description_placeholders']['mac'], '84:F3:EB:07:C2:EC')
    result = await flow.async_step_discovery_confirm({'name': '书房A'})
    check('confirmed discovery creates entry', result['type'], 'create_entry')
    check('confirmed entry data', result['data'],
          {'mac': '84:F3:EB:07:C2:EC', 'name': '书房A', 'port': 8000})

    # --- discovery with auto_add -----------------------------------------
    yaml = {
        'plugs': [], 'port': 8000, 'refresh_interval': 300, 'stale_timeout': 900,
        'query_debounce': 1.0, 'auto_add': True,
    }
    hass = FakeHass()
    hass.data[const.DATA_YAML_PLUGS] = yaml
    hass.data[const.DOMAIN] = None
    check('auto_add read from yaml', init.auto_add_enabled(hass), True)
    flow = make_flow(hass)
    result = await flow.async_step_discovery({'mac': 'AA:BB:CC:DD:EE:01'})
    check('auto_add creates without asking', result['type'], 'create_entry')
    check('auto_add title', result['title'], 'AA:BB:CC:DD:EE:01')

    # --- discovery of an already configured strip ------------------------
    existing = SimpleNamespace(entry_id='e1', data={'mac': 'AA:BB:CC:DD:EE:01', 'name': 'x', 'port': 8000},
                               options={}, unique_id='AA:BB:CC:DD:EE:01')
    hass = FakeHass(entries=[existing])
    hass.data[const.DATA_YAML_PLUGS] = dict(yaml, auto_add=False)
    flow = make_flow(hass)
    out = await flow.async_step_discovery({'mac': 'AA:BB:CC:DD:EE:01'})
    check('duplicate discovery aborted', out['type'], 'abort')
    check('abort reason', out['reason'], 'already_configured')

    # --- a MAC that only lives in YAML must say so, not "already added" ---
    yaml_only_hub = hub.Dc1Hub(
        SimpleNamespace(loop=asyncio.get_running_loop()),
        port=8000, refresh_interval=0, stale_timeout=0, query_debounce=0.0,
    )
    yaml_only_hub.set_plugs([hub.Dc1Plug('AA:BB:CC:DD:EE:09', 'Y', ['a', 'b', 'c', 'd'])])
    hass = FakeHass()
    hass.data[const.DOMAIN] = SimpleNamespace(hub=yaml_only_hub, port=8000, entry_macs={})
    hass.data[const.DATA_YAML_PLUGS] = dict(yaml, auto_add=False)
    flow = make_flow(hass)
    out = await flow.async_step_discovery({'mac': 'AA:BB:CC:DD:EE:09'})
    check('yaml-only MAC aborts', out['type'], 'abort')
    check('yaml-only MAC names YAML as the cause', out['reason'], 'configured_in_yaml')
    # the manual UI path must report the same thing
    flow = make_flow(hass)
    out = await flow.async_step_manual(
        {'mac': 'AA:BB:CC:DD:EE:09', 'name': '客厅', 'port': 8000}
    )
    check('UI add of a yaml MAC is blocked too',
          (out['type'], out.get('reason')), ('abort', 'configured_in_yaml'))
    # ... but a MAC that is not in YAML can still be added while YAML is active
    flow = make_flow(hass)
    out = await flow.async_step_discovery({'mac': 'AA:BB:CC:DD:EE:10'})
    check('non-yaml MAC still discovered', out['type'], 'form')
    check('yaml MACs excluded from the detected list',
          [m for m, _l in config_flow._detected(hass)], [])
    check('entry MACs and yaml MACs are separated',
          (config_flow._entry_macs(hass), sorted(config_flow._yaml_macs(hass))),
          (set(), ['AA:BB:CC:DD:EE:09']))

    # --- the hub discovery hook fires a flow ------------------------------
    hass = FakeHass()
    cb = init._make_discovery_callback(hass)
    cb(hub.SeenStrip(mac='11:22:33:44:55:66', address=None, device_type=None,
                     first_seen=None, last_seen=None))
    await asyncio.sleep(0)
    check('discovery flow started', len(hass.config_entries.flows_started), 1)
    started = hass.config_entries.flows_started[0]
    check('flow domain', started['domain'], const.DOMAIN)
    check('flow source', started['context']['source'], 'discovery')
    check('flow payload', started['data']['mac'], '11:22:33:44:55:66')

    # --- options flow ------------------------------------------------------
    entry = SimpleNamespace(entry_id='e9', unique_id='68:C6:3A:81:F7:E6',
                            data={'mac': '68:C6:3A:81:F7:E6', 'name': 'old', 'port': 8000},
                            options={'auto_add': False})
    hass = FakeHass(entries=[entry])
    options = config_flow.Dc1OptionsFlow(entry)
    options.hass = hass
    form = await options.async_step_init(None)
    check('options step id', form['step_id'], 'init')
    result = await options.async_step_init({'name': '书房', 'auto_add': True})
    check('options saves', result['type'], 'create_entry')
    check('name written to data', entry.data['name'], '书房')
    check('auto_add written to options', entry.options['auto_add'], True)


asyncio.run(flow_scenarios())

section('8. 元数据与文案一致性')
manifest = json.load(open(os.path.join(PKG, 'manifest.json'), encoding='utf-8'))
for key in ('domain', 'name', 'version', 'documentation', 'issue_tracker',
            'iot_class', 'integration_type', 'config_flow', 'codeowners'):
    check_true(f'manifest has {key}', key in manifest)
check('manifest domain', manifest['domain'], 'phicomm_dc1')
check('manifest config_flow', manifest['config_flow'], True)
check('manifest iot_class', manifest['iot_class'], 'local_push')

strings = json.load(open(os.path.join(PKG, 'strings.json'), encoding='utf-8'))


def key_tree(node, prefix=''):
    out = set()
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(prefix + k)
            out |= key_tree(v, prefix + k + '.')
    return out


base_tree = key_tree(strings)
for fname in ('en.json', 'zh.json', 'zh-Hans.json'):
    data = json.load(open(os.path.join(PKG, 'translations', fname), encoding='utf-8'))
    check(f'{fname} matches strings.json', key_tree(data) - base_tree, set())
    check(f'{fname} has no missing keys', base_tree - key_tree(data), set())

for key in ('config.step.user', 'config.step.manual', 'config.step.discovery_confirm',
            'config.abort.already_configured', 'config.abort.configured_in_yaml',
            'config.error.invalid_mac',
            'config.error.port_conflict', 'options.step.init',
            'entity.switch.master', 'entity.switch.socket_3',
            'entity.sensor.voltage', 'entity.sensor.power'):
    node = strings
    for part in key.split('.'):
        node = node.get(part, {})
    check_true(f'strings has {key}', bool(node))

hacs = json.load(open(os.path.join(ROOT, 'hacs.json'), encoding='utf-8'))
check('hacs content path', hacs['content'], ['custom_components/phicomm_dc1'])
check_true('hacs render_readme', hacs.get('render_readme'))

section('9. README 内部链接')


def github_slug(heading: str) -> str:
    """Approximate github-slugger: lowercase, drop punctuation, spaces -> '-'."""
    text = heading.lstrip('#').strip().lower()
    text = re.sub(r'[^\w\s-]', '', text, flags=re.UNICODE)
    return re.sub(r'\s', '-', text.strip())


readme_path = os.path.join(ROOT, 'README.md')
readme = open(readme_path, encoding='utf-8').read()
anchors = {github_slug(h) for h in re.findall(r'^#{1,6}\s+.*$', readme, re.M)}
internal = re.findall(r'\[([^\]]+)\]\((#[^)]+)\)', readme)
broken = [link for _text, link in internal if link[1:] not in anchors]
check_true('README has headings', len(anchors) > 10)
check('README internal anchors all resolve', broken, [])

# every documented step must be listed in the table of contents
steps = [h for h in re.findall(r'^##\s+(第\s*\d+\s*步.*|原理：.*)$', readme, re.M)]
toc_targets = {link[1:] for _t, link in internal}
missing_from_toc = [github_slug(s) for s in steps if github_slug(s) not in toc_targets]
check('all steps linked from the TOC', missing_from_toc, [])
check_true('TOC covers the numbered steps', len(steps) >= 4)

section('结果')
print(f'{CHECKS} checks run')
if FAILURES:
    print(f'{len(FAILURES)} FAILURE(S):')
    for item in FAILURES:
        print('  -', item)
    sys.exit(1)
print('ALL CHECKS PASSED')
