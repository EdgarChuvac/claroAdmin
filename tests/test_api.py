import os
import sys

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_dir)

from backend.app import get_status, get_sheets, get_blocks, generate_format, GenerateFormatRequest

def test_api_endpoints():
    # 1. Test status
    res = get_status()
    assert res["status"] == "ok"
    print("[OK] /api/status responde correctamente")

    # 2. Test sheets
    sheets_data = get_sheets()
    assert "10.20.38.0" in sheets_data["sheets"]
    print("[OK] /api/sheets responde con las hojas esperadas:", sheets_data["sheets"])

    # 3. Test blocks
    blocks_data = get_blocks(sheet="10.20.38.0")
    assert len(blocks_data["blocks"]) > 0
    b0 = blocks_data["blocks"][0]
    assert b0["network_ip"] == "10.20.38.0/27"
    assert b0["first_available"]["ip"] == "10.20.38.6"
    print(f"[OK] /api/blocks devolvio {len(blocks_data['blocks'])} subredes correctamente")

    # 4. Test format generation
    req = GenerateFormatRequest(data={
        "cliente": "NESTLE GUATEMALA SA",
        "id_servicio": "99900466T",
        "titulo": "INTERNET CORPORATIVO",
        "velocidad": "300 MBPS",
        "red_wan": "10.20.38.0/27",
        "gw_wan": "10.20.38.1",
        "ip_wan": "10.20.38.6",
        "vlan_num": "3740"
    })
    res = generate_format(req)
    text = res["formatted_text"]
    assert "99900466T" in text
    assert "10.20.38.0/27 RED" in text
    print("[OK] /api/generate-format ensamblo el texto con exito")

    print("\n[EXITO] TODAS LAS APIS FUNCIONAN AL 100%")

if __name__ == "__main__":
    test_api_endpoints()
