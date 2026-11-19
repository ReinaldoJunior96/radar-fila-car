const PAGE_SIZE = 25;
const STATUS_LABELS = { AT: "Ativo", PE: "Pendente", CA: "Cancelado", SU: "Suspenso" };
const STATUS_CLASSES = { PE: "pending", CA: "cancelled", SU: "suspended" };
const BATCH_LIMIT = 1000;
const CAR_CODE_PATTERN = /^[A-Z]{2}-\d{7}-[A-Z0-9.]{8,64}$/;
const MISSING_REASONS = {
  nao_encontrado: "Não encontrado",
  codigo_invalido: "Código inválido",
};
const state = {
  uf: "MA",
  states: [],
  stateTotal: null,
  map: null,
  municipalities: [],
  selectedMunicipality: null,
  selectedBounds: null,
  selectedBbox: null,
  drawing: false,
  drawStart: null,
  preview: null,
  selectionLayer: null,
  resultLayer: null,
  page: 1,
  pages: 0,
  total: 0,
  activeParams: null,
  activeFilterKey: null,
  features: [],
  metrics: null,
  lastExport: null,
  loading: false,
  exporting: false,
  filtersDirty: false,
  base: null,
  responseMs: null,
  cacheStatus: null,
  highlightLayer: null,
  batchCodes: [],
};

const elements = {
  form: document.querySelector("#area-search-form"),
  uf: document.querySelector("#uf"),
  stateTagName: document.querySelector("#state-tag-name"),
  stateTagUf: document.querySelector("#state-tag-uf"),
  municipality: document.querySelector("#municipality"),
  municipalityCount: document.querySelector("#municipality-count"),
  allState: document.querySelector("#all-state"),
  status: document.querySelector("#status-filter"),
  condition: document.querySelector("#condition-filter"),
  updatedSince: document.querySelector("#updated-since"),
  appRestore: document.querySelector("#app-restore"),
  codeForm: document.querySelector("#code-form"),
  carCode: document.querySelector("#car-code"),
  openBatch: document.querySelector("#open-batch"),
  batchDialog: document.querySelector("#batch-dialog"),
  batchClose: document.querySelector("#batch-close"),
  batchForm: document.querySelector("#batch-form"),
  batchCodes: document.querySelector("#batch-codes"),
  batchFile: document.querySelector("#batch-file"),
  batchSample: document.querySelector("#batch-sample"),
  batchCount: document.querySelector("#batch-count"),
  batchSubmit: document.querySelector("#batch-submit"),
  batchStatus: document.querySelector("#batch-status"),
  batchResults: document.querySelector("#batch-results"),
  batchSummary: document.querySelector("#batch-summary"),
  batchBody: document.querySelector("#batch-body"),
  batchNotice: document.querySelector("#batch-notice"),
  batchDownload: document.querySelector("#batch-download"),
  areaMin: document.querySelector("#area-min"),
  areaMax: document.querySelector("#area-max"),
  reset: document.querySelector("#reset-filters"),
  search: document.querySelector("#search-button"),
  searchLabel: document.querySelector("#search-label"),
  notice: document.querySelector("#notice"),
  noticeText: document.querySelector("#notice span:last-child"),
  sourceNote: document.querySelector("#source-note"),
  sourceText: document.querySelector("#source-text"),
  mapPanel: document.querySelector(".map-panel"),
  mapTitle: document.querySelector("#map-title"),
  mapSubtitle: document.querySelector("#map-subtitle"),
  mapEmpty: document.querySelector("#map-empty"),
  drawButton: document.querySelector("#draw-area-button"),
  drawHint: document.querySelector("#draw-hint"),
  selectedArea: document.querySelector("#selected-area"),
  selectedAreaLabel: document.querySelector("#selected-area-label"),
  clearArea: document.querySelector("#clear-area"),
  resultsTitle: document.querySelector("#results-title"),
  resultsSummary: document.querySelector("#results-summary"),
  resultsBody: document.querySelector("#results-body"),
  pageSummary: document.querySelector("#page-summary"),
  previous: document.querySelector("#previous-page"),
  next: document.querySelector("#next-page"),
  exportCsv: document.querySelector("#export-csv"),
  exportGeojson: document.querySelector("#export-geojson"),
  metricRecords: document.querySelector("#metric-records"),
  metricReturned: document.querySelector("#metric-returned"),
  metricExport: document.querySelector("#metric-export"),
  metricExportDetail: document.querySelector("#metric-export-detail"),
  metricBase: document.querySelector("#metric-base"),
  metricBaseDetail: document.querySelector("#metric-base-detail"),
  metricCache: document.querySelector("#metric-cache"),
  metricQueryTime: document.querySelector("#metric-query-time"),
  metricSaved: document.querySelector("#metric-saved"),
  metricSavedDetail: document.querySelector("#metric-saved-detail"),
  propertyDialog: document.querySelector("#property-dialog"),
  propertyDialogTitle: document.querySelector("#property-dialog-title"),
  propertyDialogContent: document.querySelector("#property-dialog-content"),
  propertyDialogClose: document.querySelector("#property-dialog-close"),
};

