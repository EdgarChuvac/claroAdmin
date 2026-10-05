"""Generación del texto de alta (INTERNET y DATOS corporativos).

El formato imprime únicamente los datos que se llenaron: una línea cuyo valor
está vacío no aparece en el texto final.
"""

from typing import Any, Dict, List, Optional

from .catalog import Catalog, default_catalog

FACTIBILIDAD_SEPARATOR = "." * 64
MONITOREO_SEPARATOR = "-" * 64
SIN_FACTIBILIDAD = "SIN FACTIBILIDAD"


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _equipment_order(eq: Dict[str, Any]) -> tuple[int, int]:
    """Ordena por la numeración de la tabla (1, 2, 3...); sin número va al final."""
    try:
        return (0, int(_text(eq.get("no"))))
    except ValueError:
        return (1, 0)


def build_route_string(
    equipos: List[Dict[str, str]],
    raisecom_model: str = "RAISECOM RAX711-L",
    cpe_model: str = "CISCO C921",
    medio: str = "FO",
) -> str:
    """Ruta: ``Rol Marca Modelo Hostname (IP Admon.) --> ... ==> MEDIO ==> (CLIENTE) RAISECOM --> CPE``.

    Los equipos extremo Claro se encadenan según su numeración, empezando por el 1.
    """
    parts = []
    for eq in sorted(equipos, key=_equipment_order):
        name = " ".join(p for p in (_text(eq.get(k)) for k in ("rol", "marca", "modelo", "hostname")) if p)
        ip = _text(eq.get("ip_admon"))
        if ip:
            name = f"{name} ({ip})".strip()
        if name:
            parts.append(name)

    cliente_chain = f"(CLIENTE) {raisecom_model}"
    if cpe_model:
        cliente_chain += f" --> {cpe_model}"
    claro_chain = " --> ".join(parts)
    if not claro_chain:
        return cliente_chain
    medio = _text(medio)
    return f"{claro_chain} ==> {medio} ==> {cliente_chain}" if medio else f"{claro_chain} ==> {cliente_chain}"


def _optional(lines: List[str], label: str, value: str) -> None:
    if value:
        lines.append(f"{label}{value}")


def generate_format_text(data: Dict[str, Any], catalog: Optional[Catalog] = None) -> str:
    """Genera el formato de alta según el tipo de servicio (INTERNET o DATOS)."""
    catalog = catalog or default_catalog()
    defaults = catalog.network_defaults
    template = catalog.service(_text(data.get("titulo"), "INTERNET"))

    cliente = _text(data.get("cliente"))
    disenador = _text(data.get("disenador"))
    tel_disenador = _text(data.get("tel_disenador"))
    fecha = _text(data.get("fecha"))
    id_servicio = _text(data.get("id_servicio"))
    observaciones = _text(data.get("observaciones"))

    factibilidad_bloque = _text(data.get("factibilidad_bloque"))
    sin_factibilidad = bool(data.get("sin_factibilidad")) and not factibilidad_bloque

    # Ruta
    equipo_cpe = _text(data.get("equipo_cpe")) or defaults.equipo_cpe
    raisecom = _text(data.get("equipo_raisecom")) or defaults.equipo_raisecom
    medio_ruta = catalog.medio_ruta(_text(data.get("medio"), "FIBRA"))
    ruta = _text(data.get("ruta_manual")) or build_route_string(
        data.get("equipos_claro") or [], raisecom, equipo_cpe, medio_ruta
    )
    obs_medio = _text(data.get("obs_medio"))

    # Recursos
    red_wan = _text(data.get("red_wan"))
    gw_wan = _text(data.get("gw_wan"))
    ip_wan = _text(data.get("ip_wan"))
    ips_adicionales = [_text(ip) for ip in data.get("ips_adicionales") or [] if _text(ip)]
    ip_publica = _text(data.get("ip_publica")) if template.ip_publica else ""
    loopback = _text(data.get("loopback"))
    loopback_ip = loopback.split("/")[0]
    if loopback and "/" not in loopback:
        loopback = f"{loopback}/32"
    isla = _text(data.get("isla"))
    vlan = _text(data.get("vlan_num"))
    vrf_name = _text(data.get("vrf_name"))
    rd = _text(data.get("rd"))
    vrf_desc = _text(data.get("vrf_desc"))
    vlan_desc = _text(data.get("desc_vlan"))

    designer = " ".join(p for p in (disenador, tel_disenador) if p)
    lines = [
        f"DISEÑO REALIZADO POR {designer} | FECHA {fecha}".strip(" |"),
        f"***********************ALTA DE {template.banner}**********************",
        "Factibilidad:",
    ]
    if factibilidad_bloque:
        lines.append(factibilidad_bloque)
    elif sin_factibilidad:
        lines.append(SIN_FACTIBILIDAD)
    lines.extend([FACTIBILIDAD_SEPARATOR, "", "RUTA A CONFIGURAR", "=================", "", ruta])
    _optional(lines, "OBSERVACIONES DE MEDIO: ", obs_medio)
    _optional(lines, "OBSERVACIONES: ", observaciones)

    recursos: List[str] = []
    if red_wan or gw_wan or ip_wan or ips_adicionales:
        recursos.append("IP WAN")
        _optional(recursos, "", f"{red_wan} RED" if red_wan else "")
        _optional(recursos, "", f"{gw_wan}    GW" if gw_wan else "")
        _optional(recursos, "", f"{ip_wan}    WAN" if ip_wan else "")
        recursos.extend(f"{ip}    ADICIONAL" for ip in ips_adicionales)
        recursos.append("")
    if ip_publica:
        recursos.extend([f"IP PUBLICA {ip_publica}", ""])
    if loopback:
        recursos.extend([f"LOOPBACK {loopback}", ""])
    red_lines: List[str] = []
    _optional(red_lines, "ISLA ", isla)
    if vlan:
        red_lines.append(f"VLAN {vlan}" + (f" NOMBRE DE VRF: {vrf_name}" if vrf_name else ""))
    elif vrf_name:
        red_lines.append(f"NOMBRE DE VRF: {vrf_name}")
    _optional(red_lines, "RD ", rd)
    _optional(red_lines, "DESCRIPCION VRF ", vrf_desc)
    _optional(red_lines, "DESCRIPCION VLAN ", vlan_desc)
    recursos.extend(red_lines)

    if recursos:
        while recursos and not recursos[-1]:
            recursos.pop()
        lines.extend(["", "RECURSOS ASIGNADOS", "===================", "", *recursos])

    # El bloque de monitoreo reemplaza al antiguo campo PSK y solo aplica con loopback.
    if loopback:
        loopback_id = _text(data.get("loopback_id")) or defaults.loopback_id
        lines.extend([
            "",
            MONITOREO_SEPARATOR,
            "FAVOR DE AGREGAR LOOPBACK AL MONITOREO EN NMIS E ISE",
            "************************************************",
            "",
            f"ID DEL SERVICIO:  {id_servicio}",
            f"LOOPBACK {loopback_id} :  {loopback_ip}",
            f"NOMBRE DEL CLIENTE: {cliente}",
            f"EQUIPO: {equipo_cpe}",
            f"PRE-SHARED KEY: {defaults.psk_monitoreo}",
        ])

    return "\n".join(lines)
