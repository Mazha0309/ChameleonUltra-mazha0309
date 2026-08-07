# Chameleon Ultra BLE 模拟器（固件捕获脚本）设计

日期：2026-08-07
目标：在不刷入真机的前提下，通过模拟 Chameleon Ultra 的 BLE 协议，捕获商业轮询 APP
（"CU自动轮询-大龙"）通过蓝牙推送的固件镜像，用于后续分析其实现思路。
运行环境：Linux PC + 蓝牙适配器 + Python 3 + BlueZ

## 背景与动机

商业轮询固件只通过配套 APP 推送，不直接提供固件文件。用户不想把商业固件刷进真机
（防砖、防设备 ID 绑定消耗试用次数），因此需要脚本模拟一台"虚拟变色龙"，让 APP
把固件推给脚本保存。不涉及破解激活码/授权，捕获后用于学习其轮询与卡槽实现思路。

## 协议基础（均来自开源资料）

### 正常模式（Chameleon Ultra 服务）

- 服务：`6e400001-b5a3-f393-e0a9-e50e24dcca9e`（Nordic UART 风格）
  - RX 特征 `6e400002-...`：APP → 设备（write / write-without-response）
  - TX 特征 `6e400003-...`：设备 → APP（notify）
- 帧格式（UltraFrame）：
  `SOF(1) + SOF_LRC(1) + CMD(2BE) + STATUS(2BE) + LEN(2BE) + HEAD_LRC(1) + DATA(LEN) + DATA_LRC(1)`
- 校验：LRC = (0x100 - sum(bytes)) & 0xFF
- 关键命令（data_cmd.h）：
  - `GET_APP_VERSION` = 1000
  - `ENTER_BOOTLOADER` = 1010（进入 DFU 模式）
  - `GET_DEVICE_CHIP_ID` = 1011
  - `GET_DEVICE_ADDRESS` = 1012

### DFU 模式（Nordic Secure DFU v2）

- 服务：`0000fe59-0000-1000-8000-00805f9b34fb`
  - ctrl 特征：`8ec90001-f315-4f60-9fb8-838830daea50`
  - packt 特征：`8ec90002-f315-4f60-9fb8-838830daea50`
- 协议：Object-based Secure DFU v2
  - opcode：1=OBJECT_CREATE, 2=PRN 设置, 3=OBJECT_WRITE(CRC), 4=OBJECT_EXECUTE,
    6=OBJECT_SELECT, 7=GET_MTU, 0x60=RESPONSE
  - object 0 = init packet，object 1 = 固件镜像
  - 响应包：`0x60 + opcode + result + offset/size/crc`

## 架构

### 阶段 1 · 正常模式

- 广播设备名 `ChameleonUltra` + 服务 `6e400001`
- 解析全部入站 UltraFrame，日志记录
- 应答策略（让 APP 认为连接的是真机且需要更新）：
  - `GET_APP_VERSION(1000)` → 返回伪造旧版本（默认 2.0.0，可 `--version` 指定）
  - `GET_DEVICE_CHIP_ID(1011)` / `GET_DEVICE_ADDRESS(1012)` → 返回伪 ID，
    同时把 APP 发送的真实查询打印到日志（供分析它是否按 ID 白名单校验）
  - `ENTER_BOOTLOADER(1010)` → 应答成功后切换阶段 2
  - 其余命令 → 应答 STATUS_NOT_IMPLEMENTED 并记录
- 版本号格式需与官方一致（GIT_VERSION 字符串如 `v2.2.0`）

### 阶段 2 · DFU 模式

- 停止阶段 1 广播，重新广播 DFU 服务 `fe59`（模拟真机重启进 DFU）
- 实现 Secure DFU v2 服务端：
  - 处理 OBJECT_CREATE（记录 object 类型、大小、偏移）
  - 处理 packt 数据写入（按 MTU 分片接收，追加到缓冲区）
  - 处理 OBJECT_WRITE(CRC)（返回 CRC32 校验响应）
  - 处理 PRN：若 APP 设置回执间隔 N，每收 N 包回一次回执
  - 处理 OBJECT_EXECUTE：object 0 → 保存 init_packet.bin；object 1 → 保存 firmware_app.bin
  - 处理 GET_MTU：返回协商后的 MTU
- 容错：CRC 不匹配时按协议返回错误码并重新请求对应对象（DFU 允许重传）

### 输出

- `output/init_packet.bin`：DFU init packet（含固件版本、SD 要求、哈希等）
- `output/firmware_app.bin`：固件镜像主体
- `output/frames.log`：全量 BLE 帧日志（时间戳 + HEX + 解析）
- `output/ultra-dfu-app.zip`：重组 DFU 包（init packet + 镜像 + 自动生成的 manifest.json），
  与官方发布格式一致，后续可用 nrfutil 刷入真机

### CLI 参数

```
--dfu-only           仅阶段 2，直接广播 DFU 服务（兜底）
--version STR        伪造版本号（默认 v2.0.0）
--name STR           广播设备名（默认 ChameleonUltra）
--output DIR         输出目录（默认 ./output）
--mtu N              最大 MTU（默认 247）
--prn N              PRN 回执间隔（默认 0=跟随 APP 设置）
```

## 技术选型

- BlueZ D-Bus 外设模拟：`bleak-peripheral`（pip 包，封装 BlueZ GATT 外设接口）
- 中央端测试：`bleak`（回环验证用）
- 无需 root（BlueZ 需 `bluetoothd --experimental` 或 Main.conf 开 experimental 特性）

## 测试

1. 单元级：UltraFrame 编解码 + LRC 校验（已知帧向量）
2. 回环：脚本自身以 central 角色连接模拟器，跑完整 DFU 流程（init + 镜像 + CRC + PRN），
   校验收到的字节与发送端一致
3. 真机验证（用户执行）：手机 APP 连接脚本假设备 → 走刷机流程 → 检查输出文件

## 风险与对策

- BlueZ 实验特性未开 → 文档写明启动参数
- APP 阶段 1 有额外校验（如芯片 ID 白名单）→ `--dfu-only` 兜底，或日志分析后伪造
- DFU 加密/签名（概率低）→ 捕获密文存档，另行分析
- MTU 协商差异 → 动态处理（默认 247，可参数调）

## 不做的事

- 不破解激活码/授权验证
- 不修改或刷写用户真机
- 不实现自适应轮询（后续固件项目再做）
