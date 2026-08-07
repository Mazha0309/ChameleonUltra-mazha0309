# Chameleon Ultra 16 槽位 + 固定延迟轮询固件设计

日期：2026-08-07
目标设备：官方 8 LED 版 Chameleon Ultra（nRF52840，1MB Flash）
基础固件：RfidResearchGroup/ChameleonUltra main 分支（9f90c3f）

## 背景

第三方商业固件（"CU自动轮询-大龙"）提供了固定延迟轮询和 16 卡槽（16 IC + 16 ID）功能，
但需要付费激活且闭源。本项目基于官方 GPL 开源固件，自行实现同思路功能，不接触其闭源代码与授权逻辑。

## 目标

1. 槽位从 8 扩展到 16（每槽可同时放 1 IC + 1 ID，即 32 卡位）
2. 固定延迟轮询：定时自动在启用槽位间切换
3. 8 颗 LED 区分显示 16 个槽位
4. 轮询配置（开关、间隔）持久化到 Flash
5. 魔改开源 ChameleonUltraGUI：增加轮询面板 + 16 槽位管理
6. 交付物仅限 DFU app 更新包（不动 Bootloader/SoftDevice，可随时刷回官方）

## 设计

### 1. 固件槽位扩容（8 → 16）

- `firmware/application/src/rfid/nfctag/tag_emulation.h`：`TAG_MAX_SLOT_NUM` 8 → 16
- `tag_slot_config_t` 扩容：版本号 `TAG_SLOT_CONFIG_CURRENT_VERSION` 8 → 9，
  `TAG_SLOT_CONFIG_CURRENT_SIZE` 重新计算，STATIC_ASSERT 同步更新
- 槽配置结构体中新增的 9~16 槽位默认 `enabled=0`（迁移后自动关闭）
- 存储映射 `tag_persistence.c` 的 `get_fds_map_by_slot_sense_type_for_dump` / `_for_nick`：
  映射表 8×2 扩展为 16×2（dump 记录 + nickname 记录各 16×2）
- Flash 用量估算：M1 1K dump 每条约 1KB，32 条满配约 32KB，nRF52840 1MB Flash 充足
- 迁移逻辑：升级后原 1~8 槽数据原样保留（FDS 记录 key 不变），9~16 号槽初始化为空

### 2. 8 LED 显示 16 槽

- 槽位 → LED 位置映射：`led_index = slot % 8`
- 颜色保持官方语义：红=双频、绿=IC、蓝=ID（`get_color_by_slot`）
- 1~8 号槽：常亮；9~16 号槽：同位置、同卡类型色 + 呼吸/闪烁动画区分高低半区
- 涉及文件：`rfid_main.c`（`light_up_by_slot`、`get_color_by_slot`、`apply_slot_change`）、
  `rgb_marquee.c`（新增呼吸动画或复用 PWM 呼吸效果）
- 切槽动画 `rgb_marquee_slot_switch` 的 LED 索引同样按 `% 8` 映射

### 3. 固定延迟轮询模块

- 新增 `firmware/application/src/rfid/polling.c/.h`（或并入 rfid_main）
- 机制：
  - `app_timer` 定时器按配置间隔触发
  - 触发时复用 `tag_emulation_slot_find_next(slot_now)` 找下一个启用槽（自动跳过空槽）
  - `tag_emulation_change_slot(next, true)`：切换瞬间关闭感应（sense_disable），
    防止切换过程中被读头读到半切换状态
  - 手动按键切槽时重置/暂停定时器，避免与手动操作冲突
- 行为：轮询开启后仅遍历启用槽位；若只有 1 个启用槽则无操作
- 默认间隔建议 300~500ms（比读头轮询周期短才可能漏卡，需真机实测）

### 4. 配置持久化

- `settings.h/.c`：`settings_data_t` 增加字段：
  - `uint8_t polling_enable : 1`（bitfield）
  - `uint16_t polling_interval_ms`（100~5000，0 表示无效/默认）
- `SETTINGS_CURRENT_VERSION` 6 → 7，实现 `settings_migrate()` 迁移
- 读/写接口：`settings_get/set_polling_enable()`、`settings_get/set_polling_interval()`

### 5. 命令协议

- `data_cmd.h` 新增（1000 区段未使用 ID）：
  - `DATA_CMD_GET_POLLING_ENABLE` / `DATA_CMD_SET_POLLING_ENABLE`
  - `DATA_CMD_GET_POLLING_INTERVAL` / `DATA_CMD_SET_POLLING_INTERVAL`
- `app_cmd.c` 实现对应 handler，遵循现有 frame 协议（cmd + payload + status）
- 官方 CLI（software/chameleon-cli）可选加命令；GUI 为主控界面

### 6. GUI 魔改（ChameleonUltraGUI）

- 目标仓库：GameTec-Live/ChameleonUltraGUI（开源，需克隆评估结构，Electron/Vue 系）
- 增加：轮询开关、间隔设置（ms 输入）、参与轮询槽位勾选（可选）
- 卡槽管理页 8 → 16，9~16 号槽标注"高半区"
- 现有 slot 协议命令本身支持 0~255，GUI 侧无需协议改动

### 7. 交付与恢复

- 构建产物：`ultra-dfu-app.zip`（DFU 更新包，仅 application）+ 全量 hex（供 J-Link 可选）
- 恢复路径：`nrfutil device program --firmware <官方v2.2.0包> --traits nordicDfu` 可随时刷回
- 真机验证清单（用户执行）：刷机成功、按键 16 槽循环、LED 高低半区显示、
  轮询开关（GUI）、实测门禁轮询效果

## 不做的事

- 不破解任何商业固件授权/激活码
- 不刷 Bootloader / SoftDevice，不交付全量 hex 给用户（只供高级用户可选）
- 不做 16 LED 硬件适配（目标为 8 LED 官方版）
- 不做自适应轮询（按读头节奏同步切槽），列入后续迭代
- 不做电子围栏（纯 APP 侧功能）

## 风险

- 轮询兼容性无法保证：读头轮询周期快于切槽间隔时漏卡，需真机实测调整
- 槽配置结构版本升级：官方 GUI/CLI 旧版本可能不识别新结构（slotConfig 协议不变，
  受影响的是 slot list 显示数量），GUI 用魔改版即可
- 无真机，固件只能编译验证 + 代码审查，行为正确性依赖用户真机测试
