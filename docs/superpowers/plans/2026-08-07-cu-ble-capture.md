# CU BLE 固件捕获模拟器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Linux PC + BlueZ 模拟一台"虚拟 Chameleon Ultra"（双阶段：正常模式 + DFU 模式），让商业轮询 APP 通过蓝牙把固件推给脚本，捕获固件镜像与 init packet，不刷真机。

**Architecture:** 纯 Python 3。协议逻辑（UltraFrame 编解码、Secure DFU v2 状态机）与 BLE 胶水层分离，协议层可单测。BLE 外设用 bluez-peripheral（BlueZ D-Bus GATT 外设）。两阶段：阶段 1 广播 `6e400001` 服务应答命令（伪旧版本诱导升级，收到 `ENTER_BOOTLOADER` 切阶段 2）；阶段 2 广播 Nordic DFU 服务 `fe59`，实现 Secure DFU v2 服务端接收固件并落盘，可重组为 GUI 可刷的 DFU zip。

**Tech Stack:** Python 3.10+、bluez-peripheral（D-Bus）、bleak（回环测试中央端）、pytest、zlib（CRC32）、zipfile

**关键协议事实（已从开源资料核实，实现时不得偏离）：**
- UltraFrame：`SOF(0x11) + LRC1 + CMD(2BE) + STATUS(2BE) + LEN(2BE) + LRC2 + DATA + DATA_LRC`，总长 = LEN + 10，LRC = `(0x100 - sum) & 0xFF`；LRC1 只覆盖 SOF 字节，LRC2 覆盖前 8 字节，DATA_LRC 只覆盖数据
- 命令：GET_APP_VERSION=1000（回 GIT_VERSION 字符串如 `v2.0.0`）、ENTER_BOOTLOADER=1010、GET_DEVICE_CHIP_ID=1011、GET_DEVICE_ADDRESS=1012
- 状态码：STATUS_SUCCESS=0x68、STATUS_PAR_ERR=0x60、STATUS_NOT_IMPLEMENTED=0x69
- 正常模式服务 `6e400001-b5a3-f393-e0a9-e50e24dcca9e`：RX `6e400002-...`（write/write-without-response）、TX `6e400003-...`（notify）
- DFU 服务 `0000fe59-0000-1000-8000-00805f9b34fb`：ctrl `8ec90001-f315-4f60-9fb8-838830daea50`（write+notify）、packt `8ec90002-...`（write+write-without-response）
- Secure DFU v2 opcode：1=CREATE、2=PRN、3=WRITE、4=EXECUTE、6=SELECT、7=GET_MTU、0x60=RESPONSE
- RESPONSE 格式：`0x60 + op + result + payload`；result 1=成功、5=CRC 错误、2=非法状态、3=不支持、7=参数错误
- CREATE 响应 payload：offset(4LE) + size(4LE)；WRITE 响应：offset(4LE) + crc(4LE)；EXECUTE 响应：offset(4LE) + size(4LE)
- object 0 = init packet，object 1 = 固件镜像；CRC 为标准 CRC-32（zlib.crc32）
- PRN 回执：设了 N 后每收 N 包，ctrl 通知 `0x60 0x03 1 offset(4LE) crc(4LE)` 并重置计数

---

### Task 1: 项目脚手架 + 环境

**Files:**
- Create: `tools/cu-ble-sim/requirements.txt`
- Create: `tools/cu-ble-sim/pyproject.toml`
- Create: `tools/cu-ble-sim/tests/__init__.py`（空文件）
- Create: `tools/cu-ble-sim/README.md`（骨架，后续 Task 9 补全）

- [ ] **Step 1: 创建目录与依赖文件**

```bash
mkdir -p ~/Projects/chameleonultra-poll/tools/cu-ble-sim/tests
```

`requirements.txt`:
```
bluez-peripheral>=1.0.0
bleak>=0.22.0
pytest>=8.0
```

`pyproject.toml`:
```toml
[project]
name = "cu-ble-sim"
version = "0.1.0"
description = "Chameleon Ultra BLE firmware capture simulator"
requires-python = ">=3.10"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`README.md`（骨架，写清项目一句话用途 + 后续占位）:
```markdown
# cu-ble-sim

在 Linux PC 上模拟 Chameleon Ultra 的 BLE 设备，接收商业 APP 通过 DFU 推送的固件，
输出 init packet 与固件镜像。详见 docs/superpowers/specs/2026-08-07-cu-ble-capture-design.md

（完整使用说明见 Task 9 补全）
```

- [ ] **Step 2: 创建 venv 并安装依赖**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Expected: 安装成功无报错。（若 bluez-peripheral 在 Python 3.14 安装失败，则改用 pip 安装 `dbus-next` 并在后续任务中改用 raw D-Bus 实现，见 Task 5 兜底说明。）

- [ ] **Step 3: 验证测试框架可跑**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/pytest
```

Expected: `no tests ran`（0 个测试，exit code 5 可接受）或正常退出。

- [ ] **Step 4: Commit**

```bash
cd ~/Projects/chameleonultra-poll
git add tools/cu-ble-sim
git commit -m "chore: scaffold cu-ble-sim project"
```

---

### Task 2: UltraFrame 编解码模块

**Files:**
- Create: `tools/cu-ble-sim/cu_frame.py`
- Test: `tools/cu-ble-sim/tests/test_cu_frame.py`

- [ ] **Step 1: 写失败测试**

