"use strict";

// ===========================================================================
// Estado
// ===========================================================================
const state = {
  config: null,
  operator: "",
  clientSession: "",
  sheets: [],
  blocks: [],
  selectedBlock: null,
  selectedFreeIPs: [],
  reservedForService: new Map(), // ip -> service_id reservado en esta sesión
  registeredAlta: null,          // { alta_id, text } del último registro vigente
  releaseTarget: null,
  sinFactibilidad: false,
  islaSegments: [],     // subredes de la isla seleccionada (sin detalle de IPs)
  vlanCatalog: [],      // datos guardados (RD, VRF, descripciones) de las VLAN de la isla
  currentVlan: "",      // "" = sin elegir, "*" = todas
  inventoryRequestId: 0,
  blocksRequestId: 0,
  formatRequestId: 0,
};

const STORAGE_KEYS = { operator: "claro.operator" };

function storageGet(key) {
  try { return window.localStorage.getItem(key) || ""; } catch { return ""; }
}
function storageSet(key, value) {
  try { window.localStorage.setItem(key, value); } catch { /* almacenamiento no disponible */ }
}

function $(id) { return document.getElementById(id); }

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.appendChild(typeof child === "string" || typeof child === "number" ? document.createTextNode(String(child)) : child);
  }
  return node;
}

function formatDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("es-GT", { dateStyle: "short", timeStyle: "short" });
}

// ===========================================================================
// API con trazabilidad
// ===========================================================================
class ApiError extends Error {
  constructor(message, operationId, status) {
    super(message);
    this.operationId = operationId;
    this.status = status;
  }
}

function setLastOperation(operationId) {
  if (!operationId) return;
  $("last-operation-id").textContent = operationId;
}

async function api(path, { method = "GET", json, formData, raw = false } = {}) {
  const headers = { "X-Client-Session": state.clientSession };
  if (state.operator) headers["X-Operator"] = encodeURIComponent(state.operator);
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (formData) {
    body = formData;
  }
  let response;
  try {
    response = await fetch(path, { method, headers, body });
  } catch (err) {
    throw new ApiError("No se pudo conectar con el servidor.", "", 0);
  }
  const operationId = response.headers.get("X-Operation-ID") || "";
  if (method !== "GET" || !response.ok) setLastOperation(operationId);
  if (!response.ok) {
    let detail = `Error ${response.status}`;
    try {
      const data = await response.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch { /* respuesta sin JSON */ }
    throw new ApiError(detail, operationId, response.status);
  }
  if (raw) return { response, operationId };
  const data = await response.json();
  return { ...data, operation_id: data.operation_id || operationId };
}

// ===========================================================================
// Notificaciones y diálogos
// ===========================================================================
function toast(message, type = "info", operationId = "") {
  const container = $("toast-container");
  const item = el("div", { class: `toast toast-${type}`, role: type === "error" ? "alert" : "status" },
    el("div", { class: "toast-message" }, message),
    operationId ? el("div", { class: "toast-op" },
      "ID de operación: ",
      el("button", { type: "button", class: "link-btn mono", title: "Copiar", onclick: () => copyText(operationId, "ID copiado") }, operationId)
    ) : null,
    el("button", { type: "button", class: "toast-close", "aria-label": "Cerrar", onclick: () => item.remove() }, "×")
  );
  container.appendChild(item);
  const ttl = type === "error" ? 15000 : 6000;
  setTimeout(() => item.remove(), ttl);
}

function showError(err, prefix = "") {
  console.error(err);
  const message = prefix ? `${prefix}: ${err.message}` : err.message;
  toast(message, "error", err.operationId || "");
}

function openModal(id) {
  const modal = $(id);
  modal.hidden = false;
  const focusable = modal.querySelector("input:not([type=hidden]), textarea, select, button.btn-primary");
  if (focusable) focusable.focus();
}

function closeModal(id) {
  $(id).hidden = true;
}

function confirmDialog(message, { title = "Confirmar", accept = "Confirmar", danger = false } = {}) {
  return new Promise(resolve => {
    $("confirm-modal-title").textContent = title;
    $("confirm-modal-message").textContent = message;
    const acceptBtn = $("confirm-accept");
    const cancelBtn = $("confirm-cancel");
    acceptBtn.textContent = accept;
    acceptBtn.className = danger ? "btn btn-danger" : "btn btn-primary";
    const finish = value => {
      acceptBtn.onclick = null;
      cancelBtn.onclick = null;
      closeModal("confirm-modal");
      resolve(value);
    };
    acceptBtn.onclick = () => finish(true);
    cancelBtn.onclick = () => finish(false);
    openModal("confirm-modal");
    acceptBtn.focus();
  });
}

async function copyText(text, okMessage = "Copiado al portapapeles") {
  try {
    await navigator.clipboard.writeText(text);
    toast(okMessage, "success");
  } catch {
    toast("No se pudo copiar automáticamente. Selecciónelo y use Ctrl+C.", "warning");
  }
}

function copyLastOperationId() {
  const value = $("last-operation-id").textContent.trim();
  if (value && value !== "—") copyText(value, "ID de operación copiado");
}

// ===========================================================================
// Inicio
// ===========================================================================
document.addEventListener("DOMContentLoaded", async () => {
  state.clientSession = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())).slice(0, 36);
  initAccessibility();
  initTabs();
  initKeyboard();
  initDateField();
  initImportModal();
  initOperator();
  updateFactibilidadBadge();

  document.body.addEventListener("input", event => {
    if (event.target.closest(".modal-overlay") || event.target.id === "output-format-textarea") return;
    markFormatStale();
    updateGenerationAvailability();
  });
  document.body.addEventListener("change", event => {
    if (event.target.closest(".modal-overlay")) return;
    updateGenerationAvailability();
  });

  await loadConfig();
  updateGenerationAvailability();
  await loadInventory();
  loadAltasHistory();
  $("p-id-servicio").addEventListener("change", () => { if ($("eq-loopback-auto").checked) onLoopbackToggle(); });
});

