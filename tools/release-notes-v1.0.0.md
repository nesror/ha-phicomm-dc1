## 这是什么

把斐讯 DC1 智能插排**完全本地化**接入 Home Assistant。

DC1 没有本地控制接口，固件只会主动连 `smartplugconnect.phicomm.com:8000` 并保持长连接，而斐讯云端早已下线。这个集成在 Home Assistant 里扮演那个云端服务器，所以插座不需要刷固件、不需要拆机、也不再依赖 Node-RED。

唯一的前置条件是在路由器上做一条 DNS 覆盖，把 `smartplugconnect.phicomm.com` 指向你的 HA 主机 IP（README 第 1 步，含 OpenWrt / dnsmasq / AdGuard Home / Pi-hole 的具体写法）。

## 本版本功能

- 每台插排 **4 个开关 + 2 个传感器**：总开关、开关一/二/三、电压(V)、功率(W)
- **实体可用性直接反映 TCP 长连接**：`unavailable` 就等于"插座没连上来"，排障非常直观
- **UI 添加**（config flow）：填 MAC + 名称 + 监听端口
- **自动发现**：未配置的插座拨号进来后，会出现在"已探测"列表里等你确认；也可以在配置项里打开*自动添加*，之后插上电就自动进 HA
- **设备分组**：每台插排一个设备，实体挂在设备下，中英文界面
- **YAML 模式**：需要把 entity_id 钉死（迁移既有仪表盘）时按位序显式命名 4 个通道
- 开关指令与状态回报的报文格式与社区 Node-RED 方案逐字节一致，插座侧零改动

## 安装

HACS → Integrations → 右上角 ⋮ → Custom repositories → 添加本仓库（Category 选 Integration）→ 搜索 *Phicomm DC1* → Download → **重启 Home Assistant**。

或手动把 `custom_components/phicomm_dc1` 拷到 HA 的 `config/custom_components/` 下后重启。

## 已知的两个协议坑（如果你要改代码）

1. 注册包（`action: "activate="`）里的 `uuid` 字段是一个随机数（形如 `activate=484`），**不是 MAC**；MAC 在 `params.mac`。只有状态回报包的 `uuid` 才是 MAC。按"先取 uuid"的顺序解析会静默丢掉所有注册包，症状是"端口开着、TCP 能连上、但实体永远 unavailable"。
2. `status` 是把二进制位当十进制写的数字：`0b1010` 上线是 JSON 数字 `1010`，收到 `1010` 要按 `int(str(v), 2)` 解析成 10。

## 开发自测

`python tools/selfcheck.py` —— 不需要安装 Home Assistant，用桩模块加载集成，跑 165 项检查：协议字节级断言（含真实抓包回放）、分包/粘包/坏数据重同步、YAML schema 正反用例、配置流程全路径、两种命名模式的实体构造、manifest/strings/translations 一致性。

## 限制

- 8000 端口独占，一个主机只能有一个监听者（如果之前跑过 Node-RED 方案，先禁用那个 flow）
- 只覆盖 DC1 系列（`PLUG_DC1*`），DC2 / S7 报文不同、未测试
- 链路明文无鉴权，请勿把 8000 映射到公网
- DC1 硬件不提供累计电量，要统计电耗请用 HA 的 Utility Meter 对功率传感器积分

完整说明见 README。
