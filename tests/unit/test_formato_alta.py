"""El alta reproduce el formato de referencia de Ingeniería (DATOS por G-PON)."""

from pathlib import Path

from backend.services.format_generator import generate_format_text

REFERENCIA = Path(__file__).parent / "data" / "alta_datos_gpon.txt"

FACTIBILIDAD = "\n".join(REFERENCIA.read_text(encoding="utf-8").splitlines()[3:14])

EQUIPOS = [
    {"no": "1", "rol": "PE ESCUINTLA", "marca": "HUAWEI", "modelo": "NE40E",
     "hostname": "EESCGTESN1T1A03B02EIM3", "ip_admon": "10.179.28.27"},
    {"no": "2", "rol": "CELDA JACARANDAS II", "marca": "HUAWEI", "modelo": "ATN980C",
     "hostname": "EESCGTJAN1D1A01A241BM1", "ip_admon": "10.103.85.179"},
    {"no": "3", "rol": "CELDA El MANANTIAL", "marca": "HUAWEI", "modelo": "ATN980C",
     "hostname": "EGUAGTEMN1D1A01A121BM2", "ip_admon": "10.103.85.178"},
    {"no": "4", "rol": "TAXISCO", "marca": "HUAWEI", "modelo": "ATN910D",
     "hostname": "OTAXGTTAN1D1A01A20ENM1", "ip_admon": "10.103.85.186"},
    {"no": "5", "rol": "PUERTO IZTAPA ID 2206", "marca": "HUAWEI", "modelo": "ATN980C",
     "hostname": "EIZTGTPZN1D1A02A081BM1", "ip_admon": "10.103.85.177", "int_out": "Eth-Trunk10 (G0/3/0, G0/3/3)"},
    {"no": "6", "rol": "GPON IZTAPA", "marca": "HUAWEI", "modelo": "MA5800-X17 M01",
     "hostname": "EIZTGTPZN1D1B01A211QA0", "ip_admon": "10.102.159.110", "int_out": "S1|P9"},
]

DATA = {
    "titulo": "DATOS", "id_servicio": "T1663079", "cliente": "INVERSIONES CENTROAMERICANA, S.A",
    "disenador": "EDGAR CHUVAC", "tel_disenador": "58261994", "fecha": "02-06-2025",
    "factibilidad_bloque": FACTIBILIDAD,
    "medio": "GPON", "equipo_cpe": "CISCO C921", "equipo_raisecom": "ONT HUAWEI HG8245W5",
    "equipos_claro": EQUIPOS,
    "vrf_gestor": "DSL_ACCESO", "vlan_gestor": "1698", "desc_gestor": "GESTION_CORP_ ONT",
    "red_gestor": "10.103.104.0/24", "gw_gestor": "10.103.104.1", "ip_gestor_raisecom": "10.103.104.91",
    "red_wan": "10.105.63.144/28", "gw_wan": "10.105.63.145", "ip_wan": "10.105.63.158",
    "isla": "ESCUINTLA", "vlan_num": "43", "desc_vlan": "PRONE",
    "vrf_name": "PRONE", "vrf_desc": "", "rd": "6458:370",
    "observaciones": "SOLICITUD DE GPON G624-25 CLIENTE ID 1186000018T INVERSIONES CENTROAMERICANA, S.A",
}


def test_reproduce_el_formato_de_referencia():
    esperado = REFERENCIA.read_text(encoding="utf-8").rstrip("\n")
    # Sin loopback para comparar sin el bloque de monitoreo; la loopback se valida aparte.
    texto = generate_format_text({**DATA, "loopback": ""})
    esperado_sin_loopback = esperado.replace("LOOPBACK: 10.212.239.173/32\n\n", "")
    assert texto == esperado_sin_loopback


def test_con_loopback_agrega_linea_y_bloque_de_monitoreo():
    texto = generate_format_text({**DATA, "loopback": "10.212.239.173"})
    assert "\n\nLOOPBACK: 10.212.239.173/32\n\nISLA: ESCUINTLA\n" in texto
    assert "==> FO ==> (CLIENTE) ONT HUAWEI HG8245W5" in texto
    assert "10.103.104.91    ONT" in texto
    assert texto.index("SOLICITUD DE GPON") < texto.index("FAVOR DE AGREGAR LOOPBACK AL MONITOREO")


def test_chasis_es_el_ultimo_salto_de_la_ruta():
    texto = generate_format_text({**DATA, "chasis_nombre": "CHASIS-01", "chasis_id_fisico": "123",
                                  "chasis_slot": "3", "chasis_puerto": "2"})
    assert "(10.102.159.110) S1|P9 --> CHASIS-01 (ID 123) S3|P2 ==> FO ==> (CLIENTE)" in texto