function initAccessibility() {
  const tabList = document.querySelector(".tabs-nav");
  tabList.setAttribute("role", "tablist");
  document.querySelectorAll(".tab-btn").forEach(button => {
    const panelId = button.dataset.tab;
    if (!button.id) button.id = `${panelId}-button`;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", panelId);
    button.setAttribute("aria-selected", String(button.classList.contains("active")));
    const panel = $(panelId);
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", button.id);
  });
  document.querySelectorAll(".form-group, .ipam-field").forEach(group => {
    const label = group.querySelector("label");
    const control = group.querySelector("input, select, textarea");
    if (!label || !control || label.htmlFor) return;
    if (!control.id) control.id = `field-${Math.random().toString(36).slice(2)}`;
    label.htmlFor = control.id;
  });
}

function initTabs() {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => activateTab(btn.dataset.tab));
  });
}

// Las pestañas de captura se habilitan cuando la factibilidad está cargada o se marcó «Sin factibilidad».
function factibilidadResuelta() {
  return state.sinFactibilidad || $("p-factibilidad-bloque").value.trim().length > 0;
}

function isGatedTab(tabId) {
  return !["tab-principal", "tab-consultas"].includes(tabId);
}

function activateTab(tabId) {
  if (isGatedTab(tabId) && !factibilidadResuelta()) {
    toast("Cargue la factibilidad o pulse «Sin factibilidad» para continuar.", "warning");
    tabId = "tab-principal";
    $("p-factibilidad-quick-paste").focus();
  }
  document.querySelectorAll(".tab-btn").forEach(b => {
    const active = b.dataset.tab === tabId;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".tab-content").forEach(tc => tc.classList.toggle("active", tc.id === tabId));
  if (tabId === "tab-generar" && !state.registeredAlta) updateGeneratedFormat();
  if (tabId === "tab-consultas") loadAltasHistory();
}

function initKeyboard() {
  document.addEventListener("keydown", e => {
    if (e.key === "F2") {
      // Un único manejador: abre el editor con la factibilidad ya cargada (o lo cierra).
      e.preventDefault();
      if ($("factibilidad-modal").hidden) openFactibilidadModal();
      else closeModal("factibilidad-modal");
    } else if (e.key === "Escape") {
      for (const id of ["factibilidad-modal", "import-modal", "release-modal", "alta-modal", "isla-modal"]) {
        if (!$(id).hidden) closeModal(id);
      }
      if (!$("confirm-modal").hidden) $("confirm-cancel").click();
    }
  });
}

// ===========================================================================
// Operador (sin login: nombre guardado en el navegador)
// ===========================================================================
function initOperator() {
  setOperator(storageGet(STORAGE_KEYS.operator));
  if (!state.operator) openOperatorModal();
}

function setOperator(name) {
  state.operator = (name || "").trim().slice(0, 80);
  $("operator-name").textContent = state.operator || "Sin operador";
  $("operator-chip").classList.toggle("missing", !state.operator);
  const designer = $("p-disenador");
  if (state.operator && !designer.value.trim()) designer.value = state.operator.toUpperCase();
}

function openOperatorModal() {
  $("operator-input").value = state.operator;
  openModal("operator-modal");
}

function saveOperator(event) {
  event.preventDefault();
  const value = $("operator-input").value.trim();
  if (value.length < 3) return;
  setOperator(value);
  storageSet(STORAGE_KEYS.operator, state.operator);
  closeModal("operator-modal");
  toast(`Operando como ${state.operator}`, "success");
}

function ensureOperator() {
  if (state.operator) return true;
  openOperatorModal();
  toast("Indique su nombre de operador para continuar.", "warning");
  return false;
}

// ===========================================================================
// Configuración: plantillas de servicio y catálogo de centrales
// ===========================================================================
async function loadConfig() {
  try {
    state.config = await api("/api/config");
  } catch (err) {
    showError(err, "No se pudo cargar la configuración");
    return;
  }
  const cfg = state.config;
  $("footer-version").textContent = `Claro CENAM Service Manager v${cfg.version} · datos: ${cfg.backend === "memory" ? "memoria (demo)" : "Firebase"}`;
  $("import-max-mb").textContent = cfg.max_upload_mb;

  const select = $("p-titulo");
  select.replaceChildren(...Object.entries(cfg.services).map(([name, tpl]) => new Option(tpl.label, name)));

  const d = cfg.network_defaults;
  $("m-raisecom").value = d.equipo_raisecom;
  $("s-equipo").value = d.equipo_cpe;
  $("eq-loopback").placeholder = `Asignada por el sistema (${d.loopback_pool_start} - ${d.loopback_pool_end} /32)`;

  renderCentralPresets();
  applyServiceTemplate(select.value);
}

function renderCentralPresets() {
  const container = $("centrales-presets");
  const centrales = state.config ? state.config.centrales : [];
  container.replaceChildren(...centrales.map(c =>
    el("button", { type: "button", class: "btn btn-sm btn-outline", title: c.demo ? "Datos de demostración" : c.isla, onclick: () => loadCentral(c.id) },
      c.nombre, c.demo ? " (demo)" : "")
  ));
}

function loadCentral(centralId) {
  const central = state.config.centrales.find(c => c.id === centralId);
  if (!central) return;
  $("equipment-tbody").replaceChildren();
  central.equipos.forEach(eq => addEquipmentRow(eq));
  markFormatStale();
}

function currentTemplate() {
  return state.config ? state.config.services[$("p-titulo").value] : null;
}

function applyServiceTemplate(typeName) {
  if (!state.config) return;
  const tpl = state.config.services[typeName];
  if (!tpl) return;
  // INTERNET habilita la IP pública; DATOS no la usa.
  const publica = $("eq-ip-publica");
  publica.disabled = !tpl.ip_publica;
  if (!tpl.ip_publica) publica.value = "";
  $("service-template-warning").hidden = !tpl.pendiente_validar;
  $("generar-title").textContent = `Formato Final de Alta de ${tpl.banner}`;
  fillVlanData();
}

function onServiceTypeChange(typeName) {
  const factArea = $("p-factibilidad-bloque");
  if (factArea.value) {
    const tpl = state.config && state.config.services[typeName];
    const title = tpl ? tpl.banner : typeName;
    factArea.value = factArea.value.replace(/TITULO:\s*\*\*\*[^*]+\*\*\*/i, `TITULO:\t***${title}***`);
  }
  applyServiceTemplate(typeName);
  markFormatStale();
}

// ===========================================================================
// Inventario de IPs (Firestore): Isla -> VLAN -> Segmento /24 -> Subred -> IP
// ===========================================================================
const NO_ISLA = "__sin_isla__";

function selectedIsla() {
  const value = $("eq-isla").value;
  return value === NO_ISLA ? "" : value;
}

async function loadInventory() {
  const badge = $("inventory-badge");
  try {
    const data = await api("/api/sheets");
    state.sheets = data.details || [];
    const totalFree = state.sheets.reduce((acc, s) => acc + (s.available_count || 0), 0);
    $("inventory-status").textContent = state.sheets.length
      ? `${state.sheets.length} segmento(s) · ${totalFree} IPs libres`
      : "Inventario vacío: importe un Excel";
    badge.classList.toggle("empty", !state.sheets.length);
    badge.classList.remove("error");
    await loadIslas();
  } catch (err) {
    badge.classList.add("error");
    $("inventory-status").textContent = "Error al conectar con Firebase";
    showError(err, "No se pudo cargar el inventario");
  }
}

async function loadIslas(preferred) {
  const data = await api("/api/islas");
  const select = $("eq-isla");
  const before = select.value;
  const current = preferred !== undefined ? preferred : before;
  const options = [new Option("Seleccione la isla / central", ""), ...data.islas.map(i => new Option(i, i))];
  if (data.has_unassigned) options.push(new Option("(Segmentos sin isla asignada)", NO_ISLA));
  select.replaceChildren(...options);
  $("islas-datalist").replaceChildren(...data.islas.map(i => el("option", { value: i })));
  if ([...select.options].some(o => o.value === current)) select.value = current;
  await onIslaChange({ keepSelection: select.value === before });
}

async function onIslaChange({ keepSelection = false } = {}) {
  const requestId = ++state.inventoryRequestId;
  const isla = $("eq-isla").value;
  const previousVlan = keepSelection ? state.currentVlan : "";
  state.islaSegments = [];
  state.vlanCatalog = [];
  if (!isla) {
    fillVlanSelect();
    clearIPAMSelection("Seleccione primero la isla");
    $("ipam-sheet-select").replaceChildren(new Option("Seleccione primero la isla", ""));
    updateGenerationAvailability();
    return;
  }
  if (!keepSelection) loadCentralForIsla(isla);
  try {
    const islaParam = encodeURIComponent(selectedIsla());
    const [segments, vlans] = await Promise.all([
      api(`/api/segments?isla=${islaParam}`),
      selectedIsla() ? api(`/api/vlans?isla=${islaParam}`) : Promise.resolve({ vlans: [] }),
    ]);
    if (requestId !== state.inventoryRequestId) return;
    state.islaSegments = segments.segments || [];
    state.vlanCatalog = vlans.vlans || [];
  } catch (err) {
    showError(err, "No se pudieron cargar los segmentos de la isla");
  }
  fillVlanSelect(previousVlan);
  await onVlanChange({ keepSelection });
}

function loadCentralForIsla(isla) {
  if (!state.config) return;
  const central = state.config.centrales.find(c => (c.isla || "").toUpperCase() === isla.toUpperCase());
  if (central) loadCentral(central.id);
}

function fillVlanSelect(preferred = "") {
  const select = $("eq-vlan-select");
  const free = {};
  for (const seg of state.islaSegments) {
    if (!seg.vlan) continue;
    free[seg.vlan] = (free[seg.vlan] || 0) + (seg.available_count || 0);
  }
  for (const v of state.vlanCatalog) if (!(v.vlan in free)) free[v.vlan] = null;
  const vlans = Object.keys(free).sort((a, b) => Number(a) - Number(b));
  const options = [new Option(state.islaSegments.length ? "Seleccione la VLAN" : "Sin segmentos en esta isla", "")];
  vlans.forEach(v => options.push(new Option(free[v] === null ? `VLAN ${v} (sin IPs cargadas)` : `VLAN ${v} — ${free[v]} libres`, v)));
  if (state.islaSegments.length) options.push(new Option("Todas las VLAN de la isla", "*"));
  select.replaceChildren(...options);
  select.value = [...select.options].some(o => o.value === preferred) ? preferred : "";
}

async function onVlanChange({ keepSelection = false } = {}) {
  state.currentVlan = $("eq-vlan-select").value;
  fillVlanData();
  const sheetSelect = $("ipam-sheet-select");
  if (!state.currentVlan) {
    sheetSelect.replaceChildren(new Option("Seleccione primero la VLAN", ""));
    clearIPAMSelection("Seleccione primero la VLAN");
    markFormatStale();
    return;
  }
  const segments = state.islaSegments.filter(s => state.currentVlan === "*" || s.vlan === state.currentVlan);
  const sheets = [...new Set(segments.map(s => s.sheet))];
  if (!sheets.length) {
    sheetSelect.replaceChildren(new Option("No hay segmentos con esta VLAN", ""));
    clearIPAMSelection("No hay IPs cargadas para esta VLAN");
    return;
  }
  const previous = keepSelection ? sheetSelect.value : "";
  sheetSelect.replaceChildren(...sheets.map(sheet => {
    const libres = segments.filter(s => s.sheet === sheet).reduce((acc, s) => acc + (s.available_count || 0), 0);
    return new Option(`${sheet} (${libres} libres)`, sheet);
  }));
  sheetSelect.value = sheets.includes(previous) ? previous : sheets[0];
  await loadBlocksForSheet(sheetSelect.value);
}

function vlanForData() {
  if (state.currentVlan && state.currentVlan !== "*") return state.currentVlan;
  return state.selectedBlock ? state.selectedBlock.vlan || "" : "";
}

// RD, VRF y descripciones: lo guardado para la VLAN; si no hay nada, la plantilla del servicio.
function fillVlanData() {
  const vlan = vlanForData();
  const saved = state.vlanCatalog.find(v => v.vlan === vlan);
  const tpl = currentTemplate();
  const values = saved
    ? { rd: saved.rd, vrf_name: saved.vrf_name, vrf_desc: saved.vrf_desc, vlan_desc: saved.vlan_desc }
    : { rd: tpl ? tpl.rd : "", vrf_name: tpl ? tpl.vrf_name : "", vrf_desc: tpl ? tpl.vrf_desc : "", vlan_desc: "" };
  $("eq-rd").value = values.rd || "";
  $("eq-vrf-name").value = values.vrf_name || "";
  $("eq-vrf-desc").value = values.vrf_desc || "";
  $("eq-desc-vlan").value = values.vlan_desc || "";
  $("vlan-data-status").textContent = !vlan ? "" : saved
    ? `Datos guardados de la VLAN ${vlan}${saved.updated_by ? ` (por ${saved.updated_by})` : ""}.`
    : `La VLAN ${vlan} aún no tiene datos guardados.`;
}

async function saveVlanData() {
  if (!ensureOperator()) return;
  const vlan = vlanForData();
  if (!vlan) {
    toast("Seleccione una VLAN antes de guardar sus datos.", "warning");
    return;
  }
  try {
    const r = await api("/api/vlans", { method: "PUT", json: {
      isla: selectedIsla(), vlan, rd: $("eq-rd").value.trim(), vrf_name: $("eq-vrf-name").value.trim(),
      vrf_desc: $("eq-vrf-desc").value.trim(), vlan_desc: $("eq-desc-vlan").value.trim(),
    } });
    state.vlanCatalog = [...state.vlanCatalog.filter(v => v.vlan !== vlan), r.vlan];
    fillVlanData();
    toast(r.message, "success", r.operation_id);
  } catch (err) {
    showError(err, "No se pudieron guardar los datos de la VLAN");
  }
}

function clearIPAMSelection(message = "Selecciona un segmento") {
  state.blocks = [];
  state.selectedBlock = null;
  state.selectedFreeIPs = [];
  $("ipam-block-select").replaceChildren(new Option(message));
  $("ipam-free-select").replaceChildren();
  $("assigned-tbody").replaceChildren();
  $("assigned-count").textContent = "0";
  for (const id of ["eq-red-wan", "eq-gw-wan", "eq-ip-wan", "eq-ips-adicionales"]) $(id).value = "";
}

async function loadBlocksForSheet(sheetName, preferredSegment) {
  const requestId = ++state.blocksRequestId;
  const previousSegment = preferredSegment || (state.selectedBlock && state.selectedBlock.segment_id);
  clearIPAMSelection("Cargando subredes...");
  if (!sheetName) return;
  try {
    const data = await api(`/api/blocks?sheet=${encodeURIComponent(sheetName)}`);
    if (requestId !== state.blocksRequestId) return;
    // La VLAN limita las subredes (y por lo tanto las IPs) que se ofrecen.
    state.blocks = (data.blocks || []).filter(b => !state.currentVlan || state.currentVlan === "*" || b.vlan === state.currentVlan);
    const blockSelect = $("ipam-block-select");
    if (!state.blocks.length) {
      clearIPAMSelection("No se detectaron subredes");
      return;
    }
    blockSelect.replaceChildren(...state.blocks.map((b, idx) => {
      const vlanText = b.vlan ? ` (VLAN ${b.vlan})` : "";
      return new Option(`${b.network_ip}${vlanText} — ${b.available_count} libres`, String(idx));
    }));
    let idx = state.blocks.findIndex(b => b.segment_id === previousSegment);
    if (idx < 0) idx = Math.max(0, state.blocks.findIndex(b => b.available_count > 0));
    blockSelect.value = String(idx);
    selectBlock(idx);
  } catch (err) {
    if (requestId === state.blocksRequestId) clearIPAMSelection("Error al cargar subredes");
    showError(err, "No se pudieron cargar las subredes");
  }
}

function onSheetSelected() {
  loadBlocksForSheet($("ipam-sheet-select").value);
}

function onBlockSelected() {
  selectBlock(parseInt($("ipam-block-select").value, 10));
}

function selectBlock(idx) {
  const block = state.blocks[idx];
  if (!block) {
    clearIPAMSelection();
    return;
  }
  state.selectedBlock = block;
  $("eq-red-wan").value = block.network_ip;
  $("eq-gw-wan").value = block.gateway_ip || "";
  if (state.currentVlan === "*") fillVlanData();

  const freeSelect = $("ipam-free-select");
  if (!block.available_ips.length) {
    freeSelect.replaceChildren(new Option("¡Subred llena (0 libres)!", ""));
    freeSelect.disabled = true;
  } else {
    freeSelect.disabled = false;
    freeSelect.replaceChildren(...block.available_ips.map(ipObj => new Option(`${ipObj.ip}  (octeto ${ipObj.octet})`, ipObj.ip)));
  }
  setSelectedFreeIPs(block.available_ips.length ? [block.available_ips[0].ip] : []);
  renderAssignedTable(block);
  markFormatStale();
}

function setSelectedFreeIPs(ips) {
  state.selectedFreeIPs = ips;
  const freeSelect = $("ipam-free-select");
  for (const option of freeSelect.options) option.selected = ips.includes(option.value);
  $("eq-ip-wan").value = ips[0] || "";
  $("eq-ips-adicionales").value = ips.slice(1).join(", ");
}

function onFreeIPSelected() {
  const selected = Array.from($("ipam-free-select").selectedOptions).map(o => o.value).filter(Boolean);
  setSelectedFreeIPs(selected);
  markFormatStale();
}

function assignFirstFreeIP() {
  const block = state.selectedBlock;
  if (!block || !block.available_ips.length) {
    toast("No hay IPs libres en esta subred.", "warning");
    return;
  }
  setSelectedFreeIPs([block.available_ips[0].ip]);
  toast(`Seleccionada: ${state.selectedFreeIPs[0]}. Pulse “Reservar” para confirmarla.`, "info");
}

function renderAssignedTable(block) {
  const rows = block.assigned_ips.map(item => el("tr", {},
    el("td", { class: "mono" }, item.ip),
    el("td", {}, item.id || ""),
    el("td", {}, item.assigned_by || ""),
    el("td", {}, formatDate(item.assigned_at)),
    el("td", {}, el("button", { type: "button", class: "btn-danger-sm", onclick: () => openReleaseModal(item) }, "Liberar"))
  ));
  $("assigned-tbody").replaceChildren(...rows);
  $("assigned-count").textContent = String(block.assigned_ips.length);
}

// Recarga contadores e IPs manteniendo isla, VLAN, segmento y subred seleccionados.
async function refreshInventorySelection() {
  const sheet = $("ipam-sheet-select").value;
  const segment = state.selectedBlock && state.selectedBlock.segment_id;
  await loadInventory();
  if (sheet && [...$("ipam-sheet-select").options].some(o => o.value === sheet)) {
    $("ipam-sheet-select").value = sheet;
    await loadBlocksForSheet(sheet, segment);
  }
}

async function confirmIPReservation() {
  if (!ensureOperator()) return;
  const block = state.selectedBlock;
  const ips = state.selectedFreeIPs;
  if (!block || !ips.length) {
    toast("Seleccione al menos una IP libre.", "warning");
    return;
  }
  const serviceId = $("p-id-servicio").value.trim();
  if (!serviceId) {
    toast("Ingrese el ID del Servicio en la pestaña Principal antes de reservar.", "warning");
    activateTab("tab-principal");
    $("p-id-servicio").focus();
    return;
  }
  const ok = await confirmDialog(
    `Se reservarán ${ips.length} IP(s) para el servicio “${serviceId}”:\n${ips.join(", ")}\n\nLa primera será la IP WAN.`,
    { title: "Reservar IPs", accept: "Reservar" });
  if (!ok) return;

  const button = $("btn-reserve-ip");
  button.disabled = true;
  try {
    const result = await api("/api/reservations", { method: "POST", json: { ips, service_id: serviceId, purpose: "WAN" } });
    ips.forEach(ip => state.reservedForService.set(ip, serviceId));
    toast(result.message, "success", result.operation_id);
    await refreshInventorySelection();
    // conservar la selección reservada en el formulario
    $("eq-ip-wan").value = ips[0];
    $("eq-ips-adicionales").value = ips.slice(1).join(", ");
    $("eq-red-wan").value = block.network_ip;
    $("eq-gw-wan").value = block.gateway_ip || "";
    state.selectedFreeIPs = [];
    for (const option of $("ipam-free-select").options) option.selected = false;
  } catch (err) {
    showError(err, "No se pudo reservar");
    if (err.status === 409) loadBlocksForSheet(block.sheet_name, block.segment_id);
  } finally {
    button.disabled = false;
  }
}

function openReleaseModal(item) {
  if (!ensureOperator()) return;
  state.releaseTarget = item;
  $("release-summary").textContent = `IP ${item.ip} — servicio ${item.id}. Quedará disponible para otros servicios.`;
  $("release-reason").value = "";
  openModal("release-modal");
}

async function submitRelease(event) {
  event.preventDefault();
  const item = state.releaseTarget;
  if (!item) return;
  try {
    const result = await api("/api/reservations/release", {
      method: "POST",
      json: { ips: [item.ip], service_id: item.id, reason: $("release-reason").value.trim() },
    });
    closeModal("release-modal");
    state.reservedForService.delete(item.ip);
    toast(result.message, "success", result.operation_id);
    await refreshInventorySelection();
  } catch (err) {
    showError(err, "No se pudo liberar");
  }
}

// --- Isla de un segmento ----------------------------------------------------
function openAssignIslaModal() {
  if (!ensureOperator()) return;
  const sheet = $("ipam-sheet-select").value;
  if (!sheet) {
    toast("Seleccione un segmento /24.", "warning");
    return;
  }
  $("isla-modal-summary").textContent = `Segmento ${sheet}: sus subredes aparecerán al elegir esta isla.`;
  $("isla-modal-input").value = selectedIsla();
  openModal("isla-modal");
}

async function submitAssignIsla(event) {
  event.preventDefault();
  const sheet = $("ipam-sheet-select").value;
  try {
    const r = await api(`/api/sheets/${encodeURIComponent(sheet)}/isla`, { method: "PUT", json: { isla: $("isla-modal-input").value.trim() } });
    closeModal("isla-modal");
    toast(r.message, "success", r.operation_id);
    await loadIslas(r.isla);
  } catch (err) {
    showError(err, "No se pudo asignar la isla");
  }
}

// --- Loopback automática ----------------------------------------------------
function onLoopbackToggle() {
  return refreshLoopback(true);
}

async function refreshLoopback(markStale) {
  const input = $("eq-loopback");
  if (!$("eq-loopback-auto").checked) {
    input.value = "";
    if (markStale) markFormatStale();
    return;
  }
  try {
    const serviceId = $("p-id-servicio").value.trim();
    const r = await api(`/api/loopbacks/next?service_id=${encodeURIComponent(serviceId)}`);
    input.value = r.cidr;
    input.title = r.assigned ? "Loopback ya asignada a este servicio" : "Se reserva al registrar el alta";
  } catch (err) {
    input.value = "";
    showError(err, "No se pudo obtener la loopback");
  }
  if (markStale) markFormatStale();
}

// --- Importar / exportar ---------------------------------------------------
function initImportModal() {
  document.querySelectorAll('input[name="import-mode"]').forEach(radio => {
    radio.addEventListener("change", () => {
      const replace = document.querySelector('input[name="import-mode"]:checked').value === "replace";
      $("import-confirm-line").hidden = !replace;
      $("import-confirm").required = replace;
    });
  });
}

function openImportModal() {
  if (!ensureOperator()) return;
  $("import-result").replaceChildren();
  $("import-file").value = "";
  openModal("import-modal");
}

async function submitImport(event) {
  event.preventDefault();
  const file = $("import-file").files[0];
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".xlsx")) {
    toast("Seleccione un archivo .xlsx.", "warning");
    return;
  }
  const mode = document.querySelector('input[name="import-mode"]:checked').value;
  const formData = new FormData();
  formData.append("file", file);
  formData.append("mode", mode);
  formData.append("confirm_replace", String($("import-confirm").checked));
  formData.append("isla", $("import-isla").value.trim());

  const button = $("btn-submit-import");
  button.disabled = true;
  button.textContent = "Importando...";
  const resultBox = $("import-result");
  resultBox.replaceChildren(el("p", {}, "Procesando el archivo y cargando a Firebase..."));
  try {
    const r = await api("/api/inventory/import", { method: "POST", formData });
    resultBox.replaceChildren(
      el("p", { class: "result-ok" }, `✅ ${r.message}`),
      el("ul", {},
        el("li", {}, `Importación: `, el("span", { class: "mono" }, r.import_id), ` · modo ${r.mode}`),
        el("li", {}, `Hojas: ${r.sheets.join(", ")}`),
        r.ignored_sheets.length ? el("li", {}, `Hojas ignoradas (nombre no es una red): ${r.ignored_sheets.join(", ")}`) : null,
        el("li", {}, `Subredes: ${r.segments} · IPs escritas: ${r.ips_written} · sin cambios: ${r.ips_unchanged} · eliminadas: ${r.ips_deleted}`),
        el("li", {}, `Totales: ${r.totals.disponibles} libres, ${r.totals.ocupadas} ocupadas, ${r.totals.gateways} gateways`),
        el("li", {}, `ID de operación: `, el("span", { class: "mono" }, r.operation_id)),
      ),
      r.conflicts_count ? el("details", { open: true },
        el("summary", {}, `⚠ ${r.conflicts_count} conflicto(s): se conservó el valor de Firebase`),
        el("ul", { class: "conflicts" }, ...r.conflicts.slice(0, 50).map(c =>
          el("li", { class: "mono" }, `${c.ip}: Firebase=${c.firestore} · Excel=${c.excel}`)))
      ) : null,
    );
    toast("Inventario importado a Firebase.", "success", r.operation_id);
    await loadInventory();
  } catch (err) {
    resultBox.replaceChildren(el("p", { class: "result-error" }, `❌ ${err.message}`),
      err.operationId ? el("p", {}, "ID de operación: ", el("span", { class: "mono" }, err.operationId)) : null);
    showError(err, "Error al importar");
  } finally {
    button.disabled = false;
    button.textContent = "Importar";
  }
}

