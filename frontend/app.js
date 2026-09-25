// State variables
let currentBlocks = [];
let currentSelectedBlock = null;
let currentSelectedFreeIP = null;
let blocksRequestId = 0;
let formatRequestId = 0;

document.addEventListener("DOMContentLoaded", () => {
  initAccessibility();
  initTabs();
  initEquipmentTable();
  initExcelUpload();
  loadInitialData();
  initFactibilidad();
  initDateField();
  updateGenerationAvailability();
  document.body.addEventListener("input", event => {
    if (event.target.id !== "output-format-textarea") {
      markFormatStale();
      updateGenerationAvailability();
    }
  });
  document.body.addEventListener("change", updateGenerationAvailability);
});

function initAccessibility() {
  const tabList = document.querySelector(".tabs-nav");
  tabList.setAttribute("role", "tablist");
  document.querySelectorAll(".tab-btn").forEach(button => {
    const panelId = button.dataset.tab;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", panelId);
    button.setAttribute("aria-selected", String(button.classList.contains("active")));
    const panel = document.getElementById(panelId);
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", button.id || `${panelId}-button`);
    if (!button.id) button.id = `${panelId}-button`;
  });

  document.querySelectorAll(".form-group, .ipam-field").forEach(group => {
    const label = group.querySelector("label");
    const control = group.querySelector("input, select, textarea");
    if (!label || !control) return;
    if (!control.id) control.id = `field-${crypto.randomUUID()}`;
    label.htmlFor = control.id;
  });
}

async function getApiError(response, fallback) {
  try {
    const data = await response.json();
    return data.detail || fallback;
  } catch {
    return fallback;
  }
}

function clearIPAMSelection(message = "Selecciona un segmento") {
  currentBlocks = [];
  currentSelectedBlock = null;
  currentSelectedFreeIP = null;
  document.getElementById("ipam-block-select").replaceChildren(new Option(message));
  document.getElementById("ipam-free-select").replaceChildren(new Option("Sin IP seleccionada"));
  document.getElementById("eq-red-wan").value = "";
  document.getElementById("eq-gw-wan").value = "";
  document.getElementById("eq-ip-wan").value = "";
  document.getElementById("eq-vlan-num").value = "";
}

function markFormatStale() {
  const output = document.getElementById("output-format-textarea");
  if (output && output.value) output.dataset.stale = "true";
}

function getMissingRequiredFields() {
  return Array.from(document.querySelectorAll("input[required], select[required], textarea[required]"))
    .filter(control => !control.disabled && !control.checkValidity());
}

function updateGenerationAvailability() {
  const missingFields = getMissingRequiredFields();
  const canGenerate = missingFields.length === 0;
  const generateTab = document.querySelector('[data-tab="tab-generar"]');
  const previewButton = document.getElementById("btn-update-format");
  const status = document.getElementById("generation-requirements-status");

  generateTab.disabled = !canGenerate;
  generateTab.setAttribute("aria-disabled", String(!canGenerate));
  previewButton.disabled = !canGenerate;

  if (canGenerate) {
    generateTab.title = "Generar formato con los datos actuales del cliente";
    status.textContent = "Todos los campos requeridos están completos.";
    status.className = "generation-status ready";
  } else {
    const labels = missingFields.map(control => {
      const label = document.querySelector(`label[for="${control.id}"]`);
      return label ? label.textContent.trim().replace(/:$/, "") : control.name || control.id;
    });
    const message = `Completa ${missingFields.length} campo(s) requerido(s): ${labels.join(", ")}`;
    generateTab.title = message;
    status.textContent = message;
    status.className = "generation-status pending";
  }
}

// Tab switching logic
function initTabs() {
  const tabBtns = document.querySelectorAll(".tab-btn");
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      tabBtns.forEach(b => b.classList.remove("active"));
      tabBtns.forEach(b => b.setAttribute("aria-selected", "false"));
      document.querySelectorAll(".tab-content").forEach(tc => tc.classList.remove("active"));
      
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      const targetTabId = btn.getAttribute("data-tab");
      const targetContent = document.getElementById(targetTabId);
      if (targetContent) {
        targetContent.classList.add("active");
      }
      
      // Auto-update format if switching to generate tab
      if (targetTabId === "tab-generar") {
        updateGeneratedFormat();
      }
    });
  });
}

