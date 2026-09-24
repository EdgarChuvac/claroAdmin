// State variables
let currentBlocks = [];
let currentSelectedBlock = null;
let currentSelectedFreeIP = null;

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initEquipmentTable();
  initExcelUpload();
  loadInitialData();
  initFactibilidad();
  initDateField();
});

// Tab switching logic
function initTabs() {
  const tabBtns = document.querySelectorAll(".tab-btn");
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      tabBtns.forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(tc => tc.classList.remove("active"));
      
      btn.classList.add("active");
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
  try {
    const res = await fetch(`/api/blocks?sheet=${encodeURIComponent(sheetName)}`);
    if (!res.ok) throw new Error("Error al cargar subredes");
    const data = await res.json();
    currentBlocks = data.blocks || [];
    
    const blockSelect = document.getElementById("ipam-block-select");
    blockSelect.innerHTML = "";
    
    if (currentBlocks.length === 0) {
      const opt = document.createElement("option");
      opt.textContent = "No se detectaron subredes";
      blockSelect.appendChild(opt);
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
  if (!currentBlocks[idx]) return;
  const b = currentBlocks[idx];
  currentSelectedBlock = b;
  
  // Populate Equipamiento fields
  document.getElementById("eq-red-wan").value = b.network_ip;
  document.getElementById("eq-gw-wan").value = b.gateway_ip || "";
  if (b.vlan) {
    document.getElementById("eq-vlan-num").value = b.vlan;
  }
  
  // Populate Free IPs dropdown
  const freeSelect = document.getElementById("ipam-free-select");
  freeSelect.innerHTML = "";
  
  if (b.available_ips.length === 0) {
    const opt = document.createElement("option");
    opt.textContent = "¡Subred LLENA (0 libres)!";
    freeSelect.appendChild(opt);
    currentSelectedFreeIP = null;
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
  
  const ok = confirm(`¿Deseas reservar la IP ${currentSelectedFreeIP.ip} en el Excel para el ID de servicio '${clientId}'?`);
  if (!ok) return;
  
  try {
    const res = await fetch("/api/assign-ip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sheet_name: currentSelectedBlock.sheet_name,
        row: currentSelectedFreeIP.row,
        col_val: currentSelectedBlock.val_col_num,
        client_id: clientId
      })
    });
    
    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.detail || "Error al asignar IP en Excel");
    }
    
    alert(`🎉 ¡IP ${currentSelectedFreeIP.ip} reservada con éxito en el archivo Excel para ${clientId}!`);
    // Reload sheet to refresh available counts
    await loadBlocksForSheet(currentSelectedBlock.sheet_name);
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
}

