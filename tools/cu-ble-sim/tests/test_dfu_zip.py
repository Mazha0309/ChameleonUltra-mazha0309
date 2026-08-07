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
