# Phicomm DC1 Smart Power Strip · 斐讯 DC1 智能插排 Home Assistant 集成

把斐讯 DC1（PLUG_DC1_7 等固件）智能插排**完全本地化**接入 Home Assistant：不依赖任何已经停摆的
厂商云端，不需要 Node-RED，不需要刷固件、不需要拆机焊接。

一个插排提供 **4 个开关 + 2 个传感器**（总开关 / 开关一 / 开关二 / 开关三 / 电压 / 功率），
支持 UI 添加、自动发现、设备分组、中英文界面，可通过 HACS 安装。

---

## 目录

- [原理：为什么必须先改 DNS](#原理为什么必须先改-dns)
- [第 1 步：在路由器上把域名指到 Home Assistant](#第-1步在路由器上把域名指到-home-assistant)
- [第 2 步：安装集成](#第-2步安装集成)
- [第 3 步：添加插排（UI / 自动发现）](#第-3步添加插排ui--自动发现)
- [YAML 模式（固定 entity_id）](#yaml-模式固定-entity_id)
- [生成的实体](#生成的实体)
- [故障排查](#故障排查)
- [从 Node-RED 迁移](#从-node-red-迁移)
- [协议细节](#协议细节)
- [开发与自测](#开发与自测)
- [限制与安全说明](#限制与安全说明)
- [English summary](#english-summary)

---

## 原理：为什么必须先改 DNS

DC1 这类斐讯插座**没有本地控制接口**，固件里也不会监听任何端口。它的工作方式是：

```
   ┌──────────┐   WiFi    ┌──────────┐   TCP :8000    ┌─────────────────────────┐
   │  DC1 插座 │ ────────> │  路由器   │ ─────────────> │ smartplugconnect.        │
   └──────────┘           └──────────┘                 │ phicomm.com（斐讯云端）   │
                            ▲                          └─────────────────────────┘
                            │                            该域名已随斐讯倒闭而失效
                     DNS 在这里改写
```

插座主动去连 `smartplugconnect.phicomm.com:8000`，并保持长连接、周期性心跳。
所以本集成做的事情只有一件：**在家用网络里扮演那个云端服务器**。

只要让域名解析到运行 Home Assistant 的那台机器，插座就会自己连进来，之后：

- 插座 → HA：注册包、状态回报（开关位掩码、电压、功率）
- HA → 插座：查询指令、开关指令

整个过程是 push 的，HA 不需要知道插座的 IP，插座换 IP 也无所谓——这比按 IP 轮询可靠得多。

> 也正因为如此，**8000 端口只能有一个监听者**。如果之前用 Node-RED 跑过同样的方案，必须先禁用
> 那个流程，否则本集成会报"无法监听 8000 端口"。

---

## 第 1 步：在路由器上把域名指到 Home Assistant

先确认你的 Home Assistant 主机 IP（**建议同时在路由器里给它做静态 DHCP 绑定**，否则 IP 一变就全断）：
HA 侧可在 `设置 → 系统 → 网络` 查看，或看 `ha network` 的输出。下面以 `192.168.31.203` 为例。

### dnsmasq（OpenWrt / Kwrt / 爱快旁路由 / 自建 DNS 通用）

SSH 进路由器，写入一条地址覆盖（OpenWrt 上最省事的做法）：

```sh
uci add dhcp domain
uci set dhcp.@domain[-1].name='smartplugconnect.phicomm.com'
uci set dhcp.@domain[-1].ip='192.168.31.203'
uci commit dhcp
/etc/init.d/dnsmasq restart
```

或者直接往 `/etc/dnsmasq.d/` 里丢一行（等价写法，注意结尾的斜杠表示"含所有子域"）：

```
address=/smartplugconnect.phicomm.com/192.168.31.203
```

### 其他路由器

| 平台 | 位置 |
| --- | --- |
| OpenWrt / Kwrt / ImmortalWrt | `网络 → DHCP/DNS → 常规设置 → 地址` 里加 `address=/smartplugconnect.phicomm.com/192.168.31.203` |
| 华硕 Merlin | `Services → DNS Filter / 自定义主机` 里做 A 记录劫持 |
| 群晖 / Docker 里的 AdGuard Home | `过滤器 → DNS 重写`，域名填 `smartplugconnect.phicomm.com`，IP 填 HA 地址 |
| Pi-hole | `Long run domain groups` 或 `gravity.exclusions` + `192.168.31.203 smartplugconnect.phicomm.com` 写入 `pihole.list` |
| 爱快 iKuai | 不支持自定义 DNS 记录，需要旁挂一个 dnsmasq，或把插座的网关/DNS 指向带 dnsmasq 的设备 |

### 验证是否生效

在**和插座同一网络**的电脑上执行（注意：如果你机器上挂着 Clash/代理的 fake-IP DNS，要显式指定路由器当 DNS，否则测的是代理的解析结果）：

```sh
nslookup smartplugconnect.phicomm.com 192.168.31.1
```

返回的 Address 必须是你填的 HA 主机 IP。

```
Address:  192.168.31.203      ← 正确
Address:  198.18.1.87         ← 这是代理软件的 fake-IP，说明你查的不是路由器 DNS
```

---

## 第 2 步：安装集成

### 方式 A：HACS（推荐）

1. `HACS → Integrations → ⋮ → Custom repositories`，Add，填 `https://github.com/nesror/Phicomm-DC1-Smart-Power-Strip`，
   Category 选 **Integration**。
2. 回到 HACS 的 Integrations 列表，找到 **Phicomm DC1 Smart Power Strip** → Download。
3. **重启 Home Assistant**（自定义集成必须重启才会被加载）。

### 方式 B：手动

把 `custom_components/phicomm_dc1` 整个目录复制到 HA 的 `config/custom_components/` 下，重启 Home Assistant。

---

## 第 3 步：添加插排（UI / 自动发现）

`设置 → 设备与服务 → 添加集成`，搜索 **Phicomm DC1**。

第一次添加时还没有任何插座连进来，所以会让你直接填：

- **MAC 地址**：印在插座背面标签上，形如 `68:C6:3A:81:F7:E6`（大小写、`-` 或 `:` 分隔都能识别）
- **名称**：可选，留空就用 MAC 当设备名
- **监听端口**：默认 `8000`，只有第一次添加时才问，后续插排复用同一个监听

添加完成后集成就开始监听了。这时**把插座断电 10 秒再上电**——
斐讯固件的重试策略很保守，连接被拒后往往要等很久，甚至不再重试，断电重插是最快的办法。

插座一连上来，本集成就会把它登记为"已探测"，你会看到：

- 如果开着自动添加：插排**自动出现**为一个设备，带 4 个开关 + 2 个传感器，无需任何操作；
- 如果没开：`设置 → 设备与服务` 顶部会出现一条"发现 1 个 Phicomm DC1 设备"，点 **配置** 起个名字即可；
  也可以随时点集成的 **配置** 按钮，从下拉列表里挑（列表项会附带插座来源 IP 和型号）。

**自动添加开关**：`设置 → 设备与服务 → Phicomm DC1 → ⚙ 配置`，勾选 *自动添加新发现的插排*。
打开后家里再买一个 DC1，插上电就自动进 HA，不用管路由器之外的任何事；担心陌生设备蹭进来就保持关闭。

一个主机上所有插排共用一个监听端口，所以**同一个集成实例里的端口必须一致**（端口被别的东西占了会在
日志里明确报出来）。

---

## YAML 模式（固定 entity_id）

UI 模式下实体名由"设备名 + 翻译后的通道名"生成，改设备名会改 entity_id。如果你需要**精确控制
entity_id**（比如仪表盘、历史数据、既有自动化已经绑死了老 ID），用 YAML 模式，每个通道显式命名：

```yaml
phicomm_dc1:
  port: 8000
  auto_add: true
  plugs:
    - mac: "68:C6:3A:81:F7:E6"
      name: 客厅插排
      # 数组下标 = 状态位：0=总开关 1=开关一 2=开关二 3=开关三
      switches:
        - dc1_swiitch
        - dc1_swiitch1
        - dc1_swiitch3
        - dc1_swiitch2
      voltage: dc1_dianya
      power: dc1_dianliu
    - mac: "84:F3:EB:07:C2:EC"
      name: 书房插排

switch:
  - platform: phicomm_dc1

sensor:
  - platform: phicomm_dc1
```

建议放进 `packages/` 里（需要 `homeassistant: packages: !include_dir_named packages`）。

要点：

- `switches` 必须正好 4 项，顺序就是**位序**；某一项写 `null` 表示不创建该开关。
- 想改某个孔对应的 entity_id，只改数组里那一项的字符串即可，不用碰硬件。
- 不写 `voltage` / `power` 就不创建对应传感器。
- YAML 模式下实体**不进实体注册表**（没有 config entry 可挂），因此没有设备分组；
  这是 Home Assistant 的限制（2026 起设备必须绑定 config entry）。需要设备分组就用 UI 模式。
- 两种模式可以共存，但**同一个 MAC 请只用一种方式配置**，否则会撞 unique_id。

---

## 生成的实体

UI 模式下每台插排一个设备，包含：

| 实体 | 说明 |
| --- | --- |
| `switch.<设备名>_master` | 总开关（bit0，控制整排通电） |
| `switch.<设备名>_socket_1` | 开关一（bit1） |
| `switch.<设备名>_socket_2` | 开关二（bit2） |
| `switch.<设备名>_socket_3` | 开关三（bit3） |
| `sensor.<设备名>_voltage` | 电压，V，`device_class=voltage` |
| `sensor.<设备名>_power` | 功率，W，`device_class=power` |

实体的可用性直接反映 TCP 长连接状态：**插座掉线/未连上时全部显示 `unavailable`**，
连上后自动恢复。这是判断"DNS 有没有生效、插座有没有拨号进来"最直观的信号。

---

## 故障排查

**实体全是 `unavailable`**

1. 路由器 DNS 是否生效（见上面的 `nslookup` 验证，注意代理软件的 fake-IP 干扰）。
2. 8000 端口是否被别的程序占着（Node-RED 同名流程、别的容器）。看 HA 日志有没有
   `无法监听 8000 端口`。
3. 插座是否真的重新拨号了——**断电重插**。
4. 插座和 HA 是否在同一可达网段。跨 VLAN 时插座要能路由到 HA 的 IP，且路由器上没有客户端隔离。
5. 还不行就开诊断日志，看有没有连接进来、首包长什么样：

```yaml
logger:
  default: warning
  logs:
    custom_components.phicomm_dc1: debug
```

debug 级别会打印每个连接的对端地址和首包原文。

**日志出现"发现未配置的插排 XX:XX…"** —— 说明 DNS 和端口都通了，只是还没添加它。
去集成页面点配置，或打开自动添加。

**日志出现"报文里没有可用的 MAC"** —— 你的固件变体把 MAC 放在了别的字段。把那条日志里的
`字段=` 内容贴到 issue 里，注册包（`action: activate=`）的 MAC 在 `params.mac`，
状态回报包的 MAC 在 `uuid`，这是目前已知固件的两种放法。

**开关切了没反应，但状态会自己变回去** —— 插座没连上（`unavailable` 时指令发不出去，
HA 会抛"当前未连接"）。

**端口冲突** —— 一个主机只能有一个进程监听 8000。如果确实要换端口，路由器上的 DNS 只改域名指向，
端口是插座固件写死的 8000，所以**通常只能让出 8000**，而不是让集成去用别的端口。

---

## 从 Node-RED 迁移

如果你原来跑的是常见的 "Node-RED + tcp in 8000 + ha-entity" 方案，迁移很直接：

1. 在 Node-RED 里**禁用**那个 TCP 服务端节点所在的 flow（不删也行，留着当回滚），部署。
2. 停掉 Node-RED 加载件，或至少确认 8000 已经让出。
3. 装本集成，按上面的步骤添加插排。
4. 给插座断电重插。
5. 需要保留原 entity_id 的话用 YAML 模式，把 `switches` 数组按原来的位序抄一遍。
   注意不少现成流程里"开关二/开关三"是接反的（数组第 3、4 项对调），照抄就能保持仪表盘不变。

集成下发的指令格式与 Node-RED 流程逐字节一致，所以插座侧不需要任何改动。

---

## 协议细节

一行一个 JSON，`\n` 结尾。

```jsonc
// 插座 → HA：注册（MAC 在 params.mac，uuid 是个随机数，别当 MAC 用）
{"action":"activate=","uuid":"activate=484","auth":"",
 "params":{"device_type":"PLUG_DC1_7","mac":"68:C6:3A:81:F7:E6","ssid":"iOT"}}

// 插座 → HA：状态回报（MAC 在 uuid）
{"msg":"get datapoint success","uuid":"68:C6:3A:81:F7:E6",
 "result":{"status":"0010","V":221,"P":37}}

// HA → 插座：查询
{"action":"datapoint","params":{},"uuid":"68:C6:3A:81:F7:E6","auth":""}

// HA → 插座：设置（status 是"把二进制位当十进制写"的数字）
{"action":"datapoint=","params":{"status":1010},"uuid":"68:C6:3A:81:F7:E6","auth":""}
```

两个坑：

1. **`uuid` 字段含义不唯一**。注册包里它是 `activate=<随机数>`，长度 12，不是 MAC；
   状态回报包里它才是 MAC。只按"先取 uuid"的顺序写会静默丢掉所有注册包，表现为
   "端口开着、连接能建立、但实体永远 unavailable"。
2. **`status` 是十进制字面的二进制**。`0b1010` 要发成 JSON 数字 `1010`，收到 `1010`
   要按 `int(str(v), 2)` 解析成 10。所以 `bits_to_status(8) == 1000`。

`tools/selfcheck.py` 里有针对真实抓包的字节级断言，改协议时先跑它。

---

## 开发与自测

仓库自带一个**不需要 Home Assistant** 的离线自检脚本，它会用桩模块加载集成，然后：

- 编译所有模块、校验 manifest / strings / translations 结构一致
- 用真实抓到的注册包和回报包回放协议解析（含分包、粘包、字符串里的花括号、二进制前缀、坏数据重同步）
- 逐字节比对控制帧
- 校验 YAML `CONFIG_SCHEMA` 接受/拒绝的用例
- 走一遍配置流程：首次手动添加、从已探测列表选择、MAC 非法、发现确认、自动添加、重复发现中止、选项保存
- 构造两种命名模式下的全部实体

```sh
python tools/selfcheck.py
```

改完代码在真机上验证时，可以用 `tools/` 之外的任意 TCP 客户端冒充插座：连上 8000，
发一条上面那个注册包（把 mac 换成你的），再对 `{"action":"datapoint"}` 查询回报状态，
就能在不动硬件的情况下看到实体变可用、开关可切。

---

## 限制与安全说明

- **一个主机一个监听**：8000 端口独占。
- **只支持 DC1 系列**（`PLUG_DC1*`）。DC2、S7 等型号报文不同，未测试。
- **插座必须能解析到 HA**。走公网 DNS、或插座在另一个 VLAN/SSID 且被隔离，都会失败。
- **明文、无鉴权**。这条链路上原本就没有任何认证（斐讯云端时代也是这样），所以：
  - 不要把 HA 的 8000 端口映射到公网；
  - 局域网内任何设备只要能占住 8000（或改 DNS）就能冒充云端，请保证内网可信；
  - 集成只在收到"已配置的 MAC"的包时才回话，未知 MAC 会记入"已探测"列表，
    但**默认不会自动添加**，需要你确认。
- 心跳/查询是自持的：插座一旦连上，集成大约每秒会发一次查询（沿用原 Node-RED 方案的行为，
  换来的是开关响应快）。`query_debounce`、`refresh_interval`、`stale_timeout` 这三个调参项
  目前只在 YAML 块里可配（UI 模式没有暴露它们）。
- 累计电量：DC1 硬件不提供，所以没有 `energy` 传感器。要统计电耗请用 HA 的
  Utility Meter 助手对这个功率传感器做积分。

---

## English summary

The Phicomm DC1 strip has **no local API** — it dials out to
`smartplugconnect.phicomm.com:8000` and keeps that socket open. Since the Phicomm
cloud is gone, this integration impersonates it: add a DNS override on your router
pointing that hostname at your Home Assistant host, install the integration, and the
strips connect to you instead.

Each strip exposes 4 switches (master + 3 sockets) and 2 sensors (voltage, power).
Entity availability mirrors the TCP session, so `unavailable` means "the strip has not
called home".

Setup:

1. **Router DNS**: `address=/smartplugconnect.phicomm.com/<HA_IP>` in dnsmasq
   (OpenWrt: `uci add dhcp domain` …). Verify with
   `nslookup smartplugconnect.phicomm.com <router-ip>` — beware fake-IP proxy DNS on
   your test machine.
2. **Install** via HACS (add this repo as a custom Integration repository) or copy
   `custom_components/phicomm_dc1` into your `config/` tree, then restart Home Assistant.
3. **Add the integration** (`Settings → Devices & Services → Add integration → Phicomm DC1`),
   enter the MAC from the label and the listen port (default 8000). Then **power-cycle the
   strip** — the firmware retries very conservatively. It shows up as a discovered device,
   or is added on its own if you enable *auto add*.

Two protocol gotchas worth knowing: on the registration packet the `uuid` field holds a
nonce (`activate=484`) and the real MAC is in `params.mac`; and `status` is a bitmask
written as if its binary digits were decimal, so `0b1010` goes on the wire as the number
`1010`.

A legacy YAML mode lets you pin exact entity ids per socket if you have dashboards bound
to them. Run `python tools/selfcheck.py` — it validates the whole integration offline,
including byte-exact frame checks against packets captured from real hardware, without
needing Home Assistant installed.

MIT licensed. Not affiliated with Phicomm.

---

## 许可与致谢

MIT。与斐讯官方无关。斐讯云端早已下线，本项目的协议实现来自对设备实际报文的抓取与复现。