// Excel Upload Handler
function initExcelUpload() {
  const fileInput = document.getElementById("excel-file-input");
  fileInput.addEventListener("change", async (e) => {
    if (!e.target.files.length) return;
    const file = e.target.files[0];
    const formData = new FormData();
    formData.append("file", file);
    
    document.getElementById("excel-filename").textContent = `Cargando ${file.name}...`;
    
    try {
      const res = await fetch("/api/upload-excel", {
        method: "POST",
        body: formData
      });
      
      if (!res.ok) throw new Error("Error al subir archivo");
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
      alert(`✅ Archivo Excel '${file.name}' cargado con éxito.`);
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
  
  tr.innerHTML = `
    <td><input type="text" value="${data.no || currentCount}"></td>
    <td><input type="text" value="${data.rol || 'SW'}"></td>
    <td><input type="text" value="${data.marca || 'HUAWEI'}"></td>
    <td><input type="text" value="${data.modelo || 'ATN 980C'}"></td>
    <td><input type="text" value="${data.hostname || ''}"></td>
    <td><input type="text" value="${data.ip_admon || ''}"></td>
    <td><input type="text" value="${data.int_in || ''}"></td>
    <td><input type="text" value="${data.int_out || ''}"></td>
    <td style="text-align: center;"><button class="btn-danger-sm" onclick="this.closest('tr').remove()">✖</button></td>
  `;
  tbody.appendChild(tr);
}

function loadRoutePreset(presetName) {
  const tbody = document.getElementById("equipment-tbody");
  tbody.innerHTML = "";
  
  if (presetName === "carmen") {
    // Preset matching Central El Carmen example
    document.getElementById("eq-isla").value = "CARMEN";
    const carmenData = [
      { no: "1", rol: "PE", marca: "HUAWEI", modelo: "NE40E", hostname: "GNCYGTECN1D1A12B02EIM3", ip_admon: "10.179.28.10", int_in: "", int_out: "" },
      { no: "2", rol: "PE", marca: "HUAWEI", modelo: "NE40E", hostname: "GNCYGTECN1D1A11B02EIM2", ip_admon: "10.179.28.9", int_in: "", int_out: "" },
      { no: "3", rol: "SW", marca: "HUAWEI", modelo: "ATN980C", hostname: "GNCYGTECN1D1C06A331BM1", ip_admon: "10.78.10.102", int_in: "", int_out: "Eth-Trunk12 (GE0/6/0, GE0/6/1)" },
      { no: "4", rol: "TRÁFICO", marca: "CTC", modelo: "FRM220A-07", hostname: "GNCYGTECN1D1C05A28AHA6", ip_admon: "10.78.250.234", int_in: "", int_out: "S15|P2" }
    ];
    carmenData.forEach(eq => addEquipmentRow(eq));
  } else if (presetName === "monteverde") {
    // Preset matching Service Manager screenshot
    document.getElementById("eq-isla").value = "MONTE VERDE";
    const mvData = [
      { no: "1", rol: "PE", marca: "HUAWEI", modelo: "NE40E-X8A", hostname: "GMIXGTMVN1T1B0", ip_admon: "10.179.28.14", int_in: "", int_out: "" },
      { no: "2", rol: "SW", marca: "HUAWEI", modelo: "ATN 980C", hostname: "GMIXGTMFN1D1B0:", ip_admon: "10.174.171.46", int_in: "", int_out: "Eth-Trunk3 <G0/2/13|14>" },
      { no: "3", rol: "SW", marca: "CTC", modelo: "FRM220A-02", hostname: "GMIXGTMFN1D120:", ip_admon: "10.87.242.250", int_in: "", int_out: "<S11|P2>" }
    ];
    mvData.forEach(eq => addEquipmentRow(eq));
  }
}

// Pre-Shared Key Generator
function generateRandomPSK() {
  const chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  let psk = "";
  for (let i = 0; i < 14; i++) {
    psk += chars.charAt(Math.floor(Math.random() * chars.length));
  }
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
    itemsArea.value = `• ${typeName} LOCAL ${velocidad}  (ACEPTADO)\n• ARRENDAMIENTO EQUIPO  (ACEPTADO)\n• MONITOREO ENLACE  (ACEPTADO)`;
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
    window.open(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(coords)}`, "_blank");
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
    
    equipos_claro: getEquipmentRowsData(),
    equipo_raisecom: document.getElementById("m-raisecom").value
  };
}

// Update generated format box
async function updateGeneratedFormat() {
  const formData = collectFormData();
  try {
    const res = await fetch("/api/generate-format", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data: formData })
    });
    if (!res.ok) throw new Error("Error al generar formato");
    const data = await res.json();
    document.getElementById("output-format-textarea").value = data.formatted_text;
  } catch (err) {
    console.error(err);
    alert(`Error: ${err.message}`);
  }
}

// Copy to clipboard
function copyFormatToClipboard() {
  const textarea = document.getElementById("output-format-textarea");
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
  const text = document.getElementById("output-format-textarea").value;
  const idServicio = document.getElementById("p-id-servicio").value.trim() || "ALTA_SERVICIO";
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `Alta_${idServicio}.txt`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
