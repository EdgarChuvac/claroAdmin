"""Parser del Excel de ejemplo y generador del formato de alta."""

import os

from conftest import SAMPLE_XLSX

from backend.services.excel_parser import ExcelIPAMReader
from backend.services.format_generator import generate_format_text


def test_excel_parsing():
    excel_path = str(SAMPLE_XLSX)
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
    assert "LOOPBACK: 10.212.239.51/32" in text
    assert "ISLA: CARMEN" in text
    assert "VLAN: 3740" in text
    assert "ip vpn-instance INTERNET_GT_METRO" in text
    assert " route-distinguisher 6458:11270" in text
    assert "LOOPBACK 5 :  10.212.239.51" in text
    assert "PSK-DEMO-NO-VALIDA" not in text
    print("[OK] Todas las validaciones de generacion de formato pasaron exitosamente.")


def test_pasted_factibility_block_is_printed_as_is():
    bloque = "TITULO:\t***INTERNET CORPORATIVO***\nMEDIO:\tFIBRA\nDIRECCION:\tZONA 1\\1"
    text = generate_format_text({"titulo": "INTERNET", "medio": "RADIO", "factibilidad_bloque": bloque})
    assert f"{bloque}\n" in text
    assert "==> RADIO ==>" not in text  # sin equipos Claro no hay tramo de medio


if __name__ == "__main__":
    print("Ejecutando pruebas de verificacion...")
    test_excel_parsing()
    test_format_generation()
    print("\n[EXITO] TODAS LAS PRUEBAS COMPLETADAS CON EXITO!")


import pytest  # noqa: E402

from backend.services.excel_parser import normalize_sheet_name, split_service_label  # noqa: E402


@pytest.mark.parametrize(("nombre", "esperado"), [
    ("10.78.163.0", "10.78.163.0"),
    ("TIVOLI - 10.78.163.0", "10.78.163.0"),
    ("10.78.151.0 - TIVOLI NUEVO PE", "10.78.151.0"),
    ("10.18.57.X", "10.18.57.0"),
    ("10.18.53.x", "10.18.53.0"),
    (" 10.20.38.0 ", "10.20.38.0"),
    ("10.20.38.128", None),
    ("Hoja1", None),
    ("10.1.1.0 y 10.1.2.0", None),
    ("999.1.1.0", None),
])
def test_nombres_de_hoja_de_los_excel_reales(nombre, esperado):
    assert normalize_sheet_name(nombre) == esperado


@pytest.mark.parametrize(("etiqueta", "esperado"), [
    ("1282900001T HILOS Y ALGODON, S.A..", ("1282900001T", "HILOS Y ALGODON, S.A..")),
    ("1317800048T  PRODUCTOS ALIMENTICIOS", ("1317800048T", "PRODUCTOS ALIMENTICIOS")),
    ("86100290", ("86100290", "")),
    ("HSRP", ("HSRP", "")),
    ("MINISTERIO PUBLICO", ("MINISTERIO PUBLICO", "")),
    ("HSRP fis 1", ("HSRP fis 1", "")),
])
def test_separa_id_y_cliente_solo_si_parece_id(etiqueta, esperado):
    assert split_service_label(etiqueta) == esperado


@pytest.mark.parametrize(("vlan_raw", "vlan"), [
    ("INTERNET_GT_METRO VLAN 3740  /26", "3740"),
    ("COMITÉ PROCIEGOS VLAN 1728 VRF PROCIEGOS", "1728"),
    ("VLAN-976", "976"),
    ("1010", "1010"),
    ("UFINET-TIVOLI", ""),
])
def test_vlan_de_la_fila_de_red(vlan_raw, vlan):
    from backend.services.excel_parser import IPBlock

    assert IPBlock("10.0.0.0", 0, 7, 1, 1, 9, vlan_raw).vlan == vlan


@pytest.mark.parametrize("etiqueta", ["GW", "GATEWAY", "Geteway", "gwy", "GWY", "IP GW"])
def test_variantes_de_gateway(etiqueta):
    from backend.services.excel_parser import GATEWAY_LABEL_RE

    assert GATEWAY_LABEL_RE.search(etiqueta.upper())