const THEME_LABELS = {
  apps: "Áreas de preservação permanente (APP)",
  reserva_legal: "Reserva Legal",
  vegetacao_nativa: "Vegetação nativa",
  area_consolidada: "Área consolidada",
  hidrografia: "Hidrografia",
  area_pousio: "Área de pousio",
  servidao_administrativa: "Servidão administrativa",
  uso_restrito: "Uso restrito",
  ecossistemas_relevo: "Ecossistemas e relevo",
};
const CACHE_LABELS = {
  cache: "Respondido pelo cache, sem chamar o SICAR",
  sicar: "Buscado agora no SICAR",
  cache_antigo: "SICAR indisponível: mostrando a última cópia guardada",
};

function currentStateName() {
  return state.states.find((item) => item.uf === state.uf)?.nome ?? state.uf;
}

function showNotice(message, kind = "") {
  elements.notice.className = `notice ${kind}`.trim();
  elements.noticeText.textContent = message;
}

function setLoading(loading) {
  state.loading = loading;
  elements.search.disabled = loading || elements.municipality.disabled;
  elements.searchLabel.textContent = loading ? "Buscando imóveis…" : "Buscar imóveis";
  elements.search.setAttribute("aria-busy", String(loading));
  updateExportButtons();
  updatePaginationButtons();
}

function updateExportButtons() {
  const disabled = state.loading || state.exporting || state.filtersDirty || state.total === 0;
  elements.exportCsv.disabled = disabled;
  elements.exportGeojson.disabled = disabled;
}

function updatePaginationButtons() {
  const disabled = state.loading || state.filtersDirty;
  elements.previous.disabled = disabled || state.page <= 1;
  elements.next.disabled = disabled || state.page >= state.pages;
}