// Initial Data Load
async function loadInitialData() {
  try {
    const res = await fetch("/api/sheets");
    if (!res.ok) throw new Error("Error al obtener hojas de cálculo");
    const data = await res.json();
    
    document.getElementById("excel-filename").textContent = data.current_file || "Inventario Activo";
    
    const sheetSelect = document.getElementById("ipam-sheet-select");
    sheetSelect.innerHTML = "";
    data.sheets.forEach(sheet => {
      const opt = document.createElement("option");
      opt.value = sheet;
      opt.textContent = sheet;
      sheetSelect.appendChild(opt);
    });
    
    if (data.sheets.length > 0) {
      await loadBlocksForSheet(data.sheets[0]);
    }
  } catch (err) {
    console.error(err);
    document.getElementById("excel-filename").textContent = "Error al conectar con servidor";
  }
}

// Load blocks for selected sheet
async function loadBlocksForSheet(sheetName) {
  const requestId = ++blocksRequestId;
  clearIPAMSelection("Cargando subredes...");
  try {
    const res = await fetch(`/api/blocks?sheet=${encodeURIComponent(sheetName)}`);
    if (!res.ok) throw new Error("Error al cargar subredes");
    const data = await res.json();
    if (requestId !== blocksRequestId) return;
    currentBlocks = data.blocks || [];
    
    const blockSelect = document.getElementById("ipam-block-select");
    blockSelect.innerHTML = "";
    
    if (currentBlocks.length === 0) {
      const opt = document.createElement("option");
      opt.textContent = "No se detectaron subredes";
      blockSelect.appendChild(opt);
      clearIPAMSelection("No se detectaron subredes");
      return;
    }
    
    currentBlocks.forEach((b, idx) => {
      const opt = document.createElement("option");
      opt.value = idx;
      const vlanText = b.vlan ? `(VLAN ${b.vlan})` : "";
      opt.textContent = `${b.network_ip} ${vlanText} - [${b.available_count} libres]`;
      blockSelect.appendChild(opt);
    });
    
    selectBlock(0);
  } catch (err) {
    console.error(err);
    if (requestId === blocksRequestId) clearIPAMSelection("Error al cargar subredes");
    throw err;
  }
}

function onSheetSelected() {
  const sheetName = document.getElementById("ipam-sheet-select").value;
  loadBlocksForSheet(sheetName);
}

function onBlockSelected() {
  const idx = parseInt(document.getElementById("ipam-block-select").value, 10);
  selectBlock(idx);
}

function selectBlock(idx) {
  if (!currentBlocks[idx]) {
    clearIPAMSelection();
    return;
  }
  const b = currentBlocks[idx];
  currentSelectedBlock = b;
  
  // Populate Equipamiento fields
  document.getElementById("eq-red-wan").value = b.network_ip;
  document.getElementById("eq-gw-wan").value = b.gateway_ip || "";
  document.getElementById("eq-vlan-num").value = b.vlan || "";
  
  // Populate Free IPs dropdown
  const freeSelect = document.getElementById("ipam-free-select");
  freeSelect.innerHTML = "";
  
  if (b.available_ips.length === 0) {
    const opt = document.createElement("option");
    opt.textContent = "¡Subred LLENA (0 libres)!";
    freeSelect.appendChild(opt);
    currentSelectedFreeIP = null;
    document.getElementById("eq-ip-wan").value = "";
  } else {
    b.available_ips.forEach((ipObj, ipIdx) => {
      const opt = document.createElement("option");
      opt.value = ipIdx;
      opt.textContent = `${ipObj.ip} (Octeto ${ipObj.octet})`;
      freeSelect.appendChild(opt);
    });
    currentSelectedFreeIP = b.available_ips[0];
    document.getElementById("eq-ip-wan").value = b.available_ips[0].ip;
  }
}

