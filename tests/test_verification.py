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
        "cliente": "CLIENTE DEMO SA",
        "direccion": "DIRECCION DE DEMOSTRACION",
        "coordenadas": "",
        "disenador": "INGENIERO DEMO",
        "tel_disenador": "",
        "fecha": "19-05-2025",
        "titulo": "INTERNET CORPORATIVO",
        "contacto_tec": "CONTACTO DEMO",
        "ejecutivo": "EJECUTIVO DEMO",
        "consultor": "CONSULTOR DEMO",
        "medio": "FIBRA",
        "factibilidad": "FACTIBLE SEGUN VALIDACION TECNICA DE DEMOSTRACION",
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
            {"rol": "PE", "marca": "HUAWEI", "modelo": "NE40E", "hostname": "PE-DEMO-01", "ip_admon": "192.0.2.10", "int_out": ""},
            {"rol": "SW", "marca": "HUAWEI", "modelo": "ATN980C", "hostname": "SW-DEMO-01", "ip_admon": "192.0.2.11", "int_out": "Eth-Trunk12"},
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
        "id_servicio": "SERVICIO-DEMO-001",
        "loopback_id": "5",
        "psk": "PSK-DEMO-NO-VALIDA"
    }
    
    text = generate_format_text(test_data)
    print("\n--- INICIO FORMATO GENERADO ---")
    print(text[:400] + "\n...")
    print("--- FIN VISTA PREVIA ---")
    
    assert "***********************ALTA DE INTERNET CORPORATIVO**********************" in text
    assert "SERVICIO-DEMO-001" in text
    assert "10.78.89.32/27 RED" in text
    assert "10.78.89.35    WAN" in text
    assert "ip vpn-instance INTERNET_GT_METRO" in text
    assert "PRE-SHARED KEY: PSK-DEMO-NO-VALIDA" in text
    print("[OK] Todas las validaciones de generacion de formato pasaron exitosamente.")


def test_form_fields_override_pasted_factibility_block():
    text = generate_format_text(
        {
            "titulo": "INTERNET CORPORATIVO",
            "medio": "RADIO",
            "velocidad": "500 MBPS",
            "direccion": "DIRECCION ACTUAL",
            "coordenadas": "14.0, -90.0",
            "factibilidad_bloque": (
                "TITULO:\t***INTERNET CORPORATIVO***\n"
                "MEDIO:\tFIBRA\n"
                "VELOCIDAD:\t100 MBPS\n"
                "DIRECCION:\tDIRECCION ANTERIOR"
            ),
        }
    )

    assert "MEDIO:\tRADIO" in text
    assert "VELOCIDAD:\t500 MBPS" in text
    assert "DIRECCION:\tDIRECCION ACTUAL, // COORDENADAS: 14.0, -90.0" in text
    assert "DIRECCION ANTERIOR" not in text


def test_factibility_values_treat_backslashes_as_text():
    text = generate_format_text(
        {
            "medio": r"RADIO\1",
            "factibilidad_bloque": "MEDIO:\tFIBRA",
        }
    )

    assert "MEDIO:\t" + r"RADIO\1" in text

if __name__ == "__main__":
    print("Ejecutando pruebas de verificacion...")
    test_excel_parsing()
    test_format_generation()
    print("\n[EXITO] TODAS LAS PRUEBAS COMPLETADAS CON EXITO!")
