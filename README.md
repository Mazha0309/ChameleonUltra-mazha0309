![logo](docs/images/ultra-logo.png)

![ultra picture](docs/images/ultra-overview.png)

# ChameleonUltra Authorized Distributors

Lyon, France: [Lab401](https://lab401.com/)

Santa Ana, United States: [Hackerwarehouse](https://hackerwarehouse.com/)

Hastings, UK: [KSEC](https://labs.ksec.co.uk/product/proxgrind-chameleon-ultra/)

Montreal, Canada: [TechSecurityTools](https://techsecuritytools.com/product/chameleon-ultra/)

Shenzhen, China: [Sneaktechnology](https://sneaktechnology.com)

Guangdong, China: [MTools Tec](https://shop.mtoolstec.com/)

Lazada One, Singapore: [Aliexpress by RRG](https://proxgrind.aliexpress.com/store/1101312023)

# What is it and how to use ?

Read the [available documentation](https://github.com/RfidResearchGroup/ChameleonUltra/wiki).

# Compatible applications

* [ChameleonUltraGUI](https://github.com/GameTec-live/ChameleonUltraGUI)
* [MTools BLE](https://github.com/RfidResearchGroup/ChameleonUltra/wiki/mtoolsble)
* [Mifare Chameleon Tool (iOS only, Beta)](https://apps.apple.com/it/app/mifare-chameleon-tool/id6761231484)
* [Chameleon Ultra (Sailfish OS only)](https://sailfishos-chum.github.io/apps/harbour-chameleon-ultra)

# Videos

*Beware some of the instructions might have changed since recording, check the current documentation when in doubt!*

* [Downloading and compiling the official CLI](https://www.youtube.com/watch?v=VGpAeitNXH0)
* [Downloading ChameleonUltraGUI](https://www.youtube.com/watch?v=rHH7iqbX3nY)
* [ChameleonUltraGUI features overview](https://www.youtube.com/watch?v=YqE8wyVSse4)
* [Using ChameleonUltraGUI and the Chameleon Ultra](https://www.youtube.com/watch?v=9jtKNJ5-kVY)
* [MTools BLE - How to clone a card with ChameleonUltra](https://youtu.be/IvH-xtdW1Wk?si=4exqgAAeJ-kxU3aN)

# Official channels

Where do you find the community?
* [RFID Hacking community discord server](https://t.ly/d4_C)
  * Software/chameleon-dev for firmware and clients development discussions
  * Devices/chameleon-ultra for usage discussions
* [GameTec_live discord server](https://discord.gg/DJ2A4wxncK)

###### Searching for the docs repo? Find it [here](https://github.com/RfidResearchGroup/ChameleonUltraDocs)

---

## Mazha0309 修改版（16 卡槽 + 轮询固件）

基于官方 main 分支（v2.2.0）的修改版固件，**GPL-3.0 许可证，与官方保持一致**。版本号格式：`v2.2.0-mazha0309-XXX`（XXX 为构建序号）。

### 功能修改

- **16 卡槽**：槽位数 8 → 16（`TAG_MAX_SLOT_NUM`），老设备单次启动自动迁移（v8→v9），原 1~8 槽数据保留
- **8 颗 LED 显示 16 槽**：槽位 → 灯位 `slot % 8`；1~8 槽显示标准色（红=双频/绿=IC/蓝=ID），**9~16 槽用混色**（黄/青/品红）区分，不闪烁
- **场触发自动轮询**：无读头时静止不动；读头场出现按配置间隔自动在启用槽间切换；读头离开自动恢复原槽位
  - 间隔 100~5000ms，修改立即生效（协议命令 `GET/SET_POLLING_ENABLE(1041/1042)`、`GET/SET_POLLING_INTERVAL(1043/1044)`）
  - 配置持久化（settings v8）
- **按键动作新增**：
  - `轮询开关`（SettingsButtonTogglePolling = 6）：按一下开关自动轮询
  - `进DFU`（SettingsButtonEnterDfuMode = 7）：保存数据后重启进 bootloader，方便插电脑刷机
  - **A+B 同时长按 1 秒软重启**（松开触发，可经命令 `GET/SET_AB_REBOOT_ENABLE(1045/1046)` 关闭，默认开）
- **协议修复**：`GET_SLOT_INFO`/`GET_ENABLED_SLOTS` 返回全部 16 槽（官方 8 槽硬编码）
- **动画**：保持官方扫灯动画语义（含 `end=11` 边缘标记）；切槽动画使用目标槽显示色，避免旧槽颜色闪烁

### 编译

```bash
cd firmware
docker run --rm -v "$(pwd)/..:/workdir:rw" -e CURRENT_DEVICE_TYPE=ultra \
  ghcr.io/rfidresearchgroup/chameleonultra-fw-builder:main bash ./firmware/build.sh
# 产物：firmware/objects/ultra-dfu-app.zip（仅 application 的 DFU 包）
```

版本号由 git 标签生成，打新构建号：`git tag -f v2.2.0-mazha0309-XXX HEAD`

### 刷机

- 手机：MTools / ChameleonUltraGUI 本地 DFU 包刷入
- 电脑：`./firmware/flash-dfu-app.sh`（需 nrfutil）
- 恢复：随时可刷官方 v2.2.0 的 `ultra-dfu-app.zip`

### 配套工具（tools/cu-ble-sim/）

Python 脚本，通过 USB 串口直接控制设备：

- `set_active_slot.py <slot>` — 切到指定槽（0~15）
- `polling_ctl.py on|off|interval <ms>|status` — 轮询控制