async function exportInventory() {
  try {
    const { response, operationId } = await api("/api/inventory/export", { raw: true });
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    downloadBlob(blob, match ? match[1] : "inventario_ips.xlsx");
    setLastOperation(operationId);
    toast("Inventario exportado.", "success", operationId);
  } catch (err) {
    showError(err, "No se pudo exportar");
  }
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ===========================================================================
// Equipos extremo Claro
// ===========================================================================
function getEquipmentRowsData() {
  return Array.from($("equipment-tbody").querySelectorAll("tr")).map(tr => {
    const v = Array.from(tr.querySelectorAll("input")).map(i => i.value.trim());
    return { no: v[0], rol: v[1], marca: v[2], modelo: v[3], hostname: v[4], ip_admon: v[5] };
  });
}

function addEquipmentRow(data = {}) {
  const tbody = $("equipment-tbody");
  const headers = document.querySelectorAll("#equipment-table th");
  const values = [data.no || tbody.querySelectorAll("tr").length + 1, data.rol || "", data.marca || "", data.modelo || "",
    data.hostname || "", data.ip_admon || ""];
  const tr = el("tr", {}, ...values.map((value, index) =>
    el("td", {}, el("input", { type: "text", value: String(value), "aria-label": headers[index].textContent.trim() }))));
  tr.appendChild(el("td", { class: "center" },
    el("button", { type: "button", class: "btn-danger-sm", onclick: () => { tr.remove(); markFormatStale(); } }, "Eliminar")));
  tbody.appendChild(tr);
}

// ===========================================================================
// Factibilidad (F2)
// ===========================================================================
function handleQuickPaste(e) {
  e.preventDefault();
  const pasteData = (e.clipboardData || window.clipboardData).getData("text");
  if (!pasteData || !pasteData.trim()) return;
  $("p-factibilidad-bloque").value = pasteData;
  state.sinFactibilidad = false;
  updateFactibilidadBadge();
  const titleMatch = pasteData.match(/TITULO:\s*\*\*\*([^*]+)\*\*\*/i);
  if (titleMatch) {
    const detected = titleMatch[1].trim().toUpperCase();
    const select = $("p-titulo");
    for (const opt of select.options) {
      if (detected.includes(opt.value.toUpperCase()) || detected.includes(opt.text.toUpperCase())) {
        if (select.value !== opt.value) {
          select.value = opt.value;
          applyServiceTemplate(opt.value);
        }
        break;
      }
    }
  }
  const quickInput = $("p-factibilidad-quick-paste");
  quickInput.value = "";
  quickInput.placeholder = "✅ Factibilidad cargada. Presiona F2 para ver o editar.";
  markFormatStale();
}

function toggleSinFactibilidad() {
  if ($("p-factibilidad-bloque").value.trim()) {
    toast("Ya hay una factibilidad cargada. Bórrela desde «Ver / Editar (F2)» si el servicio no la tiene.", "warning");
    return;
  }
  state.sinFactibilidad = !state.sinFactibilidad;
  updateFactibilidadBadge();
  markFormatStale();
  if (state.sinFactibilidad) toast("Continuando sin factibilidad.", "info");
}

function updateFactibilidadBadge() {
  const loaded = $("p-factibilidad-bloque").value.trim().length > 0;
  if (loaded) state.sinFactibilidad = false;
  const badge = $("factibilidad-status-badge");
  const [cls, icon, text] = loaded ? ["loaded", "✅", "Factibilidad cargada"]
    : state.sinFactibilidad ? ["skipped", "🚫", "Sin factibilidad"]
    : ["empty", "⚪", "Factibilidad pendiente"];
  badge.className = `fact-badge ${cls}`;
  badge.replaceChildren(el("span", { class: "badge-icon" }, icon), el("span", { class: "badge-text" }, text));
  const button = $("btn-sin-factibilidad");
  button.setAttribute("aria-pressed", String(state.sinFactibilidad));
  button.classList.toggle("active", state.sinFactibilidad);
  button.disabled = loaded;
  $("factibilidad-gate-hint").hidden = factibilidadResuelta();
  updateGenerationAvailability();
}

function openFactibilidadModal() {
  const text = $("p-factibilidad-bloque").value;
  $("modal-factibilidad-textarea").value = text;
  $("modal-factibilidad-info").textContent = text.trim()
    ? `${text.trim().length} caracteres cargados`
    : "Aún no hay factibilidad cargada: pegue el texto aquí.";
  openModal("factibilidad-modal");
  $("modal-factibilidad-textarea").focus();
}

function saveFactibilidadModal() {
  $("p-factibilidad-bloque").value = $("modal-factibilidad-textarea").value;
  updateFactibilidadBadge();
  closeModal("factibilidad-modal");
  markFormatStale();
}

function initDateField() {
  const today = new Date();
  $("p-fecha").value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
}

// ===========================================================================
// Validación y generación del formato
// ===========================================================================
function getMissingRequiredFields() {
  return Array.from(document.querySelectorAll(".tab-content input[required], .tab-content select[required], .tab-content textarea[required]"))
    .filter(control => !control.disabled && !control.checkValidity());
}

function updateGenerationAvailability() {
  const missing = getMissingRequiredFields();
  const canGenerate = missing.length === 0;
  const generateTab = document.querySelector('[data-tab="tab-generar"]');
  const status = $("generation-requirements-status");
  const resuelta = factibilidadResuelta();
  document.querySelectorAll(".tab-btn").forEach(btn => {
    if (isGatedTab(btn.dataset.tab)) btn.classList.toggle("locked", !resuelta);
  });
  generateTab.disabled = !canGenerate || !resuelta;
  generateTab.setAttribute("aria-disabled", String(!canGenerate));
  $("btn-update-format").disabled = !canGenerate;
  $("btn-register-alta").disabled = !canGenerate;
  if (!resuelta) {
    status.textContent = "Cargue la factibilidad o pulse «Sin factibilidad» para continuar.";
    status.className = "generation-status pending";
  } else if (canGenerate) {
    status.textContent = "Todos los campos requeridos están completos.";
    status.className = "generation-status ready";
  } else {
    const labels = missing.map(control => {
      const label = document.querySelector(`label[for="${control.id}"]`);
      return label ? label.textContent.trim().replace(/:$/, "") : control.id;
    });
    status.textContent = `Completa ${missing.length} campo(s) requerido(s): ${labels.join(", ")}`;
    status.className = "generation-status pending";
  }
}

function markFormatStale() {
  if (!state.registeredAlta) return;
  state.registeredAlta = null;
  $("btn-copy-format").disabled = true;
  $("btn-download-format").disabled = true;
  const status = $("alta-status");
  status.hidden = false;
  status.className = "alta-status stale";
  status.textContent = "Hay cambios sin registrar. Pulse “Registrar alta” para guardar la nueva versión antes de copiarla.";
}

function collectFormData() {
  let fecha = $("p-fecha").value;
  const p = fecha.split("-");
  if (p.length === 3 && p[0].length === 4) fecha = `${p[2]}-${p[1]}-${p[0]}`;
  const tpl = currentTemplate();
  return {
    titulo: $("p-titulo").value,
    id_servicio: $("p-id-servicio").value.trim(),
    cliente: $("p-cliente").value.trim(),
    disenador: $("p-disenador").value,
    tel_disenador: $("p-tel-disenador").value,
    fecha,
    factibilidad_bloque: $("p-factibilidad-bloque").value,
    sin_factibilidad: state.sinFactibilidad,
    medio: $("s-medio").value,
    equipo_cpe: $("s-equipo").value,
    observaciones: $("s-observaciones").value,
    isla: selectedIsla(),
    vlan_num: vlanForData(),
    red_wan: $("eq-red-wan").value,
    gw_wan: $("eq-gw-wan").value,
    ip_wan: $("eq-ip-wan").value,
    ips_adicionales: $("eq-ips-adicionales").value.split(",").map(s => s.trim()).filter(Boolean),
    rd: $("eq-rd").value.trim(),
    vrf_name: $("eq-vrf-name").value.trim(),
    vrf_desc: $("eq-vrf-desc").value.trim(),
    desc_vlan: $("eq-desc-vlan").value.trim(),
    ip_publica: tpl && tpl.ip_publica ? $("eq-ip-publica").value.trim() : "",
    loopback_auto: $("eq-loopback-auto").checked,
    equipos_claro: getEquipmentRowsData(),
    equipo_raisecom: $("m-raisecom").value,
    obs_medio: $("m-obs-medio").value,
  };
}

function focusFirstMissing() {
  const missing = getMissingRequiredFields();
  if (!missing.length) return false;
  updateGenerationAvailability();
  const tab = missing[0].closest(".tab-content");
  if (tab) activateTab(tab.id);
  missing[0].reportValidity();
  missing[0].focus();
  return true;
}

async function updateGeneratedFormat() {
  if (focusFirstMissing()) return;
  const requestId = ++state.formatRequestId;
  const output = $("output-format-textarea");
  try {
    const data = await api("/api/generate-format", { method: "POST", json: { data: collectFormData() } });
    if (requestId !== state.formatRequestId) return;
    output.value = data.formatted_text;
    state.registeredAlta = null;
    $("btn-copy-format").disabled = true;
    $("btn-download-format").disabled = true;
    const status = $("alta-status");
    status.hidden = false;
    status.className = "alta-status preview";
    status.textContent = "Vista previa (aún no registrada). Pulse “Registrar alta” para guardarla en Firebase y habilitar copiar/descargar.";
  } catch (err) {
    showError(err, "No se pudo generar la vista previa");
  }
}

function wanIsReserved(data) {
  if (!data.ip_wan) return true;
  if (state.reservedForService.get(data.ip_wan) === data.id_servicio) return true;
  const block = state.blocks.find(b => b.assigned_ips.some(a => a.ip === data.ip_wan));
  return Boolean(block && block.assigned_ips.find(a => a.ip === data.ip_wan).id === data.id_servicio);
}

async function registerAlta() {
  if (!ensureOperator()) return;
  if (focusFirstMissing()) return;
  let data;
  try {
    data = collectFormData();
  } catch (err) {
    showError(err);
    return;
  }
  if (!wanIsReserved(data)) {
    const ok = await confirmDialog(
      `La IP WAN ${data.ip_wan} no figura reservada para el servicio “${data.id_servicio}”.\n¿Desea registrar el alta de todas formas?`,
      { title: "IP sin reservar", accept: "Registrar igual" });
    if (!ok) return;
  }
  const button = $("btn-register-alta");
  button.disabled = true;
  try {
    const result = await api("/api/altas", { method: "POST", json: { data } });
    $("output-format-textarea").value = result.formatted_text;
    if (data.loopback_auto) refreshLoopback(false);
    state.registeredAlta = { alta_id: result.alta_id, text: result.formatted_text, service: data.id_servicio };
    $("btn-copy-format").disabled = false;
    $("btn-download-format").disabled = false;
    const status = $("alta-status");
    status.hidden = false;
    status.className = "alta-status registered";
    status.replaceChildren(
      result.duplicate ? "Esta alta ya estaba registrada: " : "✅ Alta registrada: ",
      el("strong", { class: "mono" }, result.alta_id),
      " · operación ",
      el("button", { type: "button", class: "link-btn mono", onclick: () => copyText(result.operation_id, "ID copiado") }, result.operation_id));
    toast(result.duplicate ? "El alta ya existía; no se duplicó." : `Alta ${result.alta_id} registrada en Firebase.`, "success", result.operation_id);
  } catch (err) {
    showError(err, "No se pudo registrar el alta");
  } finally {
    updateGenerationAvailability();
  }
}

function copyFormatToClipboard() {
  if (!state.registeredAlta) {
    toast("Registre el alta antes de copiarla.", "warning");
    return;
  }
  copyText(state.registeredAlta.text, "¡Formato copiado al portapapeles!");
}

function downloadFormatTxt() {
  if (!state.registeredAlta) {
    toast("Registre el alta antes de descargarla.", "warning");
    return;
  }
  const safeId = state.registeredAlta.service.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80) || "ALTA";
  downloadBlob(new Blob([state.registeredAlta.text], { type: "text/plain;charset=utf-8" }),
    `Alta_${safeId}_${state.registeredAlta.alta_id}.txt`);
}