function markFiltersDirty() {
  state.filtersDirty = true;
  state.lastExport = null;
  updateExportButtons();
  updatePaginationButtons();
  renderMetrics();
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} KB`;
  return `${(bytes / (1024 * 1024)).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} MB`;
}

function renderMetrics() {
  const metrics = state.metrics;
  elements.metricRecords.textContent = metrics
    ? metrics.records_matched.toLocaleString("pt-BR")
    : "—";
  elements.metricReturned.textContent = metrics
    ? `${metrics.records_returned} nesta página · página ${state.page} de ${state.pages}`
    : "— nesta página";
  elements.metricBase.textContent = state.base?.atualizado_ate ? formatIsoDate(state.base.atualizado_ate) : "—";
  elements.metricBaseDetail.textContent = state.base?.consultado_em
    ? `Conferido em ${new Date(state.base.consultado_em).toLocaleString("pt-BR")}`
    : "Consultado ao vivo";
  elements.metricQueryTime.textContent = state.responseMs === null ? "—" : `${Math.round(state.responseMs).toLocaleString("pt-BR")} ms`;
  elements.metricCache.textContent = state.cacheStatus === "HIT"
    ? CACHE_LABELS.cache
    : CACHE_LABELS[metrics?.origem] ?? "Medido neste navegador";
  if (state.lastExport) {
    elements.metricExport.textContent = formatBytes(state.lastExport.bytes);
    elements.metricExportDetail.textContent = `${state.lastExport.format.toUpperCase()} · ${state.lastExport.bytes.toLocaleString("pt-BR")} bytes`;
  } else {
    elements.metricExport.textContent = "Ainda não baixada";
    elements.metricExportDetail.textContent = state.filtersDirty
      ? "Aplique os filtros e baixe um arquivo"
      : "Baixe CSV ou GeoJSON para medir";
  }
}

async function refreshSavings() {
  try {
    const response = await fetch("/api/cache/metricas", { cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();
    elements.metricSaved.textContent = data.chamadas_evitadas.toLocaleString("pt-BR");
    elements.metricSavedDetail.textContent = `${data.chamadas_ao_sicar.toLocaleString("pt-BR")} feitas · ${formatBytes(data.bytes_evitados)} não transferidos`;
  } catch {
    elements.metricSavedDetail.textContent = "Indisponível no momento";
  }
}

function startMap() {
  state.map = L.map("map", { preferCanvas: true, zoomControl: false }).setView([-3.37, -44.29], 10);
  L.control.zoom({ position: "bottomright" }).addTo(state.map);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(state.map);
  state.resultLayer = L.geoJSON(null, {
    style: { color: "#205d43", weight: 1.25, fillColor: "#76a77a", fillOpacity: 0.19 },
    onEachFeature: (feature, layer) => {
      const p = feature.properties ?? {};
      const code = escapeHtml(p.cod_imovel ?? "");
      layer.bindPopup(`<strong>${code}</strong><br>${escapeHtml(formatArea(p.num_area))} · ${escapeHtml(STATUS_LABELS[p.ind_status] ?? p.ind_status ?? "Situação não informada")}<br><button class="popup-details" type="button" data-car-code="${code}">Ver detalhes</button>`);
      layer.on("popupopen", (event) => {
        const button = event.popup.getElement()?.querySelector(".popup-details");
        button?.addEventListener("click", () => openPropertyDetails(button.dataset.carCode));
      });
    },
  }).addTo(state.map);
  state.selectionLayer = L.layerGroup().addTo(state.map);
  state.highlightLayer = L.geoJSON(null, {
    style: { color: "#c4661f", weight: 2.5, fillColor: "#e9a15f", fillOpacity: 0.22 },
  }).addTo(state.map);

  state.map.on("mousedown", beginRectangle);
  state.map.on("mousemove", updateRectangle);
  state.map.on("mouseup", finishRectangle);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function formatArea(value) {
  const number = value === null || value === undefined || value === "" ? Number.NaN : Number(value);
  return Number.isFinite(number) ? `${number.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} ha` : "—";
}

function formatIsoDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value ?? ""));
  return match ? `${match[3]}/${match[2]}/${match[1]}` : "—";
}

function formatNumber(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("pt-BR", { maximumFractionDigits: digits }) : "—";
}

function detailField(label, value) {
  const wrapper = document.createElement("div");
  wrapper.className = "detail-field";
  const heading = document.createElement("span");
  heading.textContent = label;
  const content = document.createElement("strong");
  content.textContent = value || "—";
  wrapper.append(heading, content);
  return wrapper;
}

function appendDetailSection(title, content) {
  const section = document.createElement("section");
  section.className = "detail-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.append(heading, content);
  elements.propertyDialogContent.append(section);
}

function renderPropertyDetails(data) {
  elements.propertyDialogTitle.textContent = data.codigo_car;
  elements.propertyDialogContent.replaceChildren();

  const fields = document.createElement("div");
  fields.className = "detail-grid";
  const typeLabels = { IRU: "Imóvel Rural", AST: "Assentamento", PCT: "Povos e Comunidades Tradicionais" };
  fields.append(
    detailField("Situação cadastral", data.situacao_descricao),
    detailField("Condição informada", data.condicao),
    detailField("Município / UF", [data.municipio, data.uf].filter(Boolean).join(" / ")),
    detailField("Área declarada", formatArea(data.area_declarada_ha)),
    detailField("Área calculada do polígono", formatArea(data.area_calculada_ha)),
    detailField("APP a recompor", formatArea(data.app_a_recompor_ha)),
    detailField("Módulos fiscais", formatNumber(data.modulos_fiscais, 2)),
    detailField("Tipo de imóvel", typeLabels[data.tipo_imovel] ?? data.tipo_imovel),
    detailField("Data de inscrição", formatIsoDate(data.data_inscricao)),
    detailField("Última atualização", formatIsoDate(data.data_atualizacao)),
  );
  appendDetailSection("Cadastro", fields);

  if (data.alertas?.length) {
    const alerts = document.createElement("ul");
    alerts.className = "detail-alerts";
    for (const alert of data.alertas) {
      const item = document.createElement("li");
      item.textContent = alert.descricao;
      alerts.append(item);
    }
    appendDetailSection("Pontos de atenção nos dados", alerts);
  }

  const themes = document.createElement("div");
  themes.className = "detail-theme-list";
  for (const [key, label] of Object.entries(data.camadas ?? THEME_LABELS)) {
    const rows = (data.temas ?? []).filter((item) => item.camada === key);
    if (!rows.length) {
      const row = document.createElement("div");
      row.className = "detail-theme";
      const name = document.createElement("strong");
      name.textContent = label;
      const amount = document.createElement("span");
      amount.textContent = "Nenhuma feição nesta camada";
      row.append(name, amount);
      themes.append(row);
      continue;
    }
    for (const item of rows) {
      const row = document.createElement("div");
      row.className = "detail-theme";
      const name = document.createElement("strong");
      name.textContent = item.categoria === label ? label : `${label} · ${item.categoria}`;
      const amount = document.createElement("span");
      const areaText = item.area_ha === null || item.area_ha === undefined ? "" : `${formatArea(item.area_ha)} · `;
      amount.textContent = `${areaText}${item.feicoes.toLocaleString("pt-BR")} feição(ões)`;
      row.append(name, amount);
      themes.append(row);
    }
  }
  appendDetailSection("Camadas ambientais declaradas", themes);

  const note = document.createElement("p");
  note.className = "detail-note";
  note.textContent = `${data.aviso} As áreas vêm das camadas oficiais; quando o serviço não informa a área da feição, ela é calculada pelo polígono.`;
  elements.propertyDialogContent.append(note);

  const link = document.createElement("a");
  link.className = "detail-official-link";
  link.href = `https://car.gov.br/#/consultar/${encodeURIComponent(data.codigo_car)}`;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = "Abrir Demonstrativo oficial no SICAR ↗";
  elements.propertyDialogContent.append(link);
}

