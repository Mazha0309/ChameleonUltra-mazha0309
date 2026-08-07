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
    assert resp == bytes([OP_RESPONSE, OP_GET_MTU, RES_SUCCESS]) + (247).to_bytes(
        2, "little"
    )


def test_unsupported_op():
    t = DfuTarget()
    resp = t.handle_ctrl(bytes([0x63]))
    assert resp == bytes([OP_RESPONSE, 0x63, RES_NOT_SUPPORTED])


def test_full_session():
    t = DfuTarget()
    init_packet = b"\x00" * 128
    firmware = b"IMAGE" * 1000  # 5000 bytes

    # --- init packet object ---
    assert t.handle_ctrl(
        bytes([OP_OBJECT_CREATE, 0x00]) + len(init_packet).to_bytes(4, "little")
    ) == (
        bytes([OP_RESPONSE, OP_OBJECT_CREATE, RES_SUCCESS])
        + (0).to_bytes(4, "little")
        + len(init_packet).to_bytes(4, "little")
    )
    for off in range(0, len(init_packet), 100):
        chunk = init_packet[off : off + 100]
        assert t.handle_packet(chunk) is None
    assert t.handle_ctrl(
        bytes([OP_WRITE])
        + zlib.crc32(init_packet).to_bytes(4, "little")
        + len(init_packet).to_bytes(4, "little")
    ) == (
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
    assert t.handle_ctrl(
        bytes([OP_OBJECT_CREATE, 0x01]) + len(firmware).to_bytes(4, "little")
    ) == (
        bytes([OP_RESPONSE, OP_OBJECT_CREATE, RES_SUCCESS])
        + (0).to_bytes(4, "little")
        + len(firmware).to_bytes(4, "little")
    )
    for off in range(0, len(firmware), 244):
        chunk = firmware[off : off + 244]
        assert t.handle_packet(chunk) is None
    assert t.handle_ctrl(
        bytes([OP_WRITE])
        + zlib.crc32(firmware).to_bytes(4, "little")
        + len(firmware).to_bytes(4, "little")
    ) == (
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
    resp = t.handle_ctrl(
        bytes([OP_WRITE])
        + (0xDEADBEEF).to_bytes(4, "little")
        + (10).to_bytes(4, "little")
    )
    assert resp[2] == RES_CRC_ERROR


def test_select_empty():
    t = DfuTarget()
    resp = t.handle_ctrl(bytes([OP_SELECT, 0x01]))
    assert resp == bytes([OP_RESPONSE, OP_SELECT, RES_SUCCESS]) + (0).to_bytes(
        4, "little"
    ) + (0).to_bytes(4, "little")


def test_prn_receipt():
    t = DfuTarget()
    t.handle_ctrl(bytes([OP_SET_PRN]) + (2).to_bytes(2, "little"))
    t.handle_ctrl(bytes([OP_OBJECT_CREATE, 0x01]) + (100).to_bytes(4, "little"))
    assert t.handle_packet(b"A" * 10) is None
    receipt = t.handle_packet(b"B" * 10)
    assert (
        receipt[0] == OP_RESPONSE
        and receipt[1] == OP_WRITE
        and receipt[2] == RES_SUCCESS
    )
    assert int.from_bytes(receipt[3:7], "little") == 20
    assert int.from_bytes(receipt[7:11], "little") == zlib.crc32(b"A" * 10 + b"B" * 10)