// ===========================================================================
// Consultas
// ===========================================================================
async function searchService(event) {
  event.preventDefault();
  const serviceId = $("search-service-id").value.trim();
  const box = $("search-results");
  if (!serviceId) return;
  box.replaceChildren(el("p", {}, "Buscando..."));
  try {
    const r = await api(`/api/services/${encodeURIComponent(serviceId)}`);
    box.replaceChildren(
      el("h4", {}, `IPs asignadas (${r.ips.length})`),
      r.ips.length ? el("ul", {}, ...r.ips.map(ip => el("li", {},
        el("span", { class: "mono" }, ip.ip), ` · ${ip.purpose || ""} · subred ${ip.segment_id.replace("_", "/")} · por ${ip.assigned_by || "—"} (${formatDate(ip.assigned_at)})`))) : el("p", { class: "hint" }, "Sin IPs asignadas."),
      el("h4", {}, `Altas registradas (${r.altas.length})`),
      r.altas.length ? el("ul", {}, ...r.altas.map(a => el("li", {},
        el("button", { type: "button", class: "link-btn mono", onclick: () => showAlta(a.alta_id) }, a.alta_id),
        ` · ${formatDate(a.created_at)} · ${a.operator || ""}`))) : el("p", { class: "hint" }, "Sin altas registradas."),
    );
  } catch (err) {
    box.replaceChildren(el("p", { class: "result-error" }, err.message));
  }
}