`tests/test_cu_frame.py`:
```python
import pytest

from cu_frame import (
    CMD_ENTER_BOOTLOADER,
    CMD_GET_APP_VERSION,
    STATUS_NOT_IMPLEMENTED,
    STATUS_SUCCESS,
    encode_frame,
    lrc,
    parse_frame,
)


def test_lrc_known_vector():
    assert lrc(bytes([0x11])) == 0xEF
    assert lrc(b"") == 0x00


def test_encode_frame_structure():
    frame = encode_frame(CMD_GET_APP_VERSION, STATUS_SUCCESS, b"v2.0.0")
    assert frame[0] == 0x11            # SOF
    assert frame[1] == 0xEF            # LRC1 = lrc(sof)
    assert frame[2:4] == b"\x03\xe8"   # cmd 1000 BE
    assert frame[4:6] == b"\x00\x68"   # status 0x68
    assert frame[6:8] == b"\x00\x06"   # len 6
    assert frame[8] == lrc(frame[:8])  # LRC2 covers first 8 bytes
    assert frame[-1] == lrc(b"v2.0.0")
    assert len(frame) == 16            # 10 + len


def test_parse_frame_roundtrip():
    frame = encode_frame(CMD_GET_APP_VERSION, STATUS_SUCCESS, b"v2.0.0")
    parsed = parse_frame(frame)
    assert parsed == {"cmd": CMD_GET_APP_VERSION, "status": STATUS_SUCCESS, "data": b"v2.0.0"}


def test_parse_frame_incomplete_returns_none():
    frame = encode_frame(CMD_ENTER_BOOTLOADER, STATUS_SUCCESS)
    assert parse_frame(frame[:9]) is None  # 只收到头部
    assert parse_frame(frame) == {"cmd": CMD_ENTER_BOOTLOADER, "status": STATUS_SUCCESS, "data": b""}


def test_parse_frame_bad_lrc_raises():
    frame = bytearray(encode_frame(CMD_GET_APP_VERSION, STATUS_NOT_IMPLEMENTED))
    frame[-1] ^= 0xFF
    with pytest.raises(ValueError):
        parse_frame(bytes(frame))


def test_empty_data_frame():
    frame = encode_frame(CMD_ENTER_BOOTLOADER, STATUS_SUCCESS)
    assert len(frame) == 10
    assert frame[-1] == 0x00
```

- [ ] **Step 2: 运行确认失败**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/pytest tests/test_cu_frame.py -v
```

Expected: `ModuleNotFoundError: No module named 'cu_frame'`

- [ ] **Step 3: 实现**

`cu_frame.py`:
```python
"""Chameleon Ultra serial frame (UltraFrame) encode/decode.

Layout (all big-endian except noted):
    [0]    SOF     = 0x11
    [1]    LRC1    = lrc of [0]
    [2:4]  CMD     u16
    [4:6]  STATUS  u16
    [6:8]  LEN     u16
    [8]    LRC2    = lrc of [0:8]
    [9:9+LEN]  DATA
    [-1]   DATA_LRC = lrc of DATA
Total length = LEN + 10.
"""

SOF = 0x11
TOTAL_OVERHEAD = 10

STATUS_SUCCESS = 0x68
STATUS_PAR_ERR = 0x60
STATUS_NOT_IMPLEMENTED = 0x69

CMD_GET_APP_VERSION = 1000
CMD_CHANGE_DEVICE_MODE = 1001
CMD_GET_DEVICE_MODE = 1002
CMD_SET_ACTIVE_SLOT = 1003
CMD_SET_SLOT_TAG_TYPE = 1004
CMD_SET_SLOT_DATA_DEFAULT = 1005
CMD_SET_SLOT_ENABLE = 1006
CMD_SET_SLOT_TAG_NICK = 1007
CMD_GET_SLOT_TAG_NICK = 1008
CMD_SLOT_DATA_CONFIG_SAVE = 1009
CMD_ENTER_BOOTLOADER = 1010
CMD_GET_DEVICE_CHIP_ID = 1011
CMD_GET_DEVICE_ADDRESS = 1012
CMD_SAVE_SETTINGS = 1013
CMD_RESET_SETTINGS = 1014


def lrc(data: bytes) -> int:
    """Two's-complement checksum: (0x100 - sum) & 0xFF."""
    return (0x100 - sum(data)) & 0xFF


def encode_frame(cmd: int, status: int, data: bytes = b"") -> bytes:
    if len(data) > 0xFFFF:
        raise ValueError("data too long")
    pre = (
        bytes([SOF, lrc(bytes([SOF]))])
        + cmd.to_bytes(2, "big")
        + status.to_bytes(2, "big")
        + len(data).to_bytes(2, "big")
    )
    pre += bytes([lrc(pre)])
    return pre + data + bytes([lrc(data)])


def parse_frame(buf: bytes):
    """Parse one frame. Returns dict or None if incomplete. Raises ValueError on corrupt frame."""
    if len(buf) < TOTAL_OVERHEAD:
        return None
    if buf[0] != SOF:
        raise ValueError("bad sof")
    if buf[1] != lrc(bytes([SOF])):
        raise ValueError("bad sof lrc")
    data_len = int.from_bytes(buf[6:8], "big")
    if len(buf) < TOTAL_OVERHEAD + data_len:
        return None
    if buf[8] != lrc(buf[:8]):
        raise ValueError("bad head lrc")
    if buf[-1] != lrc(buf[9:-1]):
        raise ValueError("bad data lrc")
    return {
        "cmd": int.from_bytes(buf[2:4], "big"),
        "status": int.from_bytes(buf[4:6], "big"),
        "data": buf[9:-1],
    }
```

- [ ] **Step 4: 运行确认通过**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/pytest tests/test_cu_frame.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/chameleonultra-poll
git add tools/cu-ble-sim
git commit -m "feat: add UltraFrame codec with LRC checksum"
```

---