function onFreeIPSelected() {
  if (!currentSelectedBlock || !currentSelectedBlock.available_ips) return;
  const ipIdx = parseInt(document.getElementById("ipam-free-select").value, 10);
  const chosen = currentSelectedBlock.available_ips[ipIdx];
  if (chosen) {
    currentSelectedFreeIP = chosen;
    document.getElementById("eq-ip-wan").value = chosen.ip;
  }
}

function assignFirstFreeIP() {
  if (!currentSelectedBlock || !currentSelectedBlock.available_ips.length) {
    alert("No hay IPs libres disponibles en este segmento.");
    return;
  }
  const first = currentSelectedBlock.available_ips[0];
  document.getElementById("ipam-free-select").value = 0;
  currentSelectedFreeIP = first;
  document.getElementById("eq-ip-wan").value = first.ip;
  alert(`✅ Se asignó la primera IP libre: ${first.ip}`);
}

async function confirmIPReservation() {
  if (!currentSelectedBlock || !currentSelectedFreeIP) {
    alert("Por favor selecciona una IP libre primero.");
    return;
  }
  const clientId = document.getElementById("p-id-servicio").value.trim();
  if (!clientId) {
    alert("Debes ingresar el 'ID del Servicio' en la pestaña Principal antes de reservar la IP.");
    return;
  }
  
  const selectedIP = currentSelectedFreeIP.ip;
  const selectedSheet = currentSelectedBlock.sheet_name;
  if (document.getElementById("eq-ip-wan").value.trim() !== selectedIP) {
    alert("La IP WAN fue editada manualmente. Vuelve a seleccionarla desde el inventario antes de reservar.");
    return;
  }
  const ok = confirm(`¿Deseas reservar la IP ${selectedIP} en el Excel para el ID de servicio '${clientId}'?`);
  if (!ok) return;

  const reserveButton = document.getElementById("btn-reserve-ip");
  reserveButton.disabled = true;
  try {
    const res = await fetch("/api/assign-ip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sheet_name: selectedSheet,
        ip: selectedIP,
        client_id: clientId
      })
    });
    
    if (!res.ok) {
      throw new Error(await getApiError(res, "Error al asignar IP en Excel"));
    }
    
    alert(`IP ${selectedIP} reservada con éxito para ${clientId}.`);
    // Reload sheet to refresh available counts
    await loadBlocksForSheet(selectedSheet);
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    reserveButton.disabled = false;
  }
}

// Excel Upload Handler
function initExcelUpload() {
  const fileInput = document.getElementById("excel-file-input");
  fileInput.addEventListener("change", async (e) => {
    if (!e.target.files.length) return;
    const file = e.target.files[0];
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      alert("Selecciona un archivo Excel con extensión .xlsx.");
      e.target.value = "";
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    
    document.getElementById("excel-filename").textContent = `Cargando ${file.name}...`;
    
    try {
      const res = await fetch("/api/upload-excel", {
        method: "POST",
        body: formData
      });
      
      if (!res.ok) throw new Error(await getApiError(res, "Error al subir archivo"));
      const data = await res.json();
      
      document.getElementById("excel-filename").textContent = data.filename;
      
      const sheetSelect = document.getElementById("ipam-sheet-select");
      sheetSelect.innerHTML = "";
      data.sheets.forEach(sheet => {
        const opt = document.createElement("option");
        opt.value = sheet;
        opt.textContent = sheet;
        sheetSelect.appendChild(opt);
      });
      
      if (data.sheets.length > 0) {
        await loadBlocksForSheet(data.sheets[0]);
      }
      alert(`Archivo Excel '${file.name}' cargado con éxito.`);
    } catch (err) {
      console.error(err);
      alert(`Error al cargar Excel: ${err.message}`);
      document.getElementById("excel-filename").textContent = "Error de archivo";
    }
  });
}

// Equipment Table management
function initEquipmentTable() {
  loadRoutePreset("carmen");
}