async function lookupOperation(event) {
  event.preventDefault();
  const opId = $("search-operation-id").value.trim().toUpperCase();
  const box = $("operation-result");
  if (!opId) return;
  try {
    const r = await api(`/api/operations/${encodeURIComponent(opId)}`);
    const rows = [
      ["Acción", r.action], ["Resultado", `${r.outcome} (HTTP ${r.status_code})`], ["Operador", r.operator || "—"],
      ["Fecha", formatDate(r.created_at)], ["Duración", `${r.duration_ms} ms`], ["Servicio", r.service_id || "—"],
      ["Error", r.error || "—"], ["Ruta", `${r.method} ${r.path}`],
    ];
    box.replaceChildren(
      el("table", { class: "kv-table" }, ...rows.map(([k, v]) => el("tr", {}, el("th", {}, k), el("td", {}, String(v))))),
      el("details", {}, el("summary", {}, "Detalles técnicos"), el("pre", { class: "mono" }, JSON.stringify(r.details || {}, null, 2))),
    );
  } catch (err) {
    box.replaceChildren(el("p", { class: "result-error" }, err.message));
  }
}

async function loadAltasHistory() {
  try {
    const r = await api("/api/altas?limit=30");
    $("altas-tbody").replaceChildren(...(r.altas.length ? r.altas.map(a => el("tr", {},
      el("td", { class: "mono" }, a.alta_id),
      el("td", {}, formatDate(a.created_at)),
      el("td", {}, a.service_id || ""),
      el("td", {}, a.cliente || ""),
      el("td", {}, a.tipo_servicio || ""),
      el("td", { class: "mono" }, a.ip_wan || ""),
      el("td", {}, a.operator || ""),
      el("td", {}, el("button", { type: "button", class: "btn btn-sm btn-outline", onclick: () => showAlta(a.alta_id) }, "Ver")),
    )) : [el("tr", {}, el("td", { colspan: "8", class: "hint center" }, "Aún no hay altas registradas."))]));
  } catch (err) {
    showError(err, "No se pudo cargar el historial");
  }
}

async function showAlta(altaId) {
  try {
    const a = await api(`/api/altas/${encodeURIComponent(altaId)}`);
    $("alta-modal-title").textContent = `Alta ${a.alta_id}`;
    $("alta-modal-meta").textContent = `${a.service_id} · ${a.cliente} · ${formatDate(a.created_at)} · ${a.operator} · operación ${a.operation_id}`;
    $("alta-modal-text").value = a.formatted_text;
    openModal("alta-modal");
  } catch (err) {
    showError(err, "No se pudo abrir el alta");
  }
}
