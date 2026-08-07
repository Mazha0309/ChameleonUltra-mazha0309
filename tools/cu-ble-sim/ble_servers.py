"""BLE glue layer: phase 1 (normal mode) BLE server.

Thin layer over bluez-peripheral 0.1.7; all protocol logic lives in cu_frame /
dfu_protocol. This 0.1.7 build is the pre-Peripheral spacecheese API: there is
no Peripheral class and no AdvertisementData. The building blocks are:

- Service / characteristic / CharacteristicFlags (bluez_peripheral.gatt.*)
- Advertisement (bluez_peripheral.advert) for advertising
- get_message_bus() / Adapter (bluez_peripheral.util)

Phase 1 advertises the Chameleon Ultra service (6e400001), answers protocol
commands with fake values, and hands over to phase 2 (DFU mode, later task)
through the on_enter_dfu callback when ENTER_BOOTLOADER is received.
"""

import asyncio
import logging

from bluez_peripheral.advert import Advertisement
from bluez_peripheral.gatt.characteristic import (
    CharacteristicFlags,
    characteristic,
)
from bluez_peripheral.gatt.service import Service
from bluez_peripheral.util import get_message_bus, is_bluez_available

from cu_frame import (
    CMD_ENTER_BOOTLOADER,
    CMD_GET_APP_VERSION,
    CMD_GET_DEVICE_ADDRESS,
    CMD_GET_DEVICE_CHIP_ID,
    STATUS_NOT_IMPLEMENTED,
    STATUS_SUCCESS,
    TOTAL_OVERHEAD,
    encode_frame,
    parse_frame,
)

log = logging.getLogger("cu-ble-sim")

ULTRA_SERV_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
ULTRA_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
ULTRA_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
DFU_SERV_UUID = "0000fe59-0000-1000-8000-00805f9b34fb"
DFU_CTRL_UUID = "8ec90001-f315-4f60-9fb8-838830daea50"
DFU_PACKT_UUID = "8ec90002-f315-4f60-9fb8-838830daea50"

# Pairing: the commercial app does not require pairing, so no Agent is
# registered. bluez-peripheral 0.1.7 ships NoIoAgent/BaseAgent, but registering
# as the default agent requires superuser, which we avoid; the phase-1
# characteristics carry no ENCRYPT/SECURE flags, so writes work unpaired.


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


class NormalServer:
    """Phase 1: advertise the Chameleon Ultra service and answer commands."""

    def __init__(self, name: str, fake_version: str, on_enter_dfu):
        self.name = name
        self.fake_version = fake_version
        self.on_enter_dfu = on_enter_dfu
        self._bus = None
        self._service = None
        self._tx_char = None
        self._assembler = FrameAssembler()
        self._chip_id = bytes([0x12, 0x34, 0x56, 0x78])
        self._address = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x02])

    async def start(self):
        """Register the GATT service and start advertising.

        No Peripheral class in bluez-peripheral 0.1.7: export a Service on the
        system bus and register an Advertisement (device name goes through its
        localName parameter).
        """
        if self._bus is not None:
            raise RuntimeError("server already started")
        bus = await get_message_bus()
        if not await is_bluez_available(bus):
            await bus.disconnect()
            raise RuntimeError("BlueZ is not available on the system bus")

        service = Service(ULTRA_SERV_UUID)
        rx = characteristic(
            ULTRA_RX_UUID,
            CharacteristicFlags.WRITE | CharacteristicFlags.WRITE_WITHOUT_RESPONSE,
        )
        rx.setter(self._on_write)
        tx = characteristic(ULTRA_TX_UUID, CharacteristicFlags.NOTIFY)
        service.add_characteristic(rx)
        service.add_characteristic(tx)
        await service.register(bus)

        advert = Advertisement(
            localName=self.name,
            serviceUUIDs=[ULTRA_SERV_UUID],
            appearance=0,
            timeout=0,
        )
        await advert.register(bus)

        self._bus = bus
        self._service = service
        self._tx_char = tx
        log.info("advertising %r with service %s", self.name, ULTRA_SERV_UUID)

    async def stop(self):
        """Unregister the service and drop the bus.

        bluez-peripheral 0.1.7 has no Advertisement.unregister(); bluez
        releases the advert when the exporting app disconnects the bus.
        """
        if self._service is not None:
            await self._service.unregister()
            self._service = None
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None
        self._tx_char = None
        log.info("phase 1 server stopped")

    def _on_write(self, _service, data, _options):
        """Write handler; must stay synchronous.

        bluez-peripheral 0.1.7 calls setter_func from its non-async
        WriteValue dbus method and discards the return value, so an async
        handler would never run. Frame handling and notifying are sync; only
        on_enter_dfu may be async and is scheduled on the running loop.

        Each BLE write may hold 0..N complete frames (or half a frame), so all
        writes share one FrameAssembler.
        """
        for frame in self._assembler.feed(bytes(data)):
            self._handle_frame(frame)

    def _handle_frame(self, frame):
        cmd, payload = frame["cmd"], frame["data"]
        log.info("RX cmd=%d payload=%s", cmd, payload.hex())
        if cmd == CMD_GET_APP_VERSION:
            self._send(CMD_GET_APP_VERSION, STATUS_SUCCESS, self.fake_version.encode())
        elif cmd == CMD_GET_DEVICE_CHIP_ID:
            self._send(CMD_GET_DEVICE_CHIP_ID, STATUS_SUCCESS, self._chip_id)
        elif cmd == CMD_GET_DEVICE_ADDRESS:
            self._send(CMD_GET_DEVICE_ADDRESS, STATUS_SUCCESS, self._address)
        elif cmd == CMD_ENTER_BOOTLOADER:
            self._send(CMD_ENTER_BOOTLOADER, STATUS_SUCCESS)
            log.info("ENTER_BOOTLOADER received, switching to DFU mode")
            self._schedule(self.on_enter_dfu)
        else:
            self._send(cmd, STATUS_NOT_IMPLEMENTED)

    def _send(self, cmd, status, data=b""):
        if self._tx_char is None:
            return
        # 0.1.7 notifies via Characteristic.changed() (emit_properties_changed);
        # it silently drops the value if the client is not subscribed.
        self._tx_char.changed(bytes(encode_frame(cmd, status, data)))

    def _schedule(self, fn):
        """Call fn now; if it returns a coroutine, run it on the event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        result = fn()
        if asyncio.iscoroutine(result):
            if loop is None:
                result.close()
                log.error("no running loop; discarding on_enter_dfu result")
            else:
                loop.create_task(result)