### Task 3: Secure DFU v2 服务端状态机

**Files:**
- Create: `tools/cu-ble-sim/dfu_protocol.py`
- Test: `tools/cu-ble-sim/tests/test_dfu_protocol.py`

- [ ] **Step 1: 写失败测试**

`tests/test_dfu_protocol.py`:
```python
import zlib

import pytest

from dfu_protocol import (
    DfuTarget,
    OP_EXECUTE,
    OP_GET_MTU,
    OP_OBJECT_CREATE,
    OP_RESPONSE,
    OP_SELECT,
    OP_SET_PRN,
    OP_WRITE,
    RES_CRC_ERROR,
    RES_NOT_SUPPORTED,
    RES_SUCCESS,
)


def test_get_mtu():
    t = DfuTarget(mtu=247)
    resp = t.handle_ctrl(bytes([OP_GET_MTU]))
    assert resp == bytes([OP_RESPONSE, OP_GET_MTU, RES_SUCCESS]) + (247).to_bytes(2, "little")


def test_unsupported_op():
    t = DfuTarget()
    resp = t.handle_ctrl(bytes([0x63]))
    assert resp == bytes([OP_RESPONSE, 0x63, RES_NOT_SUPPORTED])


def test_full_session():
    t = DfuTarget()
    init_packet = b"\x00" * 128
    firmware = b"IMAGE" * 1000  # 5000 bytes

    # --- init packet object ---
    assert t.handle_ctrl(bytes([OP_OBJECT_CREATE, 0x00]) + len(init_packet).to_bytes(4, "little")) == (
        bytes([OP_RESPONSE, OP_OBJECT_CREATE, RES_SUCCESS])
        + (0).to_bytes(4, "little")
        + len(init_packet).to_bytes(4, "little")
    )
    for off in range(0, len(init_packet), 100):
        chunk = init_packet[off : off + 100]
        assert t.handle_packet(chunk) is None
    assert t.handle_ctrl(bytes([OP_WRITE]) + zlib.crc32(init_packet).to_bytes(4, "little") + len(init_packet).to_bytes(4, "little")) == (
        bytes([OP_RESPONSE, OP_WRITE, RES_SUCCESS])
        + len(init_packet).to_bytes(4, "little")
        + zlib.crc32(init_packet).to_bytes(4, "little")
    )
    assert t.handle_ctrl(bytes([OP_EXECUTE])) == (
        bytes([OP_RESPONSE, OP_EXECUTE, RES_SUCCESS])
        + len(init_packet).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
    )
    assert t.init_packet == init_packet

    # --- firmware object ---
    assert t.handle_ctrl(bytes([OP_OBJECT_CREATE, 0x01]) + len(firmware).to_bytes(4, "little")) == (
        bytes([OP_RESPONSE, OP_OBJECT_CREATE, RES_SUCCESS])
        + (0).to_bytes(4, "little")
        + len(firmware).to_bytes(4, "little")
    )
    for off in range(0, len(firmware), 244):
        chunk = firmware[off : off + 244]
        assert t.handle_packet(chunk) is None
    assert t.handle_ctrl(bytes([OP_WRITE]) + zlib.crc32(firmware).to_bytes(4, "little") + len(firmware).to_bytes(4, "little")) == (
        bytes([OP_RESPONSE, OP_WRITE, RES_SUCCESS])
        + len(firmware).to_bytes(4, "little")
        + zlib.crc32(firmware).to_bytes(4, "little")
    )
    assert t.handle_ctrl(bytes([OP_EXECUTE])) == (
        bytes([OP_RESPONSE, OP_EXECUTE, RES_SUCCESS])
        + len(firmware).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
    )
    assert t.firmware_image == firmware
    assert t.executed is True


def test_crc_mismatch():
    t = DfuTarget()
    t.handle_ctrl(bytes([OP_OBJECT_CREATE, 0x01]) + (10).to_bytes(4, "little"))
    t.handle_packet(b"0123456789")
    resp = t.handle_ctrl(bytes([OP_WRITE]) + (0xDEADBEEF).to_bytes(4, "little") + (10).to_bytes(4, "little"))
    assert resp[2] == RES_CRC_ERROR


def test_select_empty():
    t = DfuTarget()
    resp = t.handle_ctrl(bytes([OP_SELECT, 0x01]))
    assert resp == bytes([OP_RESPONSE, OP_SELECT, RES_SUCCESS]) + (0).to_bytes(4, "little") + (0).to_bytes(4, "little")


def test_prn_receipt():
    t = DfuTarget()
    t.handle_ctrl(bytes([OP_SET_PRN]) + (2).to_bytes(2, "little"))
    t.handle_ctrl(bytes([OP_OBJECT_CREATE, 0x01]) + (100).to_bytes(4, "little"))
    assert t.handle_packet(b"A" * 10) is None
    receipt = t.handle_packet(b"B" * 10)
    assert receipt[0] == OP_RESPONSE and receipt[1] == OP_WRITE and receipt[2] == RES_SUCCESS
    assert int.from_bytes(receipt[3:7], "little") == 20
    assert int.from_bytes(receipt[7:11], "little") == zlib.crc32(b"A" * 10 + b"B" * 10)
```

- [ ] **Step 2: 运行确认失败**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/pytest tests/test_dfu_protocol.py -v
```

Expected: `ModuleNotFoundError: No module named 'dfu_protocol'`

- [ ] **Step 3: 实现**

`dfu_protocol.py`:
```python
"""Secure DFU v2 server-side protocol state machine (pure logic, no BLE).

Implements the target (device) side of Nordic Secure DFU over BLE, v2 object
protocol. Reference: nRF5 SDK dfu_transport / pc-nrf-dfu-js initiator side.
"""