function getEquipmentRowsData() {
  const tbody = document.getElementById("equipment-tbody");
  const rows = tbody.querySelectorAll("tr");
  const list = [];
  rows.forEach(tr => {
    const inputs = tr.querySelectorAll("input");
    if (inputs.length >= 8) {
      list.push({
        no: inputs[0].value.trim(),
        rol: inputs[1].value.trim(),
        marca: inputs[2].value.trim(),
        modelo: inputs[3].value.trim(),
        hostname: inputs[4].value.trim(),
        ip_admon: inputs[5].value.trim(),
        int_in: inputs[6].value.trim(),
        int_out: inputs[7].value.trim()
      });
    }
  });
  return list;
}

function addEquipmentRow(data = {}) {
  const tbody = document.getElementById("equipment-tbody");
  const currentCount = tbody.querySelectorAll("tr").length + 1;
  const tr = document.createElement("tr");
  
  const values = [data.no || currentCount, data.rol || "SW", data.marca || "HUAWEI", data.modelo || "ATN 980C", data.hostname || "", data.ip_admon || "", data.int_in || "", data.int_out || ""];
  values.forEach((value, index) => {
    const cell = document.createElement("td");
    const input = document.createElement("input");
    input.type = "text";
    input.value = value;
    input.setAttribute("aria-label", document.querySelectorAll("#equipment-table th")[index].textContent.trim());
    cell.appendChild(input);
    tr.appendChild(cell);
  });
  const actionCell = document.createElement("td");
  actionCell.style.textAlign = "center";
  const removeButton = document.createElement("button");
  removeButton.className = "btn-danger-sm";
  removeButton.type = "button";
  removeButton.textContent = "Eliminar";
  removeButton.addEventListener("click", () => tr.remove());
  actionCell.appendChild(removeButton);
  tr.appendChild(actionCell);
  tbody.appendChild(tr);
}

function loadRoutePreset(presetName) {
  const tbody = document.getElementById("equipment-tbody");
  tbody.innerHTML = "";
  
  if (presetName === "carmen") {
    // Preset matching Central El Carmen example
    document.getElementById("eq-isla").value = "CARMEN";
    const carmenData = [
      { no: "1", rol: "PE", marca: "HUAWEI", modelo: "NE40E", hostname: "PE-DEMO-01", ip_admon: "192.0.2.10", int_in: "", int_out: "" },
      { no: "2", rol: "PE", marca: "HUAWEI", modelo: "NE40E", hostname: "PE-DEMO-02", ip_admon: "192.0.2.11", int_in: "", int_out: "" },
      { no: "3", rol: "SW", marca: "HUAWEI", modelo: "ATN980C", hostname: "SW-DEMO-01", ip_admon: "192.0.2.12", int_in: "", int_out: "Eth-Trunk12" },
      { no: "4", rol: "TRÁFICO", marca: "CTC", modelo: "FRM220A-07", hostname: "TRAFICO-DEMO-01", ip_admon: "192.0.2.13", int_in: "", int_out: "S15|P2" }
    ];
    carmenData.forEach(eq => addEquipmentRow(eq));
  } else if (presetName === "monteverde") {
    // Preset matching Service Manager screenshot
    document.getElementById("eq-isla").value = "MONTE VERDE";
    const mvData = [
      { no: "1", rol: "PE", marca: "HUAWEI", modelo: "NE40E-X8A", hostname: "PE-DEMO-03", ip_admon: "198.51.100.10", int_in: "", int_out: "" },
      { no: "2", rol: "SW", marca: "HUAWEI", modelo: "ATN 980C", hostname: "SW-DEMO-02", ip_admon: "198.51.100.11", int_in: "", int_out: "Eth-Trunk3" },
      { no: "3", rol: "SW", marca: "CTC", modelo: "FRM220A-02", hostname: "SW-DEMO-03", ip_admon: "198.51.100.12", int_in: "", int_out: "S11|P2" }
    ];
    mvData.forEach(eq => addEquipmentRow(eq));
  }
}

