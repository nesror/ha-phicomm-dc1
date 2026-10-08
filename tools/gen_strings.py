"""Generate strings.json + translations/{en,zh,zh-Hans}.json for the integration."""
import json
import os

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'custom_components', 'phicomm_dc1')
TDIR = os.path.join(BASE, 'translations')
os.makedirs(TDIR, exist_ok=True)

EN = {
    "config": {
        "step": {
            "user": {
                "title": "Pick a power strip",
                "description": "{count} Phicomm DC1 strip(s) have already dialled in to this "
                               "host. Pick the one you want to add.",
                "data": {"pick": "Power strip"},
            },
            "manual": {
                "title": "Power strip details",
                "description": "The MAC is printed on the label, for example "
                               "68:C6:3A:81:F7:E6. Power-cycle the strip first: it has to dial "
                               "in before it can be added.",
                "data": {
                    "mac": "MAC address",
                    "name": "Name (optional)",
                    "port": "Listen port",
                },
            },
            "discovery_confirm": {
                "title": "Phicomm DC1 strip found",
                "description": "MAC: {mac}\nSource address: {address}\nModel: {device_type}",
                "data": {"name": "Name (optional)"},
            },
        },
        "abort": {
            "already_configured": "This power strip is already configured.",
            "configured_in_yaml": (
                "This MAC is declared in your YAML configuration (the plugs list under "
                "`phicomm_dc1:`). YAML and the UI cannot manage the same strip at the "
                "same time: remove it from YAML and restart Home Assistant before "
                "adding it here. Existing entity ids are kept when you do, because both "
                "modes share the same unique ids."
            ),
            "invalid_mac": "The packet did not carry a usable MAC address.",
        },
        "error": {
            "invalid_mac": "Not a valid MAC address. Expected 12 hex digits, e.g. 68:C6:3A:81:F7:E6.",
            "port_conflict": "This host is already listening on port {running_port}; "
                             "only one service can own that port.",
        },
    },
    "options": {
        "step": {
            "init": {
                "title": "Phicomm DC1 options",
                "description": "Strip: {mac}",
                "data": {
                    "name": "Name",
                    "auto_add": "Add newly discovered strips automatically",
                },
            }
        }
    },
    "entity": {
        "switch": {
            "master": {"name": "Master switch"},
            "socket_1": {"name": "Socket 1"},
            "socket_2": {"name": "Socket 2"},
            "socket_3": {"name": "Socket 3"},
        },
        "sensor": {
            "voltage": {"name": "Voltage"},
            "power": {"name": "Power"},
        },
    },
}

ZH = {
    "config": {
        "step": {
            "user": {
                "title": "选择插排",
                "description": "已经有 {count} 个斐讯 DC1 插排连到了本机，选择要添加的那个。",
                "data": {"pick": "插排"},
            },
            "manual": {
                "title": "插排信息",
                "description": "MAC 就是插座背面标签上的地址，例如 68:C6:3A:81:F7:E6。"
                               "插座需要先断电重插，才会主动连到 Home Assistant。",
                "data": {"mac": "MAC 地址", "name": "名称（可选）", "port": "监听端口"},
            },
            "discovery_confirm": {
                "title": "发现斐讯 DC1 插排",
                "description": "MAC：{mac}\n来源地址：{address}\n型号：{device_type}",
                "data": {"name": "名称（可选）"},
            },
        },
        "abort": {
            "already_configured": "这个插排已经添加过了。",
            "configured_in_yaml": (
                "这个 MAC 已经在 YAML 配置里声明了（phicomm_dc1: 下的 plugs 列表）。"
                "YAML 和 UI 不能同时管理同一台插排：请先把它从 YAML 里去掉并重启 "
                "Home Assistant，再回来添加。因为两种模式共用同一套 unique_id，"
                "去掉 YAML 后重新添加会保留原有的 entity_id。"
            ),
            "invalid_mac": "报文里没有可用的 MAC 地址。",
        },
        "error": {
            "invalid_mac": "MAC 地址格式不对，应为 12 位十六进制，例如 68:C6:3A:81:F7:E6。",
            "port_conflict": "本机已经在 {running_port} 端口上监听了，一个端口只能有一个服务。",
        },
    },
    "options": {
        "step": {
            "init": {
                "title": "Phicomm DC1 设置",
                "description": "插排：{mac}",
                "data": {"name": "名称", "auto_add": "自动添加新发现的插排"},
            }
        }
    },
    "entity": {
        "switch": {
            "master": {"name": "总开关"},
            "socket_1": {"name": "开关一"},
            "socket_2": {"name": "开关二"},
            "socket_3": {"name": "开关三"},
        },
        "sensor": {
            "voltage": {"name": "电压"},
            "power": {"name": "功率"},
        },
    },
}


def dump(path, payload):
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print('wrote', path)


dump(os.path.join(BASE, 'strings.json'), EN)
dump(os.path.join(TDIR, 'en.json'), EN)
dump(os.path.join(TDIR, 'zh.json'), ZH)
dump(os.path.join(TDIR, 'zh-Hans.json'), ZH)
