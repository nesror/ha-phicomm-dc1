### 修复

- **UI 添加 YAML 已声明的 MAC 时，提示不再误导人**。以前统一报"这个插排已经添加过了"，
  但实际原因是它只在 `phicomm_dc1:` 的 YAML `plugs` 列表里 —— 于是人会去找一个并不存在的
  config entry。现在区分成两种中止原因：`already_configured`（UI 里真的加过了）和
  `configured_in_yaml`（YAML 里声明着，先去掉再添加），后者顺带说明"去掉 YAML 后重新添加
  会保留原有 entity_id"。

### 文档

- 新增 **「从 YAML 迁到 UI」** 步骤：把 packages 文件改名停用 → 重启 → 按 MAC 在 UI 添加。
  因为两种模式共用 `phicomm_dc1:<mac>:<位>` 这套 `unique_id`，HA 会认领已有的注册表条目，
  entity_id、友好名、图标、区域全部原样保留，只是补上 `config_entry_id` 和 `device_id`，
  设备卡片随之出现，仪表盘和既有自动化不用动。
- 纠正一处错误说法：YAML 模式的实体**是**进实体注册表的（所以 entity_id 稳定），
  缺的只是 `config_entry_id`，因此挂不到设备上。集成页没有卡片、看不到设备是
  HA 2026 "设备必须绑定 config entry" 的限制，不是本集成的 bug。
- 补了万一 HA 不认领条目时的处置办法（日志出现 `does not generate unique IDs` 时怎么办）。

### 内部

- `tools/selfcheck.py` 从 165 项增加到 172 项：新增 YAML-only MAC 在 discovery 和手动
  两条路径上的中止原因、`_entry_macs()` 与 `_yaml_macs()` 的分离、已探测列表不混入
  YAML 设备、README 内部锚点与目录覆盖度检查。
