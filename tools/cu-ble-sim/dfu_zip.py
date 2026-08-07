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
