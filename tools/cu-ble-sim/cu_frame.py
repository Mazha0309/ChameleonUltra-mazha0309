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
