"""Generación del texto de alta (Internet Corporativo, Datos, Acceso Empresarial)."""

import re
from typing import Any, Dict, List, Optional

from .catalog import Catalog, default_catalog


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _replace_fact_line(block: str, label: str, value: str) -> str:
    if not value:
        return block
    pattern = rf"(?im)^{re.escape(label)}\s*[:\t]?\s*.*$"
    replacement = f"{label}:\t{value}"
    if re.search(pattern, block):
        return re.sub(pattern, lambda _: replacement, block)
    return f"{block.rstrip()}\n{replacement}"

def build_route_string(equipos: List[Dict[str, str]], raisecom_model: str = "RAISECOM RAX711-L", cisco_model: str = "CISCO C921", enlace: str = "FO") -> str:
    """
    Construye la cadena de ruta a partir de la lista de equipos extremo Claro y equipos cliente.
    Ejemplo:
    PE EL CARMEN HUAWEI NE40E ... (IP) --> SW HUAWEI ATN980C ... Eth-Trunk12 --> TRÁFICO CTC-FRM220A-07 ... S15|P2 ==> FO ==> (CLIENTE) RAISECOM RAX711-L --> CISCO C921
    """
    parts = []
    for eq in equipos:
        rol = _text(eq.get("rol"))
        marca = _text(eq.get("marca"))
        modelo = _text(eq.get("modelo"))
        hostname = _text(eq.get("hostname"))
        ip = _text(eq.get("ip_admon"))
        int_in = _text(eq.get("int_in"))
        int_out = _text(eq.get("int_out"))

        # Ensamblar nombre del equipo
        header = f"{rol} {marca} {modelo}".strip()
        if hostname:
            header += f" {hostname}"
        if ip:
            header += f" ({ip})"
        if int_in:
            header += f" {int_in}"
        if int_out:
            header += f" {int_out}"

        parts.append(header)

    claro_chain = " --> ".join(parts) if parts else ""

    # Agregar extremo cliente con enlace de Fibra Óptica (FO)
    cliente_chain = f"(CLIENTE) {raisecom_model} --> {cisco_model}"
    enlace = _text(enlace) or "FO"
    if claro_chain:
        return f"{claro_chain} ==> {enlace} ==> {cliente_chain}"
    return cliente_chain


def _vpn_target_lines(value: Any) -> List[str]:
    if value is None:
        return []
    raw = value.splitlines() if isinstance(value, str) else [str(v) for v in value]
    lines = []
    for item in raw:
        item = item.strip()
        if not item:
            continue
        if not item.lower().startswith("vpn-target"):
            item = f"vpn-target {item}"
        lines.append(f"  {item}")
    return lines


def build_vpn_instance_block(
    vrf_name: str,
    vrf_desc: str,
    rd: str,
    import_policy: str,
    export_policy: str,
    apply_label: bool,
    vpn_targets: List[str],
    traffic_policy: str,
) -> List[str]:
    """Bloque ``ip vpn-instance`` de Huawei. Se omite si no hay VRF."""
    if not vrf_name:
        return []
    block = ["#", f"ip vpn-instance {vrf_name}"]
    if vrf_desc:
        block.append(f" description {vrf_desc}")
    block.append(" ipv4-family")
    if rd:
        block.append(f"  route-distinguisher {rd}")
    if import_policy:
        block.append(f"  import route-policy {import_policy}")
    if export_policy:
        block.append(f"  export route-policy {export_policy.format(vrf_name=vrf_name)}")
    if apply_label:
        block.append("  apply-label per-instance")
    block.extend(vpn_targets)
    if traffic_policy:
        block.append(f" traffic-policy {traffic_policy}")
    block.extend(["#", ""])
    return block


