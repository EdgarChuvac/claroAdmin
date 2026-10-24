"""Generación del texto de alta (INTERNET y DATOS corporativos).

El formato imprime únicamente los datos que se llenaron: una línea cuyo valor
está vacío no aparece en el texto final. Estructura::

    DISEÑO REALIZADO POR … | FECHA …
    ****ALTA DE <banner>****
    <bloque de factibilidad pegado>
    ****
    RUTA A CONFIGURAR
    RECURSOS ASIGNADOS (gestión, IP WAN, loopback, isla/VLAN, ip vpn-instance)
    <ID de servicio>
    <observaciones>
    [bloque de monitoreo NMIS/ISE si hay loopback]
"""

import re
from typing import Any, Dict, List, Optional

from .catalog import Catalog, default_catalog

FACTIBILIDAD_SEPARATOR = "*" * 86
MONITOREO_SEPARATOR = "-" * 64
SIN_FACTIBILIDAD = "SIN FACTIBILIDAD"


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _vlan_config_lines(value: str) -> List[str]:
    """Conserva líneas y separa comandos que Firebase haya almacenado juntos."""
    config = value.replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not config:
        return []
    commands = (
        "ip vpn-instance", "description", "ipv4-family", "route-distinguisher",
        "import route-policy", "export route-policy", "apply-label", "vpn-target",
        "traffic-policy",
    )
    marker = r"(?=\s+(?:#(?=\s|$)|(?:" + "|".join(re.escape(command) for command in commands) + r")\b))"
    lines: List[str] = []
    for source_line in config.splitlines():
        parts = re.split(marker, source_line.strip())
        commands_on_line = [part.strip() for part in parts if part.strip()]
        if len(commands_on_line) <= 1:
            lines.append(source_line.rstrip())
            continue
        for command in commands_on_line:
            if command.startswith("#") or command.startswith("ip vpn-instance"):
                lines.append(command)
            elif command.startswith(("description", "ipv4-family")):
                lines.append(f" {command}")
            elif command.startswith(commands[3:]):
                lines.append(f"  {command}")
            else:
                lines.append(command)
    return lines


def _equipment_order(eq: Dict[str, Any]) -> tuple[int, int]:
    """Ordena por la numeración de la tabla (1, 2, 3...); sin número va al final."""
    try:
        return (0, int(_text(eq.get("no"))))
    except ValueError:
        return (1, 0)


def _slot_port(slot: str, puerto: str) -> str:
    return "|".join(p for p in (f"S{slot}" if slot else "", f"P{puerto}" if puerto else "") if p)


def chasis_hop(nombre: str, id_fisico: str = "", slot: str = "", puerto: str = "") -> str:
    """Etiqueta de posición que se agrega al último equipo de la ruta."""
    return _slot_port(_text(slot), _text(puerto))


def build_route_string(
    equipos: List[Dict[str, str]],
    raisecom_model: str = "RAISECOM RAX711-L",
    cpe_model: str = "CISCO C921",
    medio: str = "FO",
    chasis: str = "",
) -> str:
    """Ruta: ``Rol Marca Modelo Hostname (IP) Interfaz --> … ==> MEDIO ==> (CLIENTE) DEMARCADOR --> CPE``.

    Los equipos extremo Claro se encadenan según su numeración, empezando por el 1.
    Si hay posición de chasis, se agrega al último equipo Claro y se omite su interfaz de salida.
    """
    parts = []
    client_parts = []
    claro_equipos = sorted(
        (eq for eq in equipos if _text(eq.get("lado")).upper() != "CLIENTE"),
        key=_equipment_order,
    )
    equipos_cliente = sorted(
        (eq for eq in equipos if _text(eq.get("lado")).upper() == "CLIENTE"),
        key=_equipment_order,
    )
    position = _text(chasis)
    for index, eq in enumerate(claro_equipos):
        name = " ".join(p for p in (_text(eq.get(k)) for k in ("rol", "marca", "modelo", "hostname")) if p)
        ip = _text(eq.get("ip_admon"))
        if ip:
            name = f"{name} ({ip})".strip()
        int_out = _text(eq.get("int_out"))
        is_last_with_position = bool(position) and index == len(claro_equipos) - 1
        if int_out and not is_last_with_position:
            name = f"{name} {int_out}".strip()
        if name:
            if is_last_with_position:
                name = f"{name} {position}".strip()
            parts.append(name)
    for eq in equipos_cliente:
        name = " ".join(p for p in (_text(eq.get(k)) for k in ("rol", "marca", "modelo", "hostname")) if p)
        ip = _text(eq.get("ip_admon"))
        if ip:
            name = f"{name} ({ip})".strip()
        int_out = _text(eq.get("int_out"))
        if int_out:
            name = f"{name} {int_out}".strip()
        if name:
            client_parts.append(name)

    cliente_chain = f"(CLIENTE) {raisecom_model}"
    if cpe_model:
        cliente_chain += f" --> {cpe_model}"
    if client_parts:
        cliente_chain = " --> ".join(client_parts)
    claro_chain = " --> ".join(parts)
    if not claro_chain:
        if position:
            return f"{position} ==> {medio} ==> {cliente_chain}" if medio else f"{position} ==> {cliente_chain}"
        return cliente_chain
    medio = _text(medio)
    return f"{claro_chain} ==> {medio} ==> {cliente_chain}" if medio else f"{claro_chain} ==> {cliente_chain}"