import zlib

OP_OBJECT_CREATE = 0x01
OP_SET_PRN = 0x02
OP_WRITE = 0x03
OP_EXECUTE = 0x04
OP_SELECT = 0x06
OP_GET_MTU = 0x07
OP_RESPONSE = 0x60

RES_SUCCESS = 0x01
RES_INVALID_STATE = 0x02
RES_NOT_SUPPORTED = 0x03
RES_DATA_SIZE_EXCEEDS = 0x04
RES_CRC_ERROR = 0x05
RES_OPERATION_FAILED = 0x06
RES_INVALID_PARAMETER = 0x07

OBJ_INIT = 0x00
OBJ_FIRMWARE = 0x01


def _resp(op: int, result: int, payload: bytes = b"") -> bytes:
    return bytes([OP_RESPONSE, op, result]) + payload


class DfuTarget:
    """State machine for one DFU session. Feed it ctrl opcodes and packet data."""

    def __init__(self, mtu: int = 247):
        self.mtu = mtu
        self.prn = 0
        self.object_type = None
        self.object_size = 0
        self.buffer = b""
        self.packets_since_receipt = 0
        self.init_packet = None
        self.firmware_image = None
        self.executed = False

    def handle_ctrl(self, payload: bytes) -> bytes:
        if not payload:
            return _resp(0xFF, RES_INVALID_PARAMETER)
        op = payload[0]
        if op == OP_OBJECT_CREATE:
            if len(payload) != 6:
                return _resp(op, RES_INVALID_PARAMETER)
            self.object_type = payload[1]
            self.object_size = int.from_bytes(payload[2:6], "little")
            self.buffer = b""
            self.packets_since_receipt = 0
            return _resp(op, RES_SUCCESS, (0).to_bytes(4, "little") + self.object_size.to_bytes(4, "little"))
        if op == OP_SET_PRN:
            if len(payload) != 3:
                return _resp(op, RES_INVALID_PARAMETER)
            self.prn = int.from_bytes(payload[1:3], "little")
            return _resp(op, RES_SUCCESS)
        if op == OP_WRITE:
            if len(payload) != 9:
                return _resp(op, RES_INVALID_PARAMETER)
            expected_crc = int.from_bytes(payload[1:5], "little")
            expected_offset = int.from_bytes(payload[5:9], "little")
            actual_crc = zlib.crc32(self.buffer) & 0xFFFFFFFF
            if actual_crc != expected_crc or len(self.buffer) != expected_offset:
                return _resp(op, RES_CRC_ERROR, len(self.buffer).to_bytes(4, "little") + actual_crc.to_bytes(4, "little"))
            return _resp(op, RES_SUCCESS, len(self.buffer).to_bytes(4, "little") + actual_crc.to_bytes(4, "little"))
        if op == OP_EXECUTE:
            if self.object_type == OBJ_INIT:
                self.init_packet = self.buffer
                self.buffer = b""
                self.object_type = None
                return _resp(op, RES_SUCCESS, len(self.init_packet).to_bytes(4, "little") + (0).to_bytes(4, "little"))
            if self.object_type == OBJ_FIRMWARE:
                self.firmware_image = self.buffer
                self.buffer = b""
                self.object_type = None
                self.executed = True
                return _resp(op, RES_SUCCESS, len(self.firmware_image).to_bytes(4, "little") + (0).to_bytes(4, "little"))
            return _resp(op, RES_INVALID_STATE)
        if op == OP_SELECT:
            if len(payload) != 2:
                return _resp(op, RES_INVALID_PARAMETER)
            if payload[1] == self.object_type:
                return _resp(op, RES_SUCCESS, len(self.buffer).to_bytes(4, "little") + self.object_size.to_bytes(4, "little"))
            return _resp(op, RES_SUCCESS, (0).to_bytes(4, "little") + (0).to_bytes(4, "little"))
        if op == OP_GET_MTU:
            return _resp(op, RES_SUCCESS, self.mtu.to_bytes(2, "little"))
        return _resp(op, RES_NOT_SUPPORTED)

    def handle_packet(self, chunk: bytes):
        """Feed one BLE packet write. Returns a PRN receipt (bytes) or None."""
        if self.object_type is None or len(chunk) == 0:
            return None
        self.buffer += chunk
        self.packets_since_receipt += 1
        if self.prn > 0 and self.packets_since_receipt >= self.prn:
            self.packets_since_receipt = 0
            crc = zlib.crc32(self.buffer) & 0xFFFFFFFF
            return _resp(OP_WRITE, RES_SUCCESS, len(self.buffer).to_bytes(4, "little") + crc.to_bytes(4, "little"))
        return None
```

- [ ] **Step 4: 运行确认通过**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/pytest tests/test_dfu_protocol.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/chameleonultra-poll
git add tools/cu-ble-sim
git commit -m "feat: add Secure DFU v2 target state machine"
```

---

### Task 4: DFU zip 重组模块

**Files:**
- Create: `tools/cu-ble-sim/dfu_zip.py`
- Test: `tools/cu-ble-sim/tests/test_dfu_zip.py`

- [ ] **Step 1: 写失败测试**

`tests/test_dfu_zip.py`:
```python
import io
import json
import zipfile

from dfu_zip import build_dfu_zip


def test_build_dfu_zip_structure():
    init_packet = b"\x01" * 64
    firmware = b"\x02" * 4096
    out = build_dfu_zip(init_packet, firmware)
    zf = zipfile.ZipFile(io.BytesIO(out))
    names = set(zf.namelist())
    assert names == {"manifest.json", "firmware_app.bin", "firmware_app.dat"}
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest == {
        "manifest": {
            "application": {
                "bin_file": "firmware_app.bin",
                "dat_file": "firmware_app.dat",
            }
        }
    }
    assert zf.read("firmware_app.bin") == firmware
    assert zf.read("firmware_app.dat") == init_packet
```