function isValidMapBounds(bounds) {
  return bounds.isValid() && bounds.getSouth() >= -90 && bounds.getNorth() <= 90
    && bounds.getWest() >= -180 && bounds.getEast() <= 180;
}

function highlightProperty(features) {
  state.highlightLayer.clearLayers();
  if (!features?.length) return;
  const bounds = L.geoJSON(features).getBounds();
  if (!isValidMapBounds(bounds)) return;
  state.highlightLayer.addData(features);
  if (bounds.isValid()) {
    elements.mapEmpty.classList.add("is-hidden");
    state.map.fitBounds(bounds, { padding: [55, 55], maxZoom: 15 });
  }
}

async function openPropertyDetails(carCode) {
  if (!carCode) return false;
  elements.propertyDialogTitle.textContent = carCode;
  const loading = document.createElement("p");
  loading.className = "detail-loading";
  loading.textContent = "Carregando cadastro e camadas…";
  elements.propertyDialogContent.replaceChildren(loading);
  if (!elements.propertyDialog.open) elements.propertyDialog.showModal();
  try {
    const response = await fetch(`/api/imoveis/${encodeURIComponent(carCode)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Não foi possível carregar os detalhes.");
    renderPropertyDetails(data);
    if (state.map) highlightProperty(data.limites);
    return true;
  } catch (error) {
    const message = document.createElement("p");
    message.className = "detail-error";
    message.textContent = error.message || "Falha ao consultar os detalhes.";
    elements.propertyDialogContent.replaceChildren(message);
    return false;
  }
}

function parseCarCodes(text) {
  const tokens = String(text).toUpperCase().split(/[\s,;|"']+/);
  return [...new Set(tokens.filter((token) => CAR_CODE_PATTERN.test(token)))];
}

function updateBatchCount() {
  state.batchCodes = parseCarCodes(elements.batchCodes.value);
  const count = state.batchCodes.length;
  const tooMany = count > BATCH_LIMIT;
  elements.batchCount.textContent = count
    ? `${count.toLocaleString("pt-BR")} código(s) reconhecido(s)${tooMany ? ", acima do limite de 1.000" : ""}`
    : "Nenhum código reconhecido";
  elements.batchCount.classList.toggle("is-error", tooMany);
  elements.batchSubmit.disabled = !count || tooMany;
}

function batchStatus(message, isError = false) {
  elements.batchStatus.hidden = !message;
  elements.batchStatus.textContent = message;
  elements.batchStatus.classList.toggle("is-error", isError);
}

function themeCell(item, key) {
  if (!item.encontrado) return "—";
  const theme = item.temas?.[key];
  if (!theme) return item.temas ? "Sem registro" : "—";
  return `${theme.feicoes.toLocaleString("pt-BR")} feição(ões)`;
}

function restoreCell(item) {
  if (!item.encontrado || item.app_a_recompor_feicoes === undefined) return "—";
  return item.app_a_recompor_feicoes
    ? `Sim · ${item.app_a_recompor_feicoes.toLocaleString("pt-BR")} feição(ões)`
    : "Não";
}

function renderBatch(data, elapsed) {
  const summary = [
    ["Consultados", data.resumo.unicos],
    ["Encontrados", data.resumo.encontrados],
    ["Não encontrados", data.resumo.nao_encontrados],
    ["Com alerta", data.resumo.com_alerta],
  ];
  elements.batchSummary.replaceChildren(...summary.map(([label, value]) => {
    const card = document.createElement("div");
    const name = document.createElement("span");
    name.textContent = label;
    const number = document.createElement("strong");
    number.textContent = value.toLocaleString("pt-BR");
    card.append(name, number);
    return card;
  }));
  elements.batchBody.replaceChildren(...data.itens.map((item) => {
    const row = document.createElement("tr");
    const status = document.createElement("span");
    status.className = `status-chip ${item.encontrado ? STATUS_CLASSES[item.situacao] ?? "" : "cancelled"}`.trim();
    status.textContent = item.encontrado ? item.situacao_descricao : MISSING_REASONS[item.motivo] ?? "Sem dados";
    const values = [
      item.codigo_car, status, item.condicao ?? "—", item.municipio ?? "—",
      item.encontrado ? formatArea(item.area_declarada_ha) : "—",
      themeCell(item, "apps"), restoreCell(item), themeCell(item, "reserva_legal"),
      item.alertas?.map((alert) => alert.descricao).join("; ") || "—",
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.append(value);
      row.append(cell);
    }
    if (item.encontrado) {
      row.dataset.featureIndex = "batch";
      row.title = "Clique para ver os detalhes deste imóvel";
      row.addEventListener("click", () => openPropertyDetails(item.codigo_car));
    }
    return row;
  }));
  elements.batchNotice.textContent = data.aviso;
  elements.batchResults.hidden = false;
  batchStatus(`${data.resumo.unicos.toLocaleString("pt-BR")} código(s) consultado(s) em ${Math.round(elapsed).toLocaleString("pt-BR")} ms.`);
  refreshSavings();
}

async function postBatch(path) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ codigos: state.batchCodes, incluir_temas: true }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === "string" ? error.detail : "Não foi possível consultar o lote.");
  }
  return response;
}

async function submitBatch() {
  elements.batchSubmit.disabled = true;
  elements.batchResults.hidden = true;
  batchStatus("Consultando o lote no SICAR…");
  const started = performance.now();
  try {
    const response = await postBatch("/api/consultas/lote");
    renderBatch(await response.json(), performance.now() - started);
  } catch (error) {
    batchStatus(error.message || "Falha ao consultar o lote.", true);
  } finally {
    updateBatchCount();
  }
}

async function downloadBatch() {
  elements.batchDownload.disabled = true;
  try {
    const response = await postBatch("/api/consultas/lote.csv");
    saveBlob(await response.blob(), "car-consulta-em-lote.csv");
  } catch (error) {
    batchStatus(error.message || "Falha ao gerar o CSV.", true);
  } finally {
    elements.batchDownload.disabled = false;
  }
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function formatDate(value) {
  if (!value) return "—";
  if (/^\d{1,2}\/\d{1,2}\/\d{4}$/.test(String(value))) return String(value);
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? String(value) : parsed.toLocaleDateString("pt-BR");
}

function municipalityBounds(municipality) {
  const [west, south, east, north] = municipality.bounds;
  return L.latLngBounds([south, west], [north, east]);
}

async function loadStates() {
  const response = await fetch("/api/estados");
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Não foi possível carregar os estados.");
  state.states = data.estados;
  elements.uf.replaceChildren(...state.states.map((item) => new Option(`${item.nome} (${item.uf})`, item.uf)));
  elements.uf.value = state.uf;
  elements.uf.disabled = false;
}

function updateStateLabels() {
  const name = currentStateName();
  elements.stateTagName.textContent = name;
  elements.stateTagUf.textContent = state.uf;
  elements.carCode.placeholder = `${state.uf}-…`;
}

async function loadMunicipalities(preferred = null) {
  elements.municipality.disabled = true;
  elements.search.disabled = true;
  elements.municipality.replaceChildren(new Option("Carregando municípios…", ""));
  try {
    const response = await fetch(`/api/municipalities?uf=${encodeURIComponent(state.uf)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Não foi possível carregar os municípios.");
    state.municipalities = data.municipalities;
    state.stateTotal = data.property_count;
    state.base = data.base ?? null;
    updateStateLabels();
    elements.municipality.replaceChildren(new Option(`Todo o estado: ${currentStateName()}`, ""));
    for (const municipality of state.municipalities) {
      elements.municipality.append(new Option(municipality.name, municipality.name));
    }
    elements.municipality.disabled = false;
    elements.search.disabled = false;
    // Abre em um município: buscar um estado inteiro é a consulta mais pesada para o SICAR.
    elements.municipality.value = state.municipalities.some((item) => item.name === preferred)
      ? preferred
      : state.municipalities[0]?.name ?? "";
    updateSelectedMunicipality();
    elements.sourceText.textContent = `${data.source}. Imóveis pelo WFS do SICAR e camadas ambientais pela Consulta Pública do CAR.`;
    elements.sourceNote.hidden = false;
    await runSearch(1);
  } catch (error) {
    elements.municipality.replaceChildren(new Option("Falha ao carregar", ""));
    showNotice(error.message || "Não foi possível carregar os municípios.", "error");
  }
}

async function startApp() {
  startMap();
  refreshSavings();
  try {
    await loadStates();
  } catch (error) {
    elements.uf.replaceChildren(new Option("Maranhão (MA)", "MA"));
    showNotice(error.message || "Não foi possível carregar os estados.", "error");
  }
  await loadMunicipalities("Itapecuru Mirim");
}

function updateSelectedMunicipality() {
  state.selectedMunicipality = state.municipalities.find((item) => item.name === elements.municipality.value) ?? null;
  state.selectedBbox = null;
  state.selectionLayer.clearLayers();
  elements.selectedArea.hidden = true;
  elements.allState.hidden = !state.selectedMunicipality;
  if (!state.selectedMunicipality) {
    const all = state.municipalities.filter((item) => item.bounds).map((item) => municipalityBounds(item));
    if (all.length) {
      state.selectedBounds = all.reduce((bounds, item) => bounds.extend(item), L.latLngBounds(all[0].getSouthWest(), all[0].getNorthEast()));
      state.map.fitBounds(state.selectedBounds, { padding: [20, 20], animate: false });
    }
    elements.municipalityCount.textContent = state.stateTotal === null || state.stateTotal === undefined
      ? "Busca em todo o estado"
      : `${state.stateTotal.toLocaleString("pt-BR")} imóveis no SICAR`;
    elements.mapTitle.textContent = currentStateName();
    elements.mapSubtitle.textContent = "Imóveis rurais cadastrados no CAR";
    return;
  }
  if (state.selectedMunicipality.bounds) {
    state.selectedBounds = municipalityBounds(state.selectedMunicipality);
    state.map.fitBounds(state.selectedBounds, { padding: [35, 35], maxZoom: 12, animate: false });
  }
  elements.municipalityCount.textContent = "A quantidade aparece após a busca";
  elements.mapTitle.textContent = state.selectedMunicipality.name;
  elements.mapSubtitle.textContent = `Imóveis rurais cadastrados no CAR · ${currentStateName()}`;
  elements.mapEmpty.classList.add("is-hidden");
}

function beginRectangle(event) {
  if (!state.drawing || event.originalEvent.button !== 0) return;
  state.drawStart = event.latlng;
  state.map.dragging.disable();
  if (state.preview) state.selectionLayer.removeLayer(state.preview);
  state.preview = L.rectangle([state.drawStart, state.drawStart], {
    color: "#397da2", weight: 2, dashArray: "6 4", fillColor: "#6daed0", fillOpacity: 0.12,
  }).addTo(state.selectionLayer);
}

function updateRectangle(event) {
  if (!state.drawing || !state.drawStart || !state.preview) return;
  state.preview.setBounds(L.latLngBounds(state.drawStart, event.latlng));
}

function finishRectangle(event) {
  if (!state.drawing || !state.drawStart) return;
  state.map.dragging.enable();
  const bounds = L.latLngBounds(state.drawStart, event.latlng);
  state.drawStart = null;
  if (state.preview) state.selectionLayer.removeLayer(state.preview);
  state.preview = null;
  const size = state.map.distance(bounds.getSouthWest(), bounds.getNorthEast());
  if (size < 100) {
    showNotice("Arraste um retângulo maior para selecionar a área.", "error");
    return;
  }
  state.selectedBbox = {
    west: bounds.getWest(), south: bounds.getSouth(), east: bounds.getEast(), north: bounds.getNorth(),
  };
  L.rectangle(bounds, {
    color: "#397da2", weight: 2, dashArray: "6 4", fillColor: "#6daed0", fillOpacity: 0.12,
  }).addTo(state.selectionLayer);
  elements.selectedArea.hidden = false;
  elements.selectedAreaLabel.textContent = `Retângulo selecionado · ${bounds.getNorthEast().distanceTo(bounds.getSouthWest()).toLocaleString("pt-BR", { maximumFractionDigits: 0 })} m de diagonal`;
  stopDrawing();
  markFiltersDirty();
  showNotice("Área selecionada. Clique em “Buscar imóveis” para aplicar o recorte.");
}

function stopDrawing() {
  state.drawing = false;
  state.drawStart = null;
  if (state.preview) state.selectionLayer.removeLayer(state.preview);
  state.preview = null;
  elements.drawButton.classList.remove("active");
  elements.drawButton.setAttribute("aria-pressed", "false");
  elements.drawButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16v16H4z" stroke-dasharray="3 2"></path><path d="M8 4v4M16 4v4M4 8h4M4 16h4"></path></svg>Desenhar retângulo';
  elements.drawHint.hidden = true;
  elements.mapPanel.classList.remove("is-drawing");
  state.map.dragging.enable();
}

function clearSelectedArea() {
  stopDrawing();
  state.selectedBbox = null;
  state.drawStart = null;
  if (state.preview) state.selectionLayer.removeLayer(state.preview);
  state.preview = null;
  state.selectionLayer.clearLayers();
  elements.selectedArea.hidden = true;
}

function getSearchParams(page = 1) {
  const params = new URLSearchParams({ uf: state.uf, page: String(page), page_size: String(PAGE_SIZE) });
  if (elements.municipality.value) params.set("municipality", elements.municipality.value);
  if (elements.status.value) params.set("status", elements.status.value);
  if (elements.condition.value) params.set("condition", elements.condition.value);
  if (elements.updatedSince.value) params.set("updated_since", elements.updatedSince.value);
  if (elements.appRestore.checked) params.set("app_to_restore", "true");
  if (elements.areaMin.value !== "") params.set("area_min", elements.areaMin.value);
  if (elements.areaMax.value !== "") params.set("area_max", elements.areaMax.value);
  if (state.selectedBbox) {
    for (const [key, value] of Object.entries(state.selectedBbox)) params.set(key, String(value));
  }
  return params;
}

async function runSearch(page = 1) {
  const params = getSearchParams(page);
  setLoading(true);
  showNotice("Consultando o SICAR…");
  try {
    const started = performance.now();
    const response = await fetch(`/api/search?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Não foi possível realizar a busca.");
    state.responseMs = performance.now() - started;
    state.cacheStatus = response.headers.get("x-cache-status");
    state.base = data.base ?? state.base;
    state.page = data.page;
    state.pages = data.pages;
    state.total = data.total;
    state.features = data.features;
    state.activeParams = new URLSearchParams(params);
    const filterKey = new URLSearchParams(params);
    filterKey.delete("page");
    filterKey.delete("page_size");
    state.activeFilterKey = filterKey.toString();
    state.metrics = data.metrics;
    state.filtersDirty = false;
    renderResults(data);
    refreshSavings();
    showNotice(data.total
      ? `${data.total.toLocaleString("pt-BR")} imóveis encontrados. A tabela e o mapa mostram esta página.`
      : "Nenhum imóvel corresponde aos filtros selecionados.", data.total ? "success" : "");
  } catch (error) {
    state.features = [];
    state.total = 0;
    state.page = 1;
    state.pages = 0;
    state.metrics = null;
    state.responseMs = null;
    state.cacheStatus = null;
    state.activeParams = null;
    state.activeFilterKey = null;
    state.lastExport = null;
    renderResults({ total: 0, page: 1, pages: 0, features: [] });
    showNotice(error.message || "Falha ao consultar a base.", "error");
  } finally {
    setLoading(false);
  }
}

function renderResults(data) {
  const city = state.selectedMunicipality?.name ?? currentStateName();
  elements.resultsTitle.textContent = `Imóveis em ${city}`;
  const areaLabel = state.selectedBbox ? " · com recorte no mapa" : "";
  elements.resultsSummary.textContent = `${data.total.toLocaleString("pt-BR")} imóveis encontrados${areaLabel}`;
  elements.pageSummary.textContent = data.total
    ? `Página ${data.page} de ${data.pages} · ${data.features.length} registros nesta página`
    : "Nenhum registro para exibir";
  updatePaginationButtons();
  updateExportButtons();
  renderMetrics();

  elements.resultsBody.replaceChildren();
  if (!data.features.length) {
    const row = document.createElement("tr");
    row.className = "empty-row";
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.textContent = "Nenhum imóvel nesta busca.";
    row.append(cell);
    elements.resultsBody.append(row);
  } else {
    data.features.forEach((feature, index) => {
      const p = feature.properties ?? {};
      const row = document.createElement("tr");
      row.dataset.featureIndex = String(index);
      const code = document.createElement("td");
      code.textContent = p.cod_imovel ?? "—";
      const status = document.createElement("td");
      const chip = document.createElement("span");
      chip.className = `status-chip ${STATUS_CLASSES[p.ind_status] ?? ""}`.trim();
      chip.textContent = STATUS_LABELS[p.ind_status] ?? p.ind_status ?? "Não informado";
      status.append(chip);
      const area = document.createElement("td");
      area.textContent = formatArea(p.num_area);
      const type = document.createElement("td");
      type.textContent = p.des_condic ?? "—";
      const update = document.createElement("td");
      update.textContent = formatDate(p.dat_atuali);
      row.append(code, status, area, type, update);
      row.title = "Clique para ver os detalhes deste imóvel";
      row.addEventListener("click", () => {
        zoomToFeature(feature);
        openPropertyDetails(p.cod_imovel);
      });
      elements.resultsBody.append(row);
    });
  }

  state.resultLayer.clearLayers();
  state.resultLayer.addData(data.features.filter((feature) => !feature.properties?.alertas?.includes("coordenadas_invalidas")));
  elements.mapEmpty.classList.toggle("is-hidden", data.total > 0);
  elements.mapSubtitle.textContent = `${city} · ${data.total.toLocaleString("pt-BR")} imóveis no resultado`;
}

function zoomToFeature(feature) {
  const layer = L.geoJSON(feature);
  const bounds = layer.getBounds();
  if (isValidMapBounds(bounds)) state.map.fitBounds(bounds, { padding: [55, 55], maxZoom: 15 });
  state.resultLayer.eachLayer((item) => {
    if (String(item.feature?.id) === String(feature.id)) item.openPopup();
  });
}

async function exportResults(format) {
  if (!state.activeParams || !state.total) return;
  if (state.total > 10000) {
    showNotice("A exportação está limitada a 10.000 imóveis. Refine os filtros ou desenhe um retângulo menor.", "error");
    return;
  }
  const params = new URLSearchParams(state.activeParams);
  params.delete("page");
  params.delete("page_size");
  params.set("format", format);
  state.exporting = true;
  updateExportButtons();
  showNotice(`Gerando arquivo ${format.toUpperCase()}…`);
  try {
    const response = await fetch(`/api/search/export?${params}`);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Não foi possível gerar o arquivo.");
    }
    const blob = await response.blob();
    const bytes = blob.size;
    const disposition = response.headers.get("content-disposition") ?? "";
    const filename = disposition.match(/filename="([^"]+)"/)?.[1] ?? `car-recorte.${format}`;
    saveBlob(blob, filename);
    state.lastExport = { format, bytes };
    renderMetrics();
    showNotice(`${format.toUpperCase()} baixado: ${bytes.toLocaleString("pt-BR")} bytes (${formatBytes(bytes)}).`, "success");
  } catch (error) {
    showNotice(error.message || "Falha ao gerar a exportação.", "error");
  } finally {
    state.exporting = false;
    updateExportButtons();
  }
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (elements.areaMin.value && elements.areaMax.value && Number(elements.areaMin.value) > Number(elements.areaMax.value)) {
    showNotice("A área mínima não pode ser maior que a máxima.", "error");
    return;
  }
  runSearch(1);
});
elements.uf.addEventListener("change", () => {
  state.uf = elements.uf.value;
  clearSelectedArea();
  markFiltersDirty();
  loadMunicipalities();
});
elements.municipality.addEventListener("change", () => {
  updateSelectedMunicipality();
  markFiltersDirty();
  runSearch(1);
});
elements.allState.addEventListener("click", () => {
  elements.municipality.value = "";
  elements.municipality.dispatchEvent(new Event("change"));
});
elements.status.addEventListener("change", markFiltersDirty);
elements.condition.addEventListener("change", markFiltersDirty);
elements.updatedSince.addEventListener("input", markFiltersDirty);
elements.appRestore.addEventListener("change", markFiltersDirty);
elements.codeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const code = elements.carCode.value.trim().toUpperCase();
  if (!CAR_CODE_PATTERN.test(code)) {
    showNotice("Confira o código CAR. Exemplo: MA-2100055-74B0F111A29D4ECF9086AAED23B43274.", "error");
    return;
  }
  await openPropertyDetails(code);
});
elements.openBatch.addEventListener("click", () => {
  updateBatchCount();
  elements.batchDialog.showModal();
});
elements.batchClose.addEventListener("click", () => elements.batchDialog.close());
elements.batchDialog.addEventListener("click", (event) => {
  if (event.target === elements.batchDialog) elements.batchDialog.close();
});
elements.batchCodes.addEventListener("input", updateBatchCount);
elements.batchFile.addEventListener("change", async () => {
  const [file] = elements.batchFile.files;
  if (!file) return;
  elements.batchCodes.value = parseCarCodes(await file.text()).join("\n");
  elements.batchFile.value = "";
  updateBatchCount();
});
elements.batchSample.addEventListener("click", () => {
  const codes = state.features.map((feature) => feature.properties?.cod_imovel).filter(Boolean);
  elements.batchCodes.value = [...new Set(codes)].join("\n");
  updateBatchCount();
  if (!codes.length) batchStatus("Faça uma busca antes de usar os imóveis dela.", true);
});
elements.batchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  submitBatch();
});
elements.batchDownload.addEventListener("click", downloadBatch);
elements.areaMin.addEventListener("input", markFiltersDirty);
elements.areaMax.addEventListener("input", markFiltersDirty);
elements.reset.addEventListener("click", () => {
  elements.status.value = "";
  elements.condition.value = "";
  elements.updatedSince.value = "";
  elements.appRestore.checked = false;
  elements.areaMin.value = "";
  elements.areaMax.value = "";
  clearSelectedArea();
  markFiltersDirty();
  runSearch(1);
});
elements.drawButton.addEventListener("click", () => {
  if (!state.drawing) {
    clearSelectedArea();
    state.drawing = true;
  } else {
    stopDrawing();
    return;
  }
  elements.drawButton.classList.toggle("active", state.drawing);
  elements.drawButton.setAttribute("aria-pressed", String(state.drawing));
  elements.drawButton.innerHTML = state.drawing
    ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>Cancelar desenho'
    : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16v16H4z" stroke-dasharray="3 2"></path><path d="M8 4v4M16 4v4M4 8h4M4 16h4"></path></svg>Desenhar retângulo';
  elements.drawHint.hidden = !state.drawing;
  elements.mapPanel.classList.toggle("is-drawing", state.drawing);
  state.map.dragging.enable();
  if (state.drawing) showNotice("Arraste o mouse sobre o mapa para desenhar um retângulo.");
});
elements.clearArea.addEventListener("click", () => {
  clearSelectedArea();
  markFiltersDirty();
  runSearch(1);
});
elements.previous.addEventListener("click", () => runSearch(Math.max(1, state.page - 1)));
elements.next.addEventListener("click", () => runSearch(Math.min(state.pages, state.page + 1)));
elements.exportCsv.addEventListener("click", () => exportResults("csv"));
elements.exportGeojson.addEventListener("click", () => exportResults("geojson"));
elements.propertyDialogClose.addEventListener("click", () => elements.propertyDialog.close());
elements.propertyDialog.addEventListener("click", (event) => {
  if (event.target === elements.propertyDialog) elements.propertyDialog.close();
});
