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
    assert frame[0] == 0x11  # SOF
    assert frame[1] == 0xEF  # LRC1 = lrc(sof)
    assert frame[2:4] == b"\x03\xe8"  # cmd 1000 BE
    assert frame[4:6] == b"\x00\x68"  # status 0x68
    assert frame[6:8] == b"\x00\x06"  # len 6
    assert frame[8] == lrc(frame[:8])  # LRC2 covers first 8 bytes
    assert frame[-1] == lrc(b"v2.0.0")
    assert len(frame) == 16  # 10 + len


def test_parse_frame_roundtrip():
    frame = encode_frame(CMD_GET_APP_VERSION, STATUS_SUCCESS, b"v2.0.0")
    parsed = parse_frame(frame)
    assert parsed == {
        "cmd": CMD_GET_APP_VERSION,
        "status": STATUS_SUCCESS,
        "data": b"v2.0.0",
    }


def test_parse_frame_incomplete_returns_none():
    frame = encode_frame(CMD_ENTER_BOOTLOADER, STATUS_SUCCESS)
    assert parse_frame(frame[:9]) is None  # 只收到头部
    assert parse_frame(frame) == {
        "cmd": CMD_ENTER_BOOTLOADER,
        "status": STATUS_SUCCESS,
        "data": b"",
    }


def test_parse_frame_bad_lrc_raises():
    frame = bytearray(encode_frame(CMD_GET_APP_VERSION, STATUS_NOT_IMPLEMENTED))
    frame[-1] ^= 0xFF
    with pytest.raises(ValueError):
        parse_frame(bytes(frame))


def test_empty_data_frame():
    frame = encode_frame(CMD_ENTER_BOOTLOADER, STATUS_SUCCESS)
    assert len(frame) == 10
    assert frame[-1] == 0x00


def test_parse_frame_with_trailing_bytes():
    """buffer 中一帧完整 + 下一帧前缀时，必须解析出第一帧。"""
    frame_a = encode_frame(CMD_GET_APP_VERSION, STATUS_SUCCESS, b"v2.0.0")
    frame_b = encode_frame(CMD_ENTER_BOOTLOADER, STATUS_SUCCESS)  # 10 字节
    assert parse_frame(frame_a + frame_b[:5]) == {
        "cmd": CMD_GET_APP_VERSION,
        "status": STATUS_SUCCESS,
        "data": b"v2.0.0",
    }


def test_parse_frame_bad_sof_raises():
    frame = bytearray(encode_frame(CMD_ENTER_BOOTLOADER, STATUS_SUCCESS))
    frame[0] ^= 0xFF
    with pytest.raises(ValueError):
        parse_frame(bytes(frame))