- [ ] **Step 2: 运行确认失败**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/pytest tests/test_dfu_zip.py -v
```

Expected: `ModuleNotFoundError: No module named 'dfu_zip'`

- [ ] **Step 3: 实现**

`dfu_zip.py`:
```python
"""Reassemble a DFU package zip from captured init packet + firmware image.

Format matches the official release package consumed by ChameleonUltraGUI /
chameleon-ultra.js DfuZip (manifest.json + application bin/dat).
"""

import io
import json
import zipfile


def build_dfu_zip(init_packet: bytes, firmware: bytes) -> bytes:
    manifest = {
        "manifest": {
            "application": {
                "bin_file": "firmware_app.bin",
                "dat_file": "firmware_app.dat",
            }
        }
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("firmware_app.bin", firmware)
        zf.writestr("firmware_app.dat", init_packet)
    return buf.getvalue()
```

- [ ] **Step 4: 运行确认通过**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/pytest tests/test_dfu_zip.py -v
```

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/chameleonultra-poll
git add tools/cu-ble-sim
git commit -m "feat: add DFU zip reassembly"
```

---

### Task 5: BLE 外设胶水层（阶段 1 正常模式）

**Files:**
- Create: `tools/cu-ble-sim/ble_servers.py`

本任务先做 spike 确认 bluez-peripheral 的 API（该库 API 较新，以安装的包为准），再写阶段 1。

- [ ] **Step 1: spike 确认 bluez-peripheral API**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/python -c "import bluez_peripheral; print(bluez_peripheral.__file__)"
.venv/bin/python - <<'EOF'
import inspect
from bluez_peripheral.gatt import Service, Characteristic, CharacteristicFlags
from bluez_peripheral.peripheral import Peripheral
from bluez_peripheral.advert import AdvertisementData
from bluez_peripheral.agent import Agent
print(inspect.signature(Peripheral.__init__))
print(inspect.signature(Characteristic.__init__))
print(inspect.signature(Service.__init__))
print(inspect.signature(Peripheral.start))
print(inspect.signature(Peripheral.add_service))
print(inspect.signature(Service.add_characteristic))
print(inspect.signature(Agent))
print(CharacteristicFlags.__members__)
EOF
```

Expected: 打印出类签名，据此把下方实现里的 handler 参数与属性名改对（read/write/notify 回调、发送通知方法、start 参数）。若 `bluez_peripheral` 导入失败：按 Task 1 Step 2 兜底，用 dbus-next 实现，或在 `--help` 输出里注明依赖缺失。

- [ ] **Step 2: 写实现（以 spike 结果为准微调）**

`ble_servers.py`:
```python
"""BLE glue layer: phase 1 (normal mode) and phase 2 (DFU mode) servers.

Thin layer over bluez-peripheral; all protocol logic lives in cu_frame /
dfu_protocol. Handler signatures adapted to the installed bluez-peripheral API.
"""

import asyncio
import logging
import time

from bluez_peripheral.advert import AdvertisementData
from bluez_peripheral.agent import Agent
from bluez_peripheral.gatt import Characteristic, CharacteristicFlags, Service
from bluez_peripheral.peripheral import Peripheral

from cu_frame import (
    CMD_ENTER_BOOTLOADER,
    CMD_GET_APP_VERSION,
    CMD_GET_DEVICE_ADDRESS,
    CMD_GET_DEVICE_CHIP_ID,
    STATUS_NOT_IMPLEMENTED,
    STATUS_PAR_ERR,
    STATUS_SUCCESS,
    TOTAL_OVERHEAD,
    encode_frame,
    parse_frame,
)
from dfu_protocol import DfuTarget

log = logging.getLogger("cu-ble-sim")

ULTRA_SERV_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
ULTRA_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
ULTRA_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
DFU_SERV_UUID = "0000fe59-0000-1000-8000-00805f9b34fb"
DFU_CTRL_UUID = "8ec90001-f315-4f60-9fb8-838830daea50"
DFU_PACKT_UUID = "8ec90002-f315-4f60-9fb8-838830daea50"

MODE_NORMAL = "normal"
MODE_DFU = "dfu"


class FrameAssembler:
    """Accumulate BLE write chunks into complete UltraFrames."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, chunk: bytes):
        self._buf += chunk
        frames = []
        while True:
            try:
                parsed = parse_frame(bytes(self._buf))
            except ValueError as e:
                log.warning("corrupt frame: %s", e)
                self._buf.clear()
                break
            if parsed is None:
                break
            frames.append(parsed)
            del self._buf[: TOTAL_OVERHEAD + len(parsed["data"])]
        return frames
```

- [ ] **Step 3: 完成 ble_servers.py（接上文）**

在文件末尾追加：

```python
class NormalServer:
    """Phase 1: advertise the Chameleon Ultra service and answer commands."""

    def __init__(self, name: str, fake_version: str, on_enter_dfu):
        self.name = name
        self.fake_version = fake_version
        self.on_enter_dfu = on_enter_dfu
        self._peripheral = None
        self._tx_char = None
        self._assembler = FrameAssembler()
        self._chip_id = bytes([0x12, 0x34, 0x56, 0x78])
        self._address = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x02])

    async def start(self):
        self._peripheral = await Peripheral.create(self.name)
        service = Service(ULTRA_SERV_UUID)
        rx = Characteristic(
            ULTRA_RX_UUID,
            [CharacteristicFlags.WRITE, CharacteristicFlags.WRITE_WITHOUT_RESPONSE],
            write=self._on_write,
        )
        self._tx_char = Characteristic(
            ULTRA_TX_UUID,
            [CharacteristicFlags.NOTIFY],
        )
        await service.add_characteristic(rx)
        await service.add_characteristic(self._tx_char)
        await self._peripheral.add_service(service)
        await self._peripheral.start()
        log.info("phase 1: normal mode started (name=%s, version=%s)", self.name, self.fake_version)

    async def stop(self):
        if self._peripheral is not None:
            await self._peripheral.stop()

    async def _on_write(self, data, options):
        for frame in FrameAssembler().feed(bytes(data)):
            await self._handle_frame(frame)

    async def _handle_frame(self, frame):
        cmd, payload = frame["cmd"], frame["data"]
        log.info("RX cmd=%d payload=%s", cmd, payload.hex())
        if cmd == CMD_GET_APP_VERSION:
            await self._send(CMD_GET_APP_VERSION, STATUS_SUCCESS, self.fake_version.encode())
        elif cmd == CMD_GET_DEVICE_CHIP_ID:
            await self._send(CMD_GET_DEVICE_CHIP_ID, STATUS_SUCCESS, self._chip_id)
        elif cmd == CMD_GET_DEVICE_ADDRESS:
            await self._send(CMD_GET_DEVICE_ADDRESS, STATUS_SUCCESS, self._address)
        elif cmd == CMD_ENTER_BOOTLOADER:
            await self._send(CMD_ENTER_BOOTLOADER, STATUS_SUCCESS)
            log.info("ENTER_BOOTLOADER received, switching to DFU mode")
            await self.on_enter_dfu()
        else:
            await self._send(cmd, STATUS_NOT_IMPLEMENTED)

    async def _send(self, cmd, status, data=b""):
        if self._tx_char is None:
            return
        await self._tx_char.notify(encode_frame(cmd, status, data))
```

（注：`Peripheral.create` 若为异步类方法返回实例则照此使用；若为构造函数+`start()` 则改为 `Peripheral(...)` 再 `await peripheral.start()`，以 spike 结果为准。Agent（配对）在商业 APP 需要绑定密码时才注册，先用 Agent 空注册：`agent = Agent(); agent.register()`。）

- [ ] **Step 4: 语法与导入自检**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/python -c "import ast; ast.parse(open('ble_servers.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/chameleonultra-poll
git add tools/cu-ble-sim/ble_servers.py
git commit -m "feat: add phase-1 normal mode BLE server"
```

---

### Task 6: BLE 胶水层（阶段 2 DFU 模式）

**Files:**
- Modify: `tools/cu-ble-sim/ble_servers.py`

- [ ] **Step 1: 追加 DfuServer 类**

在 `ble_servers.py` 末尾追加：

```python
class DfuServer:
    """Phase 2: advertise the Nordic DFU service and receive the firmware."""

    def __init__(self, name: str, mtu: int = 247, on_done=None):
        self.name = name
        self.mtu = mtu
        self.on_done = on_done
        self.target = DfuTarget(mtu=mtu)
        self._peripheral = None
        self._ctrl_char = None

    async def start(self):
        self._peripheral = await Peripheral.create(self.name)
        service = Service(DFU_SERV_UUID)
        ctrl = Characteristic(
            DFU_CTRL_UUID,
            [CharacteristicFlags.WRITE, CharacteristicFlags.NOTIFY],
            write=self._on_ctrl_write,
        )
        packt = Characteristic(
            DFU_PACKT_UUID,
            [CharacteristicFlags.WRITE, CharacteristicFlags.WRITE_WITHOUT_RESPONSE],
            write=self._on_packet_write,
        )
        self._ctrl_char = ctrl
        await service.add_characteristic(ctrl)
        await service.add_characteristic(packt)
        await self._peripheral.add_service(service)
        await self._peripheral.start()
        log.info("phase 2: DFU mode started (mtu=%d)", self.mtu)

    async def stop(self):
        if self._peripheral is not None:
            await self._peripheral.stop()

    async def _on_ctrl_write(self, data, options):
        payload = bytes(data)
        log.info("DFU ctrl RX: %s", payload.hex())
        resp = self.target.handle_ctrl(payload)
        if resp:
            log.info("DFU ctrl TX: %s", resp.hex())
            await self._ctrl_char.notify(resp)
        if self.target.executed and self.target.firmware_image is not None:
            log.info("firmware received: %d bytes", len(self.target.firmware_image))
            if self.on_done is not None:
                await self.on_done(self.target)

    async def _on_packet_write(self, data, options):
        chunk = bytes(data)
        receipt = self.target.handle_packet(chunk)
        if receipt:
            log.info("DFU PRN receipt: %s", receipt.hex())
            await self._ctrl_char.notify(receipt)
```

- [ ] **Step 2: 语法自检**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/python -c "import ast; ast.parse(open('ble_servers.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
cd ~/Projects/chameleonultra-poll
git add tools/cu-ble-sim/ble_servers.py
git commit -m "feat: add phase-2 DFU BLE server"
```

---

### Task 7: CLI 入口与阶段编排

**Files:**
- Create: `tools/cu-ble-sim/cu_ble_sim.py`

- [ ] **Step 1: 写实现**

`cu_ble_sim.py`:
```python
#!/usr/bin/env python3
"""CU BLE firmware capture simulator entry point.

Usage:
    cu_ble_sim.py [--dfu-only] [--version v2.0.0] [--name ChameleonUltra]
                  [--output ./output] [--mtu 247]
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from ble_servers import DfuServer, NormalServer
from dfu_zip import build_dfu_zip

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("cu-ble-sim")


async def run(args):
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {"init": None, "image": None}

    def on_dfu_done(target):
        result["init"] = target.init_packet
        result["image"] = target.firmware_image
        (output_dir / "init_packet.bin").write_bytes(target.init_packet)
        (output_dir / "firmware_app.bin").write_bytes(target.firmware_image)
        zip_bytes = build_dfu_zip(target.init_packet, target.firmware_image)
        (output_dir / "ultra-dfu-app.zip").write_bytes(zip_bytes)
        log.info("saved init_packet.bin (%d B), firmware_app.bin (%d B), ultra-dfu-app.zip",
                 len(target.init_packet), len(target.firmware_image))

    servers = []

    async def start_dfu():
        dfu = DfuServer(name=args.name, mtu=args.mtu, on_done=on_dfu_done)
        await dfu.start()
        servers.append(dfu)

    if not args.dfu_only:
        normal = NormalServer(name=args.name, fake_version=args.version, on_enter_dfu=start_dfu)
        await normal.start()
        servers.append(normal)
        log.info("waiting for app... (phase 1 normal mode)")
    else:
        await start_dfu()
        log.info("waiting for app... (DFU mode only)")

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        for s in servers:
            await s.stop()


def main():
    parser = argparse.ArgumentParser(description="Chameleon Ultra BLE firmware capture simulator")
    parser.add_argument("--dfu-only", action="store_true", help="skip phase 1, advertise DFU service only")
    parser.add_argument("--version", default="v2.0.0", help="fake app version reported to the app")
    parser.add_argument("--name", default="ChameleonUltra", help="advertised device name")
    parser.add_argument("--output", default="./output", help="output directory")
    parser.add_argument("--mtu", type=int, default=247, help="max ATT MTU")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        log.info("interrupted, exiting")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 语法与导入自检**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/python -c "import ast; ast.parse(open('cu_ble_sim.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 3: --help 冒烟**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/python cu_ble_sim.py --help
```

Expected: 打印 argparse 帮助，无报错

- [ ] **Step 4: Commit**

```bash
cd ~/Projects/chameleonultra-poll
git add tools/cu-ble-sim/cu_ble_sim.py
git commit -m "feat: add CLI entry with two-phase orchestration"
```

---

### Task 8: 回环测试（central 端验证）

**Files:**
- Create: `tools/cu-ble-sim/loopback_test.py`

- [ ] **Step 1: 检查 BlueZ 实验特性与权限**

```bash
bluetoothctl list
cat /etc/bluetooth/main.conf 2>/dev/null | grep -i experimental
```

若 `Experimental` 未开启，用 pkexec 开启：
```bash
pkexec bash -c 'printf "\n[General]\nExperimental = true\n" >> /etc/bluetooth/main.conf'
pkexec systemctl restart bluetooth
```

Expected: `bluetoothctl list` 有 Controller；重启后无报错

- [ ] **Step 2: 写回环测试脚本**

`loopback_test.py`:
```python
#!/usr/bin/env python3
"""Central-side loopback test: connect to the simulator and run a full DFU session.

Usage: python loopback_test.py   (start cu_ble_sim.py --dfu-only in another shell)
"""

import asyncio
import random
import zlib

from bleak import BleakClient

DFU_SERV_UUID = "0000fe59-0000-1000-8000-00805f9b34fb"
DFU_CTRL_UUID = "8ec90001-f315-4f60-9fb8-838830daea50"
DFU_PACKT_UUID = "8ec90002-f315-4f60-9fb8-838830daea50"

OP_OBJECT_CREATE = 0x01
OP_SET_PRN = 0x02
OP_WRITE = 0x03
OP_EXECUTE = 0x04
OP_GET_MTU = 0x07
OP_RESPONSE = 0x60
RES_SUCCESS = 0x01


class DfuInitiator:
    def __init__(self, client: BleakClient):
        self.client = client
        self.notifications = []

    def on_notify(self, _char, data):
        self.notifications.append(bytes(data))

    async def request(self, payload: bytes, expected_op: int):
        self.notifications.clear()
        await self.client.write_gatt_char(DFU_CTRL_UUID, payload, response=True)
        for _ in range(50):
            if self.notifications:
                break
            await asyncio.sleep(0.05)
        if not self.notifications:
            raise RuntimeError("no response from target")
        resp = self.notifications[0]
        if resp[0] != OP_RESPONSE or resp[1] != expected_op or resp[2] != RES_SUCCESS:
            raise RuntimeError(f"bad response: {resp.hex()}")
        return resp[3:]

    async def transfer(self, obj_type: int, data: bytes):
        await self.request(bytes([OP_OBJECT_CREATE, obj_type]) + len(data).to_bytes(4, "little"), OP_OBJECT_CREATE)
        await self.request(bytes([OP_SET_PRN]) + (0).to_bytes(2, "little"), OP_SET_PRN)
        chunk_size = 200
        for off in range(0, len(data), chunk_size):
            await self.client.write_gatt_char(DFU_PACKT_UUID, data[off : off + chunk_size], response=False)
        await self.request(
            bytes([OP_WRITE]) + zlib.crc32(data).to_bytes(4, "little") + len(data).to_bytes(4, "little"),
            OP_WRITE,
        )
        await self.request(bytes([OP_EXECUTE]), OP_EXECUTE)


async def main():
    init_packet = random.randbytes(128)
    firmware = random.randbytes(16384)

    async with BleakClient(DFU_SERV_UUID) as client:
        print(f"connected: {client.address}")
        initiator = DfuInitiator(client)
        await client.start_notify(DFU_CTRL_UUID, initiator.on_notify)
        mtu_resp = await initiator.request(bytes([OP_GET_MTU]), OP_GET_MTU)
        print(f"mtu = {int.from_bytes(mtu_resp, 'little')}")
        await initiator.transfer(0, init_packet)
        await initiator.transfer(1, firmware)
        await asyncio.sleep(0.5)

    print("loopback transfer finished OK")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: 跑回环测试**

终端 1：
```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/python cu_ble_sim.py --dfu-only --output ./output_test
```

终端 2：
```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/python loopback_test.py
```

Expected:
- loopback 打印 `connected: ...`、`mtu = ...`、`loopback transfer finished OK`
- `output_test/firmware_app.bin` 与 loopback 生成的随机数据一致（可再跑一次并 diff）
- 若 `Peripheral` 创建失败（adapter 占用/权限），检查 BlueZ experimental 与 `bluetoothctl` 状态，必要时 `pkexec systemctl restart bluetooth`

- [ ] **Step 4: 对照验证捕获文件**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
ls -la output_test/
.venv/bin/python - <<'EOF'
import zipfile
z = zipfile.ZipFile("output_test/ultra-dfu-app.zip")
print(z.namelist())
print(len(z.read("firmware_app.bin")), "bytes image")
EOF
```

Expected: zip 含 manifest.json + firmware_app.bin + firmware_app.dat，image 长度 16384

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/chameleonultra-poll
git add tools/cu-ble-sim/loopback_test.py
git commit -m "test: add BLE loopback DFU session test"
```

---

### Task 9: README 补全 + 最终验证

**Files:**
- Modify: `tools/cu-ble-sim/README.md`

- [ ] **Step 1: 写完整 README**

```markdown
# cu-ble-sim

在 Linux PC 上模拟 Chameleon Ultra 的 BLE 设备，让商业轮询 APP 把固件通过蓝牙推给脚本，
捕获固件镜像与 init packet，全程不刷真机。

## 原理

双阶段模拟（详见 `docs/superpowers/specs/2026-08-07-cu-ble-capture-design.md`）：
1. **正常模式**：广播 `6e400001` 服务，伪装旧版本（默认 v2.0.0），APP 会提示升级；
   收到 `ENTER_BOOTLOADER(1010)` 后自动切换到 DFU 模式
2. **DFU 模式**：广播 Nordic DFU 服务 `fe59`，完整实现 Secure DFU v2 服务端，
   接收 init packet 与固件镜像

## 环境准备（一次性）

```bash
# BlueZ 需要开启实验特性（GATT 外设 / 广播 API）
pkexec bash -c 'printf "\n[General]\nExperimental = true\n" >> /etc/bluetooth/main.conf'
pkexec systemctl restart bluetooth

cd tools/cu-ble-sim
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 使用

```bash
# 完整两阶段（推荐）
.venv/bin/python cu_ble_sim.py

# 只跑 DFU 模式（APP 直连 DFU 服务的兜底模式）
.venv/bin/python cu_ble_sim.py --dfu-only

# 参数
#   --version v2.0.0   伪造固件版本（诱导 APP 提示升级）
#   --name ChameleonUltra  广播名
#   --output ./output  输出目录
#   --mtu 247          最大 ATT MTU
```

手机打开商业 APP（如"CU自动轮询-大龙"），扫描并连接脚本假设备，走一遍"刷固件"流程。

## 输出

| 文件 | 说明 |
|---|---|
| `output/init_packet.bin` | DFU init packet（版本/SD 要求/哈希等头信息） |
| `output/firmware_app.bin` | 固件镜像主体 |
| `output/ultra-dfu-app.zip` | 重组 DFU 包（manifest.json + bin + dat），可直接给 GUI 刷 |
| `output/frames.log` | （预留）全量帧日志 |

## 测试

```bash
.venv/bin/pytest                      # 协议层单测
.venv/bin/python loopback_test.py     # BLE 回环（需先跑 cu_ble_sim.py --dfu-only）
```

## 已知限制

- 轮询兼容性、DFU 加密等风险见设计文档
- BlueZ 外设 API 若在发行版上受限，改用 `--dfu-only` 或检查实验特性
```

- [ ] **Step 2: 全量单测**

```bash
cd ~/Projects/chameleonultra-poll/tools/cu-ble-sim
.venv/bin/pytest -v
```

Expected: 14 passed（6 frame + 7 dfu + 1 zip）

- [ ] **Step 3: 再跑一遍回环确认稳定性**

重复 Task 8 Step 3（模拟器 + loopback_test），确认第二次也能完整跑通。

- [ ] **Step 4: Commit**

```bash
cd ~/Projects/chameleonultra-poll
git add tools/cu-ble-sim/README.md
git commit -m "docs: complete cu-ble-sim README"
```

---

## 验收清单（对照设计文档）

- [ ] UltraFrame 编解码 + LRC 向量测试通过（Task 2）
- [ ] Secure DFU v2 全流程单测通过：CREATE/PRN/WRITE(CRC)/EXECUTE/SELECT/MTU（Task 3）
- [ ] DFU zip 重组格式与 GUI 解析器一致（Task 4）
- [ ] 阶段 1 应答 GET_APP_VERSION/CHIP_ID/ADDRESS/ENTER_BOOTLOADER，收到 1010 后切阶段 2（Task 5）
- [ ] 阶段 2 收满固件后落盘 init_packet.bin / firmware_app.bin / ultra-dfu-app.zip（Task 6、7）
- [ ] 回环测试证明 DFU 传输字节一致（Task 8）
- [ ] README 覆盖 BlueZ 实验特性开启（pkexec）、双模式用法、输出说明、风险（Task 9）
