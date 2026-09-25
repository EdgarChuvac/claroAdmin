import re

from typing import Any, Dict, List


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

def build_route_string(equipos: List[Dict[str, str]], raisecom_model: str = "RAISECOM RAX711-L", cisco_model: str = "CISCO C921") -> str:
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
    if claro_chain:
        return f"{claro_chain} ==> FO ==> {cliente_chain}"
    return cliente_chain


def generate_format_text(data: Dict[str, Any]) -> str:
    """
    Genera el formato estandarizado de Alta de Internet Corporativo con todos los datos.
    """
    cliente = _text(data.get("cliente"))
    direccion = _text(data.get("direccion"))
    coordenadas = _text(data.get("coordenadas"))
    disenador = _text(data.get("disenador"))
    tel_disenador = _text(data.get("tel_disenador"))
    fecha = _text(data.get("fecha"))
    
    titulo = _text(data.get("titulo"), "INTERNET CORPORATIVO")
    contacto_tec = _text(data.get("contacto_tec"))
    ejecutivo = _text(data.get("ejecutivo"))
    consultor = _text(data.get("consultor"))
    medio = _text(data.get("medio"), "FIBRA")
    factibilidad = _text(data.get("factibilidad"))
    equipo_cpe = _text(data.get("equipo_cpe"), "CISCO C921")
    velocidad = _text(data.get("velocidad"), "300 MBPS")
    ips_count = _text(data.get("ips_count"), "1")
    observaciones = _text(data.get("observaciones"), "ALTA DE IC")
    
    # Items aceptados
    items = data.get("items_aceptados", [
        f"INTERNET CORPORATIVO LOCAL {velocidad}  (ACEPTADO)",
        "ARRENDAMIENTO EQUIPO  (ACEPTADO)",
        "MONITOREO ENLACE  (ACEPTADO)"
    ])
    clean_items = [_text(item).lstrip("• ") for item in items if _text(item)]
    items_block = "\n".join([f"\t• {item}" for item in clean_items])
    
    # Ruta
    equipos = data.get("equipos_claro", [])
    raisecom = data.get("equipo_raisecom", "RAISECOM RAX711-L")
    ruta_str = _text(data.get("ruta_manual"))
    if not ruta_str:
        ruta_str = build_route_string(equipos, raisecom, equipo_cpe)
        
    # Recursos Gestor Raisecom
    vrf_gestor = _text(data.get("vrf_gestor"), "GESTOR_RAISECOM")
    vlan_gestor = _text(data.get("vlan_gestor"), "836")
    red_gestor = _text(data.get("red_gestor"), "10.40.3.0/24")
    gw_gestor = _text(data.get("gw_gestor"), "10.40.3.1")
    ip_gestor_raisecom = _text(data.get("ip_gestor_raisecom"), "10.40.3.120")
    
    # Recursos WAN (del Excel)
    red_wan = _text(data.get("red_wan"))
    gw_wan = _text(data.get("gw_wan"))
    ip_wan = _text(data.get("ip_wan"))
    
    # Loopback y LAN
    loopback = _text(data.get("loopback"))
    lan = _text(data.get("lan"))
    lan_obs = _text(data.get("lan_obs"))
    lan_line = f"{lan} | {lan_obs}".strip(" |")
    
    # Isla y VLAN
    isla = _text(data.get("isla"))
    vlan_num = _text(data.get("vlan_num"))
    desc_vlan = _text(data.get("desc_vlan"))
    
    # Huawei ip vpn-instance
    vrf_name = _text(data.get("vrf_name"), "INTERNET_GT_METRO")
    vrf_desc = _text(data.get("vrf_desc"), "INTERNET_PEs_METROPOLITANO_ISLA_APP")
    rd = _text(data.get("rd"), "6458:11270")
    vpn_targets = data.get("vpn_targets", [
        "  vpn-target 6458:11270 export-extcommunity",
        "  vpn-target 6458:18900 export-extcommunity",
        "  vpn-target 6458:11270 import-extcommunity",
        "  vpn-target 6458:11540 import-extcommunity",
        "  vpn-target 6458:11280 import-extcommunity",
        "  vpn-target 6458:11290 import-extcommunity",
        "  vpn-target 6458:10130 import-extcommunity",
        "  vpn-target 6458:1150 import-extcommunity",
        "  vpn-target 6458:18900 import-extcommunity",
        "  vpn-target 6458:18910 import-extcommunity",
        "  vpn-target 6458:18920 import-extcommunity",
        "  vpn-target 6458:18930 import-extcommunity",
        "  vpn-target 6458:15200 import-extcommunity"
    ])
    if isinstance(vpn_targets, str):
        vpn_targets_str = vpn_targets
    else:
        vpn_targets_str = "\n".join(vpn_targets)
        
    # Monitoreo
    id_servicio = _text(data.get("id_servicio"))
    loopback_id = _text(data.get("loopback_id"), "5")
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

    # Determinar prefijo y títulos según la opción seleccionada
    tipo_servicio = titulo if titulo else "INTERNET CORPORATIVO"
    if "DATOS" in tipo_servicio.upper():
        prefijo_linea2 = "DATOS"
        banner_tipo = "DATOS"
        linea1 = "DATOS"
    elif "ACCESO EMPRESARIAL" in tipo_servicio.upper():
        prefijo_linea2 = "ACCESO EMPRESARIAL"
        banner_tipo = "ACCESO EMPRESARIAL"
        linea1 = "ACCESO EMPRESARIAL"
    else:
        prefijo_linea2 = "INTERNET"
        banner_tipo = "INTERNET CORPORATIVO"
        linea1 = "INTERNET CORPORATIVO"

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
        "",
        f"LOOPBACK {loopback}",
        f"LAN {lan_line}",
        "",
        f"ISLA {isla}",
        f"VLAN {vlan_num} DESCRIPCION {desc_vlan}",
        "",
        "#",
        f"ip vpn-instance {vrf_name}",
        f" description {vrf_desc}",
        " ipv4-family",
        f"  route-distinguisher {rd}",
        "  import route-policy FILTROINTERNET",
        f"  export route-policy EXP_{vrf_name}",
        "  apply-label per-instance",
        vpn_targets_str,
        " traffic-policy pt-BCP38-PUBLICAS network inbound",
        "#",
        "",
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
