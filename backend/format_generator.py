from typing import Dict, Any, List

def build_route_string(equipos: List[Dict[str, str]], raisecom_model: str = "RAISECOM RAX711-L", cisco_model: str = "CISCO C921") -> str:
    """
    Construye la cadena de ruta a partir de la lista de equipos extremo Claro y equipos cliente.
    Ejemplo:
    PE EL CARMEN HUAWEI NE40E ... (IP) --> SW HUAWEI ATN980C ... Eth-Trunk12 --> TRÁFICO CTC-FRM220A-07 ... S15|P2 ==> FO ==> (CLIENTE) RAISECOM RAX711-L --> CISCO C921
    """
    parts = []
    for eq in equipos:
        rol = eq.get("rol", "").strip()
        marca = eq.get("marca", "").strip()
        modelo = eq.get("modelo", "").strip()
        hostname = eq.get("hostname", "").strip()
        ip = eq.get("ip_admon", "").strip()
        int_out = eq.get("int_out", "").strip()
        
        # Ensamblar nombre del equipo
        header = f"{rol} {marca} {modelo}".strip()
        if hostname:
            header += f" {hostname}"
        if ip:
            header += f" ({ip})"
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
    cliente = data.get("cliente", "").strip()
    direccion = data.get("direccion", "").strip()
    coordenadas = data.get("coordenadas", "").strip()
    disenador = data.get("disenador", "").strip()
    tel_disenador = data.get("tel_disenador", "").strip()
    fecha = data.get("fecha", "").strip()
    
    titulo = data.get("titulo", "INTERNET CORPORATIVO").strip()
    contacto_tec = data.get("contacto_tec", "").strip()
    ejecutivo = data.get("ejecutivo", "").strip()
    consultor = data.get("consultor", "").strip()
    medio = data.get("medio", "FIBRA").strip()
    factibilidad = data.get("factibilidad", "").strip()
    equipo_cpe = data.get("equipo_cpe", "CISCO C921").strip()
    velocidad = data.get("velocidad", "300 MBPS").strip()
    ips_count = data.get("ips_count", "1").strip()
    observaciones = data.get("observaciones", "ALTA DE IC").strip()
    
    # Items aceptados
    items = data.get("items_aceptados", [
        f"INTERNET CORPORATIVO LOCAL {velocidad}  (ACEPTADO)",
        "ARRENDAMIENTO EQUIPO  (ACEPTADO)",
        "MONITOREO ENLACE  (ACEPTADO)"
    ])
    items_block = "\n".join([f"\t• {item}" for item in items])
    
    # Ruta
    equipos = data.get("equipos_claro", [])
    raisecom = data.get("equipo_raisecom", "RAISECOM RAX711-L")
    ruta_str = data.get("ruta_manual", "").strip()
    if not ruta_str:
        ruta_str = build_route_string(equipos, raisecom, equipo_cpe)
        
    # Recursos Gestor Raisecom
    vrf_gestor = data.get("vrf_gestor", "GESTOR_RAISECOM").strip()
    vlan_gestor = data.get("vlan_gestor", "836").strip()
    red_gestor = data.get("red_gestor", "10.40.3.0/24").strip()
    gw_gestor = data.get("gw_gestor", "10.40.3.1").strip()
    ip_gestor_raisecom = data.get("ip_gestor_raisecom", "10.40.3.120").strip()
    
    # Recursos WAN (del Excel)
    red_wan = data.get("red_wan", "").strip()
    gw_wan = data.get("gw_wan", "").strip()
    ip_wan = data.get("ip_wan", "").strip()
    
    # Loopback y LAN
    loopback = data.get("loopback", "").strip()
    lan = data.get("lan", "").strip()
    lan_obs = data.get("lan_obs", "").strip()
    lan_line = f"{lan} | {lan_obs}".strip(" |")
    
    # Isla y VLAN
    isla = data.get("isla", "").strip()
    vlan_num = data.get("vlan_num", "").strip()
    desc_vlan = data.get("desc_vlan", "").strip()
    
    # Huawei ip vpn-instance
    vrf_name = data.get("vrf_name", "INTERNET_GT_METRO").strip()
    vrf_desc = data.get("vrf_desc", "INTERNET_PEs_METROPOLITANO_ISLA_APP").strip()
    rd = data.get("rd", "6458:11270").strip()
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
    id_servicio = data.get("id_servicio", "").strip()
    loopback_id = data.get("loopback_id", "5").strip()
    loopback_ip = loopback.split("/")[0] if "/" in loopback else loopback
    psk = data.get("psk", "").strip()
    
    # Factibilidad: bloque pegado o ensamblado campo a campo
    factibilidad_bloque = data.get("factibilidad_bloque", "").strip()
    
    # Si viene el bloque pegado, extraer automáticamente dirección y coordenadas si no vienen dadas
    if factibilidad_bloque:
        import re
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
        # Asegurar que la línea de TITULO en el bloque concuerde con la opción elegida
        factibilidad_bloque = re.sub(r'TITULO:[\t\s]*\*\*\*[^*]+\*\*\*', f'TITULO:\t***{tipo_servicio}***', factibilidad_bloque, flags=re.IGNORECASE)
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