def _vpn_targets(rd: str, configured: Any) -> List[str]:
    """vpn-targets: los configurados; si no incluyen el RD, se anteponen su export e import."""
    raw = configured.splitlines() if isinstance(configured, str) else [str(v) for v in configured or []]
    targets = []
    for item in raw:
        item = item.strip()
        if item.lower().startswith("vpn-target"):
            item = item[len("vpn-target"):].strip()
        if item and item not in targets:
            targets.append(item)
    if rd:
        own = [f"{rd} export-extcommunity", f"{rd} import-extcommunity"]
        if not any(t.startswith(f"{rd} ") for t in targets):
            targets = own + targets
    return targets


def build_vpn_instance_block(
    vrf_name: str,
    vrf_desc: str = "",
    rd: str = "",
    import_policy: str = "",
    export_policy: str = "",
    apply_label: bool = True,
    vpn_targets: Any = None,
    traffic_policy: str = "",
) -> List[str]:
    """Bloque ``ip vpn-instance`` de Huawei. Se omite si no hay VRF."""
    if not vrf_name:
        return []
    block = ["#", f"ip vpn-instance {vrf_name}"]
    if vrf_desc:
        block.append(f" description {vrf_desc}")
    block.append("ipv4-family")
    if rd:
        block.append(f" route-distinguisher {rd}")
    if import_policy:
        block.append(f" import route-policy {import_policy}")
    if export_policy:
        block.append(f" export route-policy {export_policy.format(vrf_name=vrf_name)}")
    if apply_label:
        block.append(" apply-label per-instance")
    block.extend(f" vpn-target {t}" for t in _vpn_targets(rd, vpn_targets))
    if traffic_policy:
        block.append(f" traffic-policy {traffic_policy}")
    block.append("#")
    return block


def _ip_line(ip: str, label: str) -> str:
    return f"{ip}    {label}" if ip else ""


