import os
import sys

# Agregar ruta al path
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_dir)

from backend.excel_parser import ExcelIPAMReader
from backend.format_generator import generate_format_text

def test_excel_parsing():
    excel_path = os.path.join(base_dir, "data", "ejemplo_inventario_ips.xlsx")
    assert os.path.exists(excel_path), f"Excel no encontrado: {excel_path}"
    
    reader = ExcelIPAMReader(excel_path)
    sheets = reader.get_sheet_names()
    print("Hojas encontradas:", sheets)
    assert "10.20.38.0" in sheets, "Hoja 10.20.38.0 debe estar presente"
    
    blocks = reader.parse_sheet("10.20.38.0")
    print(f"Total de subredes detectadas en 10.20.38.0: {len(blocks)}")
    assert len(blocks) >= 8, f"Se esperaban al menos 8 subredes, se obtuvieron {len(blocks)}"
    
    # Validar primer bloque (0 a 31)
    b0 = blocks[0]
    print(f"Bloque 0: Red={b0.network_ip}, GW={b0.gateway_ip}, VLAN={b0.vlan}, CIDR={b0.cidr}")
    assert b0.network_ip == "10.20.38.0/27", f"Red incorrecta: {b0.network_ip}"
    assert b0.gateway_ip == "10.20.38.1", f"Gateway incorrecto: {b0.gateway_ip}"
    assert b0.vlan == "3740", f"VLAN incorrecta: {b0.vlan}"
    assert len(b0.assigned_ips) == 4, f"Se esperaban 4 IPs ocupadas, hay {len(b0.assigned_ips)}"
    assert b0.available_ips[0]["ip"] == "10.20.38.6", f"Primera libre esperada 10.20.38.6, se obtuvo {b0.available_ips[0]['ip']}"
    
    # Validar bloque /28 apilado (192 a 207)
    b_stacked = [b for b in blocks if b.network_octet == 192][0]
    print(f"Bloque 192..207: Red={b_stacked.network_ip}, Tamaño={b_stacked.size}, CIDR=/{b_stacked.cidr}")
    assert b_stacked.size == 16, f"Tamaño esperado 16, se obtuvo {b_stacked.size}"
    assert b_stacked.cidr == 28, f"CIDR esperado 28, se obtuvo {b_stacked.cidr}"
    
    print("[OK] Todas las validaciones de lectura de Excel pasaron exitosamente.")

def test_format_generation():
    test_data = {
        "cliente": "NESTLE GUATEMALA SA",
        "direccion": "48 CALLE 15-74 ZONA 12 GUATEMALA CITY",
        "coordenadas": "14.566537730922489, -90.552684568",
        "disenador": "EDGAR CHUVAC",
        "tel_disenador": "58261994",
        "fecha": "19-05-2025",
        "titulo": "INTERNET CORPORATIVO",
        "contacto_tec": "KERVIN RODRIGUEZ TEL 39925496",
        "ejecutivo": "VICKY HERRARTE TEL 58261258",
        "consultor": "LUIS FERNANDO MARROQUIN / TEL: 5826-4126",
        "medio": "FIBRA",
        "factibilidad": "FACTIBLE BRINDAR SERVICIO POR MEDIO DE FIBRA DESDE CENTRAL EL CARMEN, USAR RUTA Y CENTRAL DIFENERENTE DEL ID 99900465T",
        "equipo_cpe": "CISCO C921",
        "velocidad": "300 MBPS",
        "ips_count": "1",
        "observaciones": "ALTA DE IC",
        "items_aceptados": [
            "INTERNET CORPORATIVO LOCAL 300 MBS  (ACEPTADO)",
            "ARRENDAMIENTO EQUIPO  (ACEPTADO)",
            "MONITOREO ENLACE  (ACEPTADO)"
        ],
        "equipos_claro": [
            {"rol": "PE", "marca": "HUAWEI", "modelo": "NE40E", "hostname": "GNCYGTECN1D1A12B02EIM3", "ip_admon": "10.179.28.10", "int_out": ""},
            {"rol": "PE", "marca": "HUAWEI", "modelo": "NE40E", "hostname": "GNCYGTECN1D1A11B02EIM2", "ip_admon": "10.179.28.9", "int_out": ""},
            {"rol": "EL CARMEN", "marca": "", "modelo": "ATN980C", "hostname": "GNCYGTECN1D1C06A331BM1", "ip_admon": "10.78.10.102", "int_out": "Eth-Trunk12 (GE0/6/0, GE0/6/1)"},
            {"rol": "TRÁFICO", "marca": "EL-CARMEN-CTC", "modelo": "FRM220A-07", "hostname": "GNCYGTECN1D1C05A28AHA6", "ip_admon": "10.78.250.234", "int_out": "S15|P2"}
        ],
        "equipo_raisecom": "RAISECOM RAX711-L",
        "vrf_gestor": "GESTOR_RAISECOM",
        "vlan_gestor": "836",
        "red_gestor": "10.40.3.0/24",
        "gw_gestor": "10.40.3.1",
        "ip_gestor_raisecom": "10.40.3.120",
        "red_wan": "10.78.89.32/27",
        "gw_wan": "10.78.89.33",
        "ip_wan": "10.78.89.35",
        "loopback": "10.212.239.51/32",
        "lan": "186.151.52.220/30",
        "lan_obs": "TAREA DE LIMPIEZA T1654673",
        "isla": "CARMEN",
        "vlan_num": "3740",
        "desc_vlan": "INTERNET_GT_METRO",
        "vrf_name": "INTERNET_GT_METRO",
        "vrf_desc": "INTERNET_PEs_METROPOLITANO_ISLA_APP",
        "rd": "6458:11270",
        "id_servicio": "99900466T",
        "loopback_id": "5",
        "psk": "dgQ3IvfatixK9m"
    }
    
    text = generate_format_text(test_data)
    print("\n--- INICIO FORMATO GENERADO ---")
    print(text[:400] + "\n...")
    print("--- FIN VISTA PREVIA ---")
    
    assert "***********************ALTA DE INTERNET CORPORATIVO**********************" in text
    assert "99900466T" in text
    assert "10.78.89.32/27 RED" in text
    assert "10.78.89.35    WAN" in text
    assert "ip vpn-instance INTERNET_GT_METRO" in text
    assert "PRE-SHARED KEY: dgQ3IvfatixK9m" in text
    print("[OK] Todas las validaciones de generacion de formato pasaron exitosamente.")

if __name__ == "__main__":
    print("Ejecutando pruebas de verificacion...")
    test_excel_parsing()
    test_format_generation()
    print("\n[EXITO] TODAS LAS PRUEBAS COMPLETADAS CON EXITO!")