// Pre-Shared Key Generator
function generateRandomPSK() {
  const chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  const values = new Uint32Array(20);
  crypto.getRandomValues(values);
  const psk = Array.from(values, value => chars[value % chars.length]).join("");
  document.getElementById("eq-psk").value = psk;
}

// Service Type Selection from Dropdown (INTERNET, DATOS, ACCESO EMPRESARIAL)
function onServiceTypeChange(typeName) {
  // Actualizar la línea de TITULO en el bloque de factibilidad si está presente
  const factArea = document.getElementById("p-factibilidad-bloque");
  if (factArea && factArea.value) {
    factArea.value = factArea.value.replace(/TITULO:\s*\*\*\*[^*]+\*\*\*/i, `TITULO:\t***${typeName}***`);
  }
  
  // Actualizar servicios aceptados
  const itemsArea = document.getElementById("s-items");
  if (itemsArea) {
    const velocidad = document.getElementById("s-velocidad") ? document.getElementById("s-velocidad").value : "300 MBPS";
    itemsArea.value = `${typeName} LOCAL ${velocidad}  (ACEPTADO)\nARRENDAMIENTO EQUIPO  (ACEPTADO)\nMONITOREO ENLACE  (ACEPTADO)`;
  }
  
  // Si la pestaña de generar formato está visible, actualizarla
  const tabGenerar = document.getElementById("tab-generar");
  if (tabGenerar && tabGenerar.classList.contains("active")) {
    updateGeneratedFormat();
  }
}

// Factibilidad & Modal (F2) Handling
function initFactibilidad() {
  updateFactibilidadBadge();

  // Keyboard shortcut listener: F2 to toggle, Esc to close
  document.addEventListener("keydown", (e) => {
    if (e.key === "F2") {
      e.preventDefault();
      const modal = document.getElementById("factibilidad-modal");
      if (modal && modal.style.display === "flex") {
        closeFactibilidadModal();
      } else {
        openFactibilidadModal();
      }
    } else if (e.key === "Escape") {
      const modal = document.getElementById("factibilidad-modal");
      if (modal && modal.style.display === "flex") {
        closeFactibilidadModal();
      }
    }
  });
}

function handleQuickPaste(e) {
  e.preventDefault();
  const pasteData = (e.clipboardData || window.clipboardData).getData("text");
  if (pasteData && pasteData.trim()) {
    const hiddenArea = document.getElementById("p-factibilidad-bloque");
    hiddenArea.value = pasteData;
    updateFactibilidadBadge();
    
    // Detectar título si viene en el texto pegado
    const titleMatch = pasteData.match(/TITULO:\s*\*\*\*([^*]+)\*\*\*/i);
    if (titleMatch) {
      const detectedTitle = titleMatch[1].trim();
      const selectElem = document.getElementById("p-titulo");
      if (selectElem) {
        for (let opt of selectElem.options) {
          if (detectedTitle.toUpperCase().includes(opt.text.toUpperCase())) {
            selectElem.value = opt.value;
            break;
          }
        }
      }
    }
    
    const quickInput = document.getElementById("p-factibilidad-quick-paste");
    quickInput.value = "";
    quickInput.placeholder = "✅ Factibilidad cargada con éxito. Presiona F2 para ver.";
    
    const tabGenerar = document.getElementById("tab-generar");
    if (tabGenerar && tabGenerar.classList.contains("active")) {
      updateGeneratedFormat();
    }
  }
}

function handleQuickPasteKey(e) {
  if (e.key === "F2") {
    e.preventDefault();
    openFactibilidadModal();
  }
}

function updateFactibilidadBadge() {
  const hiddenArea = document.getElementById("p-factibilidad-bloque");
  const badge = document.getElementById("factibilidad-status-badge");
  if (!badge) return;
  
  if (hiddenArea && hiddenArea.value.trim().length > 0) {
    badge.className = "fact-badge loaded";
    badge.innerHTML = `<span class="badge-icon">✅</span><span class="badge-text">Factibilidad Cargada</span>`;
  } else {
    badge.className = "fact-badge empty";
    badge.innerHTML = `<span class="badge-icon">⚪</span><span class="badge-text">Sin Factibilidad</span>`;
  }
}