def generate_format_text(data: Dict[str, Any], catalog: Optional[Catalog] = None) -> str:
    """Genera el formato de alta según el tipo de servicio (INTERNET o DATOS)."""
    catalog = catalog or default_catalog()
    defaults = catalog.network_defaults
    template = catalog.service(_text(data.get("titulo"), "INTERNET"))

    def pick(key: str, fallback: str) -> str:
        """El formulario manda; la plantilla solo si el campo no se envió."""
        value = data.get(key)
        return fallback if value is None else _text(value)

    cliente = _text(data.get("cliente"))
    disenador = _text(data.get("disenador"))
    tel_disenador = _text(data.get("tel_disenador"))
    fecha = _text(data.get("fecha"))
    id_servicio = _text(data.get("id_servicio"))
    observaciones = _text(data.get("observaciones"))

    factibilidad_bloque = _text(data.get("factibilidad_bloque"))
    sin_factibilidad = bool(data.get("sin_factibilidad")) and not factibilidad_bloque

    # Ruta
    medio_key = _text(data.get("medio"), "FIBRA").upper()
    medio = catalog.medios.get(medio_key)
    equipo_cpe = _text(data.get("equipo_cpe")) or defaults.equipo_cpe
    demarcador = _text(data.get("equipo_raisecom")) or defaults.equipo_raisecom
    chasis_position = chasis_hop(data.get("chasis_nombre"), data.get("chasis_id_fisico"),
                                 data.get("chasis_slot"), data.get("chasis_puerto"))
    if medio_key == "GPON":
        chasis_position = "<Slot X|Puerto X|Onu ID X>"
    ruta = _text(data.get("ruta_manual")) or build_route_string(
        data.get("equipos_claro") or [], demarcador, equipo_cpe, catalog.medio_ruta(medio_key),
        chasis_position,
    )
    obs_medio = _text(data.get("obs_medio"))

    # Recursos
    gestion_label = (medio.demarcador if medio else "") or "RAISECOM"
    gestion = [
        " ".join(p for p in (
            f"VRF {_text(data.get('vrf_gestor'))}" if _text(data.get("vrf_gestor")) else "",
            f"VLAN {_text(data.get('vlan_gestor'))}" if _text(data.get("vlan_gestor")) else "",
            _text(data.get("desc_gestor")),
        ) if p),
        f"{_text(data.get('red_gestor'))} RED" if _text(data.get("red_gestor")) else "",
        _ip_line(_text(data.get("gw_gestor")), "GW"),
        _ip_line(_text(data.get("ip_gestor_raisecom")), gestion_label),
    ]
    red_wan = _text(data.get("red_wan"))
    gw_wan = _text(data.get("gw_wan"))
    ip_wan = _text(data.get("ip_wan"))
    ips_adicionales = [_text(ip) for ip in data.get("ips_adicionales") or [] if _text(ip)]
    wan = []
    if red_wan or gw_wan or ip_wan or ips_adicionales:
        wan = ["IP WAN", f"{red_wan} RED" if red_wan else "", _ip_line(gw_wan, "GW"), _ip_line(ip_wan, "WAN"),
               *(_ip_line(ip, "ADICIONAL") for ip in ips_adicionales)]
    ip_publica = _text(data.get("ip_publica")) if template.ip_publica else ""
    loopback = _text(data.get("loopback"))
    loopback_ip = loopback.split("/")[0]
    if loopback and "/" not in loopback:
        loopback = f"{loopback}/32"
    vlan = _text(data.get("vlan_num"))
    vlan_desc = _text(data.get("desc_vlan"))
    vlan_line = " ".join(p for p in (f"VLAN: {vlan}" if vlan else "",
                                    f"DESCRIPCION: {vlan_desc}" if vlan_desc else "") if p)
    vrf_name = pick("vrf_name", template.vrf_name)
    vlan_config = _text(data.get("vlan_config"))
    vpn_block = (_vlan_config_lines(vlan_config) if vlan_config else
                 build_vpn_instance_block(
                     vrf_name=vrf_name,
                     vrf_desc=pick("vrf_desc", template.vrf_desc),
                     rd=pick("rd", template.rd),
                     import_policy=template.import_policy,
                     export_policy=template.export_policy,
                     apply_label=template.apply_label_per_instance,
                     vpn_targets=template.vpn_targets if data.get("vpn_targets") is None else data.get("vpn_targets"),
                     traffic_policy=template.traffic_policy,
                 ))
    sections = [
        gestion,
        wan,
        [f"IP PUBLICA: {ip_publica}" if ip_publica else ""],
        [f"LOOPBACK: {loopback}" if loopback else ""],
        [f"ISLA: {_text(data.get('isla'))}" if _text(data.get("isla")) else "", vlan_line],
        vpn_block,
    ]
    sections = [[line for line in section if line] for section in sections]
    sections = [section for section in sections if section]

    designer = " ".join(p for p in (disenador, tel_disenador) if p)
    lines = [
        f"DISEÑO REALIZADO POR {designer} | FECHA {fecha}".strip(" |"),
        f"***********************ALTA DE {template.banner}**********************",
        "",
    ]
    if factibilidad_bloque:
        lines.extend(line.rstrip() for line in factibilidad_bloque.splitlines())
    elif sin_factibilidad:
        lines.append(SIN_FACTIBILIDAD)
    lines.extend(["", FACTIBILIDAD_SEPARATOR, "", "", "RUTA A CONFIGURAR", "=" * 17, "", ruta])
    if obs_medio:
        lines.append(f"OBSERVACIONES DE MEDIO: {obs_medio}")

    if sections:
        lines.extend(["", "RECURSOS ASIGNADOS", "=" * 18])
        for section in sections:
            lines.append("")
            lines.extend(section)

    # El ID del servicio solo aparece etiquetado en el bloque de monitoreo.
    footer = [observaciones] if observaciones else []
    if footer:
        lines.append("")
        lines.extend(footer)

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
