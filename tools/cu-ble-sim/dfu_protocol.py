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
            return _resp(
                op,
                RES_SUCCESS,
                (0).to_bytes(4, "little") + self.object_size.to_bytes(4, "little"),
            )
        if op == OP_SET_PRN:
            if len(payload) != 3:
                return _resp(op, RES_INVALID_PARAMETER)
            self.prn = int.from_bytes(payload[1:3], "little")
            return _resp(op, RES_SUCCESS)
        if op == OP_WRITE:
            if len(payload) != 9:
                return _resp(op, RES_INVALID_PARAMETER)
            if self.object_type is None:
                return _resp(op, RES_INVALID_STATE)
            expected_crc = int.from_bytes(payload[1:5], "little")
            expected_offset = int.from_bytes(payload[5:9], "little")
            actual_crc = zlib.crc32(self.buffer) & 0xFFFFFFFF
            if actual_crc != expected_crc or len(self.buffer) != expected_offset:
                return _resp(
                    op,
                    RES_CRC_ERROR,
                    len(self.buffer).to_bytes(4, "little")
                    + actual_crc.to_bytes(4, "little"),
                )
            return _resp(
                op,
                RES_SUCCESS,
                len(self.buffer).to_bytes(4, "little")
                + actual_crc.to_bytes(4, "little"),
            )
        if op == OP_EXECUTE:
            if self.object_type is None:
                return _resp(op, RES_INVALID_STATE)
            if len(self.buffer) != self.object_size:
                return _resp(op, RES_INVALID_STATE)
            if self.object_type == OBJ_INIT:
                self.init_packet = self.buffer
                self.buffer = b""
                self.object_type = None
                return _resp(
                    op,
                    RES_SUCCESS,
                    len(self.init_packet).to_bytes(4, "little")
                    + (0).to_bytes(4, "little"),
                )
            if self.object_type == OBJ_FIRMWARE:
                self.firmware_image = self.buffer
                self.buffer = b""
                self.object_type = None
                self.executed = True
                return _resp(
                    op,
                    RES_SUCCESS,
                    len(self.firmware_image).to_bytes(4, "little")
                    + (0).to_bytes(4, "little"),
                )
            return _resp(op, RES_INVALID_STATE)
        if op == OP_SELECT:
            if len(payload) != 2:
                return _resp(op, RES_INVALID_PARAMETER)
            if payload[1] == self.object_type:
                return _resp(
                    op,
                    RES_SUCCESS,
                    len(self.buffer).to_bytes(4, "little")
                    + self.object_size.to_bytes(4, "little"),
                )
            return _resp(
                op, RES_SUCCESS, (0).to_bytes(4, "little") + (0).to_bytes(4, "little")
            )
        if op == OP_GET_MTU:
            if len(payload) != 1:
                return _resp(op, RES_INVALID_PARAMETER)
            return _resp(op, RES_SUCCESS, self.mtu.to_bytes(2, "little"))
        return _resp(op, RES_NOT_SUPPORTED)

    def handle_packet(self, chunk: bytes):
        """Feed one BLE packet write. Returns a PRN receipt (bytes) or None."""
        if self.object_type is None or len(chunk) == 0:
            return None
        room = self.object_size - len(self.buffer)
        if room > 0:
            self.buffer += chunk[:room]
        self.packets_since_receipt += 1
        if self.prn > 0 and self.packets_since_receipt >= self.prn:
            self.packets_since_receipt = 0
            crc = zlib.crc32(self.buffer) & 0xFFFFFFFF
            return _resp(
                OP_WRITE,
                RES_SUCCESS,
                len(self.buffer).to_bytes(4, "little") + crc.to_bytes(4, "little"),
            )
        return None