def generate_format_text(data: Dict[str, Any], catalog: Optional[Catalog] = None) -> str:
    """
    Genera el formato estandarizado de alta según el tipo de servicio.

    Los campos vacíos se completan con la plantilla del tipo de servicio
    (``config/service_templates.json``) y los valores por defecto de red.
    """
    catalog = catalog or default_catalog()
    defaults = catalog.network_defaults
    titulo = _text(data.get("titulo"), "INTERNET CORPORATIVO")
    template = catalog.service(titulo)

    cliente = _text(data.get("cliente"))
    direccion = _text(data.get("direccion"))
    coordenadas = _text(data.get("coordenadas"))
    disenador = _text(data.get("disenador"))
    tel_disenador = _text(data.get("tel_disenador"))
    fecha = _text(data.get("fecha"))

    contacto_tec = _text(data.get("contacto_tec"))
    ejecutivo = _text(data.get("ejecutivo"))
    consultor = _text(data.get("consultor"))
    medio = _text(data.get("medio"), "FIBRA")
    factibilidad = _text(data.get("factibilidad"))
    equipo_cpe = _text(data.get("equipo_cpe")) or defaults.equipo_cpe
    velocidad = _text(data.get("velocidad"), "300 MBPS")
    ips_count = _text(data.get("ips_count"), "1")
    observaciones = _text(data.get("observaciones")) or template.observaciones

    # Items aceptados
    items = data.get("items_aceptados")
    if not items:
        items = template.default_items(template.label, velocidad)
    clean_items = [_text(item).lstrip("• ") for item in items if _text(item)]
    items_block = "\n".join([f"\t• {item}" for item in clean_items])

    # Ruta y medio
    equipos = data.get("equipos_claro", [])
    raisecom = _text(data.get("equipo_raisecom")) or defaults.equipo_raisecom
    enlace_medio = _text(data.get("enlace_medio")) or defaults.enlace_medio
    obs_medio = _text(data.get("obs_medio"))
    ruta_str = _text(data.get("ruta_manual"))
    if not ruta_str:
        ruta_str = build_route_string(equipos, raisecom, equipo_cpe, enlace_medio)

    # Recursos Gestor Raisecom
    vrf_gestor = _text(data.get("vrf_gestor")) or defaults.vrf_gestor
    vlan_gestor = _text(data.get("vlan_gestor")) or defaults.vlan_gestor
    red_gestor = _text(data.get("red_gestor")) or defaults.red_gestor
    gw_gestor = _text(data.get("gw_gestor")) or defaults.gw_gestor
    ip_gestor_raisecom = _text(data.get("ip_gestor_raisecom")) or defaults.ip_gestor_raisecom

    # Recursos WAN (del inventario)
    red_wan = _text(data.get("red_wan"))
    gw_wan = _text(data.get("gw_wan"))
    ip_wan = _text(data.get("ip_wan"))
    ips_adicionales = [_text(ip) for ip in data.get("ips_adicionales", []) or [] if _text(ip)]

    # Loopback y LAN
    loopback = _text(data.get("loopback"))
    lan = _text(data.get("lan"))
    lan_obs = _text(data.get("lan_obs"))
    lan_line = f"{lan} | {lan_obs}".strip(" |")

    # Isla y VLAN
    isla = _text(data.get("isla"))
    vlan_num = _text(data.get("vlan_num"))
    desc_vlan = _text(data.get("desc_vlan"))

    # Huawei ip vpn-instance: el formulario manda; la plantilla es el respaldo
    # solo cuando el campo no se envió (None).
    def pick(key: str, fallback: str) -> str:
        value = data.get(key)
        return fallback if value is None else _text(value)

    vrf_name = pick("vrf_name", template.vrf_name)
    vrf_desc = pick("vrf_desc", template.vrf_desc)
    rd = pick("rd", template.rd)
    vpn_targets_value = data.get("vpn_targets")
    vpn_target_lines = _vpn_target_lines(
        template.vpn_targets if vpn_targets_value is None else vpn_targets_value
    )
    vpn_block = build_vpn_instance_block(
        vrf_name=vrf_name,
        vrf_desc=vrf_desc,
        rd=rd,
        import_policy=template.import_policy,
        export_policy=template.export_policy,
        apply_label=template.apply_label_per_instance,
        vpn_targets=vpn_target_lines,
        traffic_policy=template.traffic_policy,
    )

    # Monitoreo
    id_servicio = _text(data.get("id_servicio"))
    loopback_id = _text(data.get("loopback_id")) or defaults.loopback_id
    loopback_ip = loopback.split("/")[0] if "/" in loopback else loopback
    psk = _text(data.get("psk"))

    # Factibilidad: bloque pegado o ensamblado campo a campo
    factibilidad_bloque = _text(data.get("factibilidad_bloque"))

    # Si viene el bloque pegado, extraer automáticamente dirección y coordenadas si no vienen dadas
    if factibilidad_bloque:
        if not direccion:
            dir_match = re.search(r'DIRECCION[:\t\s]+([^,\n\r]+(?:,[^,\n\r]+)*?)(?=,\s*//|\s*//|\n|$)', factibilidad_bloque, re.IGNORECASE)
            if dir_match:
                direccion = dir_match.group(1).strip()
        if not coordenadas:
            coords_match = re.search(r'COORDENADAS[:\t\s]+([^\n\r*]+)', factibilidad_bloque, re.IGNORECASE)
            if coords_match:
                coordenadas = coords_match.group(1).strip()

    tipo_servicio = titulo
    prefijo_linea2 = template.prefijo_linea2
    banner_tipo = template.banner
    linea1 = template.linea1

    # Ensamblado del formato final
    lines = [
        linea1,
        f"{prefijo_linea2} {cliente} {direccion} {coordenadas}".strip(),
        "",
        f"DISEÑO REALIZADO POR {disenador} {tel_disenador} | FECHA {fecha}".strip(" |"),
        f"***********************ALTA DE {banner_tipo}**********************",
        ""
    ]

    if factibilidad_bloque:
        # Los campos del formulario son la fuente vigente y prevalecen sobre el bloque pegado.
        title_replacement = f"TITULO:\t***{tipo_servicio}***"
        factibilidad_bloque = re.sub(
            r'TITULO:[\t\s]*\*\*\*[^*]+\*\*\*',
            lambda _: title_replacement,
            factibilidad_bloque,
            flags=re.IGNORECASE,
        )
        for label, value in (
            ("CONTACTO TEC", contacto_tec),
            ("EJECUTIVO", ejecutivo),
            ("CONSULTOR", consultor),
            ("MEDIO", medio),
            ("FACTIBILIDAD", factibilidad),
            ("EQUIPO", equipo_cpe),
            ("VELOCIDAD", velocidad),
            ("IPS", ips_count),
            ("OBSERVACIONES", observaciones),
        ):
            factibilidad_bloque = _replace_fact_line(factibilidad_bloque, label, value)
        if direccion or coordenadas:
            location = f"{direccion}, // COORDENADAS: {coordenadas}".strip(" ,")
            factibilidad_bloque = _replace_fact_line(
                factibilidad_bloque, "DIRECCION", location
            )
        lines.append(factibilidad_bloque)
        if not factibilidad_bloque.endswith("****"):
            lines.extend(["", "****"])
    else:
        lines.extend([
            f"TITULO:\t***{titulo}***",
            f"CONTACTO TEC:\t{contacto_tec}",
        ])
        if ejecutivo:
            lines.append(f"EJECUTIVO:\t{ejecutivo}")
        lines.extend([
            f"CONSULTOR:\t{consultor}",
            f"MEDIO:\t{medio}",
            f"FACTIBILIDAD:\t{factibilidad}",
            f"EQUIPO:\t{equipo_cpe}",
            f"VELOCIDAD:\t{velocidad}",
            f"IPS:\t{ips_count}",
            f"DIRECCION\t{direccion}, // COORDENADAS: {coordenadas}",
            f"OBSERVACIONES:\t{observaciones}",
            "",
            "****"
        ])

    lines.extend([
        "",
        items_block,
        "",
        "RUTA A CONFIGURAR",
        "=================",
        "",
        ruta_str,
        "",
    ])
    if obs_medio:
        lines.extend([f"OBSERVACIONES DE MEDIO: {obs_medio}", ""])

    lines.extend([
        "RECURSOS ASIGNADOS",
        "===================",
        "",
        f"VRF {vrf_gestor} VLAN {vlan_gestor}",
        f"{red_gestor} RED",
        f"{gw_gestor}    GW",
        f"{ip_gestor_raisecom}  RAISECOM",
        "",
        "IP WAN",
        f"{red_wan} RED",
        f"{gw_wan}    GW",
        f"{ip_wan}    WAN",
    ])
    for extra_ip in ips_adicionales:
        lines.append(f"{extra_ip}    ADICIONAL")
    lines.extend([
        "",
        f"LOOPBACK {loopback}",
        f"LAN {lan_line}",
        "",
        f"ISLA {isla}",
        f"VLAN {vlan_num} DESCRIPCION {desc_vlan}",
        "",
    ])
    lines.extend(vpn_block)
    lines.extend([
        "FAVOR DE AGREGAR LOOPBACK AL MONITOREO EN NMIS E ISE",
        "************************************************",
        "",
        f"ID DEL SERVICIO:  {id_servicio}",
        f"LOOPBACK {loopback_id} :  {loopback_ip}",
        f"NOMBRE DEL CLIENTE: {cliente}",
        f"EQUIPO: {equipo_cpe}",
        f"PRE-SHARED KEY: {psk}"
    ])

    return "\n".join(lines)
