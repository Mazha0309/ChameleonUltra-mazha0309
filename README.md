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

基于官方 main 分支（v2.2.0）的修改版固件，**GPL-3.0 许可证，与官方保持一致**。
版本号格式：`v2.2.0-mazha0309-XXX`（XXX 为构建序号）。

### 功能列表

| 功能 | 说明 |
|---|---|
| **16 卡槽** | 槽位数 8 → 16；老设备固件升级单次启动自动迁移（槽配置 v8→v9），原 1~8 槽数据保留 |
| **LED 混色高半区** | 8 颗物理 LED 显示 16 槽（`slot % 8`）；1~8 槽标准色（红=双频/绿=IC/蓝=ID），9~16 槽混色（黄/青/品红） |
| **场触发自动轮询** | 无读头时静止；读头场出现按配置间隔自动在启用槽间切换；读头离开自动恢复原槽位；跳过空槽 |
| **轮询间隔可配置** | 100~5000ms，修改立即生效（无需重启）；设置持久化（settings v8） |
| **按键：轮询开关** | 按键动作新增"轮询开关"，按一下开/关自动轮询 |
| **按键：进DFU** | 按键动作新增"进DFU"，保存数据后重启进 bootloader，插电脑直接刷机 |
| **A+B 长按软重启** | 同时按住 A+B 超过 1 秒，松开触发软重启；可通过协议命令关闭（默认开） |
| **协议修复** | `GET_SLOT_INFO`/`GET_ENABLED_SLOTS` 返回全部 16 槽（官方硬编码 8 槽导致 9~16 槽数据缺失） |
| **动画优化** | 保持官方扫灯动画语义；切槽动画全程使用目标槽颜色，不闪旧色 |

### 新增协议命令

| 命令 | ID | 说明 |
|---|---|---|
| `GET/SET_POLLING_ENABLE` | 1041/1042 | 查询/设置轮询开关（1 字节 0/1） |
| `GET/SET_POLLING_INTERVAL` | 1043/1044 | 查询/设置轮询间隔（uint16 大端，100~5000ms） |
| `GET/SET_AB_REBOOT_ENABLE` | 1045/1046 | 查询/设置 A+B 软重启开关 |

### 编译

```bash
cd firmware
docker run --rm -v "$(pwd)/..:/workdir:rw" -e CURRENT_DEVICE_TYPE=ultra \
  ghcr.io/rfidresearchgroup/chameleonultra-fw-builder:main bash ./firmware/build.sh
# 产物：firmware/objects/ultra-dfu-app.zip（仅 application 的 DFU 包）
```

版本号由 git 标签生成，打新构建号：

```bash
git tag -f v2.2.0-mazha0309-XXX HEAD
```

无 Docker 时也可手动装 ARM 工具链（GNU ARM 12.2.rel1）+ nrfutil + mergehex 后直接 `./build.sh`。

### 刷机

- **手机刷**：MTools / ChameleonUltraGUI → 固件管理 → 刷入本地 DFU 包
- **电脑刷**：`./firmware/flash-dfu-app.sh`（需 nrfutil + pyserial，设备 USB 连接）
  - 脚本自动进 DFU（`enter_dfu.py`），失败则按 B 键插入
- **恢复**：随时刷官方 v2.2.0 的 `ultra-dfu-app.zip` 还原

### 配套工具（tools/cu-ble-sim/）

Python 脚本，通过 USB 串口（VID 6868:8686）直接控制设备，无需 APP：

```bash
python set_active_slot.py <slot>        # 切到指定槽（0~15），高半区灯混色
python polling_ctl.py on                # 开启轮询
python polling_ctl.py off               # 关闭轮询
python polling_ctl.py interval <ms>     # 设置间隔（100~5000）
python polling_ctl.py status            # 查询状态
```

依赖：`pip install pyserial`；Linux 需 udev 规则或 dialout 组权限。

### 测试建议

1. 刷机后按键循环 16 槽：1~8 常亮标准色、9~16 混色
2. 写入 2 张卡到不同槽，开轮询，贴读卡器观察自动切槽、离开恢复
3. A+B 长按 1 秒松开验证软重启
4. 设备设置中关掉轮询开关后，贴读卡器应完全静止