function openFactibilidadModal() {
  const hiddenArea = document.getElementById("p-factibilidad-bloque");
  const modalTextarea = document.getElementById("modal-factibilidad-textarea");
  const modal = document.getElementById("factibilidad-modal");
  if (!modal) return;
  
  modalTextarea.value = hiddenArea.value;
  modal.style.display = "flex";
  
  const charCount = hiddenArea.value.trim().length;
  document.getElementById("modal-factibilidad-info").textContent = `${charCount} caracteres cargados`;
  modalTextarea.focus();
}

function closeFactibilidadModal() {
  const modal = document.getElementById("factibilidad-modal");
  if (modal) {
    modal.style.display = "none";
  }
}

function saveFactibilidadModal() {
  const hiddenArea = document.getElementById("p-factibilidad-bloque");
  const modalTextarea = document.getElementById("modal-factibilidad-textarea");
  hiddenArea.value = modalTextarea.value;
  updateFactibilidadBadge();
  closeFactibilidadModal();
  
  const tabGenerar = document.getElementById("tab-generar");
  if (tabGenerar && tabGenerar.classList.contains("active")) {
    updateGeneratedFormat();
  }
}

// Google Maps button
function openMaps() {
  const coords = document.getElementById("u-coordenadas").value.trim();
  if (coords) {
    window.open(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(coords)}`, "_blank", "noopener,noreferrer");
  }
}

// Initialize Date Field to Today's Date
function initDateField() {
  const dateInput = document.getElementById("p-fecha");
  if (dateInput) {
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    dateInput.value = `${yyyy}-${mm}-${dd}`;
    
    dateInput.addEventListener("change", () => {
      const tabGenerar = document.getElementById("tab-generar");
      if (tabGenerar && tabGenerar.classList.contains("active")) {
        updateGeneratedFormat();
      }
    });
  }
}

// Collect all form data for generating format
function collectFormData() {
  const itemsText = document.getElementById("s-items").value.trim();
  const itemsList = itemsText.split("\n").map(l => l.trim()).filter(l => l.length > 0);
  
  // Format Date to DD-MM-YYYY for Claro template
  let fechaVal = document.getElementById("p-fecha") ? document.getElementById("p-fecha").value : "";
  if (fechaVal && fechaVal.includes("-")) {
    const p = fechaVal.split("-");
    if (p.length === 3 && p[0].length === 4) {
      fechaVal = `${p[2]}-${p[1]}-${p[0]}`;
    }
  }
  
  const gestorInfo = document.getElementById("eq-gestor-info").value;
  const gestorMatch = gestorInfo.match(/VLAN\s+(\d+).*?([0-9.]+\/\d+).*?GW:\s*([0-9.]+).*?RAISECOM:\s*([0-9.]+)/i);
  if (gestorInfo.trim() && !gestorMatch) {
    throw new Error("El formato de VRF Gestor no es válido. Usa: VLAN 836 | 10.40.3.0/24 | GW: 10.40.3.1 | RAISECOM: 10.40.3.120");
  }

  return {
    titulo: document.getElementById("p-titulo") ? document.getElementById("p-titulo").value : "INTERNET CORPORATIVO",
    id_servicio: document.getElementById("p-id-servicio").value,
    cliente: document.getElementById("p-cliente").value,
    disenador: document.getElementById("p-disenador").value,
    tel_disenador: document.getElementById("p-tel-disenador") ? document.getElementById("p-tel-disenador").value : "",
    fecha: fechaVal,
    factibilidad_bloque: document.getElementById("p-factibilidad-bloque") ? document.getElementById("p-factibilidad-bloque").value : "",
    
    contacto_tec: document.getElementById("p-contacto-tec") ? document.getElementById("p-contacto-tec").value : "",
    ejecutivo: document.getElementById("p-ejecutivo") ? document.getElementById("p-ejecutivo").value : "",
    consultor: document.getElementById("p-consultor") ? document.getElementById("p-consultor").value : "",
    
    direccion: document.getElementById("u-direccion").value,
    coordenadas: document.getElementById("u-coordenadas").value,
    
    medio: document.getElementById("s-medio").value,
    velocidad: document.getElementById("s-velocidad").value,
    ips_count: document.getElementById("s-ips").value,
    equipo_cpe: document.getElementById("s-equipo").value,
    factibilidad: document.getElementById("s-factibilidad").value,
    observaciones: document.getElementById("s-observaciones").value,
    items_aceptados: itemsList,
    
    vrf_name: document.getElementById("eq-vrf-name").value,
    isla: document.getElementById("eq-isla").value,
    red_wan: document.getElementById("eq-red-wan").value,
    rd: document.getElementById("eq-rd").value,
    vlan_num: document.getElementById("eq-vlan-num").value,
    gw_wan: document.getElementById("eq-gw-wan").value,
    desc_vlan: document.getElementById("eq-desc-vlan").value,
    lan: document.getElementById("eq-ip-lan").value,
    ip_wan: document.getElementById("eq-ip-wan").value,
    loopback: document.getElementById("eq-loopback").value,
    psk: document.getElementById("eq-psk").value,
    vlan_gestor: gestorMatch ? gestorMatch[1] : "",
    red_gestor: gestorMatch ? gestorMatch[2] : "",
    gw_gestor: gestorMatch ? gestorMatch[3] : "",
    ip_gestor_raisecom: gestorMatch ? gestorMatch[4] : "",
    
    equipos_claro: getEquipmentRowsData(),
    equipo_raisecom: document.getElementById("m-raisecom").value
  };
}

// Update generated format box
async function updateGeneratedFormat() {
  const missingFields = getMissingRequiredFields();
  if (missingFields.length > 0) {
    updateGenerationAvailability();
    missingFields[0].reportValidity();
    missingFields[0].focus();
    return;
  }

  const requestId = ++formatRequestId;
  const output = document.getElementById("output-format-textarea");
  const copyButton = document.getElementById("btn-copy-format");
  const downloadButton = document.getElementById("btn-download-format");
  output.value = "Generando vista previa...";
  output.dataset.stale = "true";
  copyButton.disabled = true;
  downloadButton.disabled = true;
  try {
    const formData = collectFormData();
    const res = await fetch("/api/generate-format", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data: formData })
    });
    if (!res.ok) throw new Error(await getApiError(res, "Error al generar formato"));
    const data = await res.json();
    if (requestId === formatRequestId) {
      output.value = data.formatted_text;
      output.dataset.stale = "false";
      copyButton.disabled = false;
      downloadButton.disabled = false;
    }
  } catch (err) {
    console.error(err);
    if (requestId === formatRequestId) output.value = "";
    alert(`Error: ${err.message}`);
  }
}

// Copy to clipboard
function copyFormatToClipboard() {
  const textarea = document.getElementById("output-format-textarea");
  if (!textarea.value || textarea.dataset.stale === "true") {
    alert("Actualiza la vista previa antes de copiar.");
    return;
  }
  textarea.select();
  navigator.clipboard.writeText(textarea.value).then(() => {
    const alertBox = document.getElementById("copy-alert");
    alertBox.style.display = "block";
    setTimeout(() => {
      alertBox.style.display = "none";
    }, 3500);
  }).catch(err => {
    alert("No se pudo copiar automáticamente. Por favor selecciónalo con Ctrl+A y copia con Ctrl+C.");
  });
}

// Download TXT
function downloadFormatTxt() {
  const output = document.getElementById("output-format-textarea");
  const text = output.value;
  if (!text || output.dataset.stale === "true") {
    alert("Actualiza la vista previa antes de descargar.");
    return;
  }
  const idServicio = document.getElementById("p-id-servicio").value.trim() || "ALTA_SERVICIO";
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const safeId = idServicio.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80);
  a.download = `Alta_${safeId}.txt`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
