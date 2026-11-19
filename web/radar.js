/* Radar da Fila do CAR: lê apenas as rotas do índice local. */
(() => {
  const raiz = document.getElementById("view-radar");
  if (!raiz) return;

  const CONDICOES = [
    ["aguardando_analise", "Aguardando análise"],
    ["em_analise", "Em análise"],
    ["analisado_notificacao", "Aguardando atendimento"],
    ["analisado_regularizacao", "Aguardando regularização"],
    ["analisado_conforme", "Em conformidade"],
    ["cancelado", "Cancelado"],
    ["outro", "Outra condição"],
  ];
  const FAIXAS = [["ate_1", "Até 1 ano"], ["1_3", "1 a 3 anos"], ["3_5", "3 a 5 anos"], ["5_10", "5 a 10 anos"], ["10_mais", "10 anos ou mais"]];
  const RANKINGS = {
    sem_analise: ["Sem análise", (m) => numero(m.sem_analise)],
    sem_analise_pct: ["% sem análise", (m) => `${decimal(m.sem_analise_pct)}%`],
    fila_5_anos: ["Há 5 anos ou mais", (m) => numero(m.fila_5_anos)],
    idade_mediana_anos: ["Mediana (anos)", (m) => decimal(m.idade_mediana_anos)],
  };
  const r = {
    uf: "", ibge: null, estados: [], municipios: [], perfis: [], resumo: null, mapa: null, camada: null,
    filtros: {}, pagina: 1, paginas: 0, ranking: "sem_analise", iniciado: false, pendente: null,
  };

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const numero = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("pt-BR"));
  const decimal = (v, d = 1) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const dataBr = (v) => (v ? new Date(v.length === 10 ? `${v}T12:00:00` : v).toLocaleDateString("pt-BR") : "—");
  const dataHora = (v) => (v ? new Date(v).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—");
  const $ = (id) => raiz.querySelector(`#${id}`);

  async function api(caminho) {
    const resposta = await fetch(caminho);
    const dados = await resposta.json();
    if (!resposta.ok) throw new Error(dados.detail || "Não foi possível carregar os dados.");
    return dados;
  }
  const consulta = (extra = {}) => {
    const p = new URLSearchParams({ uf: r.uf });
    if (r.ibge) p.set("ibge", r.ibge);
    for (const [chave, valor] of Object.entries({ ...r.filtros, ...extra })) {
      if (valor === undefined || valor === null || valor === "" || valor === false) continue;
      p.set(chave, Array.isArray(valor) ? valor.join(",") : valor);
    }
    return p.toString();
  };

  raiz.innerHTML = `
    <header class="radar-head">
      <div><p class="eyebrow">RADAR DA FILA DO CAR</p><h1 id="radar-titulo">Onde a análise do CAR está parada</h1><p id="radar-sync" class="radar-sync">Carregando o índice…</p></div>
      <div class="radar-seletores">
        <label>Estado<select id="radar-uf"></select></label>
        <label>Município<select id="radar-municipio"></select></label>
      </div>
    </header>
    <div id="radar-vazio" class="radar-card radar-vazio" hidden></div>
    <div id="radar-conteudo" hidden>
      <section class="radar-kpis" id="radar-kpis" aria-label="Indicadores principais"></section>
      <section class="radar-grade">
        <article class="radar-card"><h2>Em que etapa estão os cadastros</h2><p class="radar-nota">Condição informada pelo SICAR.</p><div id="radar-funil"></div></article>
        <article class="radar-card"><h2>Há quanto tempo aguardam análise</h2><p class="radar-nota">Tempo desde a criação do cadastro, uma aproximação do tempo de fila.</p><div id="radar-faixas"></div></article>
        <article class="radar-card radar-largo"><h2>Cadastros por ano de criação</h2><div class="radar-legenda"><span><i class="serie-a"></i>Sem análise concluída</span><span><i class="serie-b"></i>Demais</span></div><div id="radar-coortes" class="coortes"></div></article>
      </section>
      <section class="radar-territorio">
        <article class="radar-card radar-mapa-card"><h2>Municípios com mais cadastros sem análise</h2><p class="radar-nota">O tamanho do círculo acompanha a quantidade. Clique para filtrar.</p><div id="radar-mapa"></div></article>
        <article class="radar-card"><div class="radar-titulo-linha"><h2>Ranking</h2><label class="sr-only" for="radar-ranking">Ordenar ranking</label><select id="radar-ranking"></select></div><div class="radar-tabela curta"><table><thead><tr><th>Município</th><th id="radar-ranking-col" class="num"></th></tr></thead><tbody id="radar-ranking-corpo"></tbody></table></div></article>
      </section>
      <section class="radar-card">
        <div class="radar-titulo-linha"><div><h2>Perfis</h2><p class="radar-nota">Selecione um ou mais. A lista mostra imóveis com todos os perfis marcados.</p></div><button id="radar-limpar" class="secondary-button" type="button">Limpar filtros</button></div>
        <div id="radar-perfis"></div>
        <details class="radar-regras"><summary>Como cada perfil é calculado</summary><div class="radar-tabela"><table><thead><tr><th>Perfil</th><th>Regra</th><th>Fonte</th><th class="num">Peso</th></tr></thead><tbody id="radar-regras"></tbody></table></div></details>
      </section>
      <section class="radar-card" id="radar-lista">
        <div class="radar-titulo-linha"><div><h2>Fila de imóveis</h2><p id="radar-fila-total" class="radar-nota"></p></div><button id="radar-csv" class="secondary-button" type="button">Baixar CSV</button></div>
        <div class="radar-filtros">
          <label>Condição<select id="f-condicao"><option value="">Todas</option>${CONDICOES.map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}</select></label>
          <label>Situação<select id="f-status"><option value="">Todas</option><option value="AT">Ativo</option><option value="PE">Pendente</option><option value="SU">Suspenso</option><option value="CA">Cancelado</option></select></label>
          <label>Tipo<select id="f-tipo"><option value="">Todos</option><option value="IRU">Imóvel rural</option><option value="AST">Assentamento</option><option value="PCT">Povos e comunidades</option></select></label>
          <label>Criado há<select id="f-anos"><option value="">Qualquer tempo</option><option value="1">1 ano ou mais</option><option value="3">3 anos ou mais</option><option value="5">5 anos ou mais</option><option value="10">10 anos ou mais</option></select></label>
          <label>Ordem<select id="f-ordem"><option value="prioridade">Prioridade sugerida</option><option value="antiguidade">Mais antigos</option><option value="area">Maiores áreas</option></select></label>
        </div>
        <p id="radar-erro" class="radar-erro" role="alert" hidden></p>
        <div class="radar-tabela"><table><thead><tr><th class="num">Prioridade</th><th>Código CAR</th><th>Município</th><th>Condição</th><th class="num">Área (ha)</th><th class="num">Anos</th><th class="num">Perfis</th></tr></thead><tbody id="radar-fila"></tbody></table></div>
        <div class="pagination"><span id="radar-pagina">—</span><div><button id="radar-ant" class="page-button" type="button">← Anterior</button><button id="radar-prox" class="page-button" type="button">Próxima →</button></div></div>
        <p class="radar-nota" id="radar-aviso"></p>
      </section>
      <section class="radar-grade">
        <article class="radar-card"><h2>Evolução da fila</h2><div id="radar-evolucao"></div></article>
        <article class="radar-card"><h2>Padrões encontrados</h2><p class="radar-nota" id="radar-grupos-nota"></p><div id="radar-grupos"></div></article>
      </section>
    </div>
    <div id="radar-tip" class="radar-tip" hidden></div>`;

  const tip = $("radar-tip");
  raiz.addEventListener("mousemove", (e) => {
    const alvo = e.target.closest("[data-tip]");
    if (!alvo) { tip.hidden = true; return; }
    tip.textContent = alvo.dataset.tip;
    tip.hidden = false;
    tip.style.left = `${Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8)}px`;
    tip.style.top = `${e.clientY + 14}px`;
  });
  raiz.addEventListener("mouseleave", () => { tip.hidden = true; });

  function barras(itens) {
    const maximo = Math.max(1, ...itens.map((i) => i.valor));
    const total = itens.reduce((s, i) => s + i.valor, 0) || 1;
    return `<div class="barras">${itens.map((i) => `
      <div class="barra" data-tip="${esc(i.rotulo)}: ${numero(i.valor)} (${decimal(100 * i.valor / total)}%)">
        <span class="barra-nome">${esc(i.rotulo)}</span>
        <span class="barra-trilho"><i style="width:${Math.max(i.valor ? 0.6 : 0, 100 * i.valor / maximo)}%"></i></span>
        <b>${numero(i.valor)}</b>
      </div>`).join("")}</div>`;
  }

  function coortes(lista) {
    const dados = lista.filter((c) => c.total);
    if (!dados.length) return '<p class="radar-nota">Sem datas de criação disponíveis.</p>';
    const maximo = Math.max(...dados.map((c) => c.total));
    return dados.map((c) => {
      const sem = c.sem_analise || 0;
      return `<div class="coorte" data-tip="${c.ano}: ${numero(c.total)} cadastros, ${numero(sem)} sem análise">
        <div class="coorte-coluna" style="height:${100 * c.total / maximo}%"><i class="serie-b" style="flex:${c.total - sem}"></i><i class="serie-a" style="flex:${sem}"></i></div>
        <span>${String(c.ano).slice(2)}</span></div>`;
    }).join("");
  }

  function renderResumo() {
    const d = r.resumo;
    const p = d.perfis || {};
    const nome = r.ibge ? d.nome : (r.estados.find((e) => e.uf === r.uf)?.nome ?? r.uf);
    $("radar-titulo").textContent = `Fila do CAR: ${nome}`;
    const kpi = (rotulo, valor, detalhe) => `<div class="radar-kpi"><span>${rotulo}</span><strong>${valor}</strong><small>${detalhe}</small></div>`;
    $("radar-kpis").innerHTML = [
      kpi("Imóveis no índice", numero(d.total), `${numero(Math.round(d.area_ha))} ha declarados`),
      kpi("Sem análise concluída", numero(d.sem_analise), `${decimal(d.sem_analise_pct)}% dos cadastros`),
      kpi("Mediana desde a criação", d.idade_mediana_anos === null ? "—" : `${decimal(d.idade_mediana_anos)} anos`, `90% até ${decimal(d.idade_p90_anos)} anos`),
      kpi("Na fila há 5 anos ou mais", numero(p.fila_5_anos || 0), `${numero(p.fila_10_anos || 0)} há 10 anos ou mais`),
      kpi("Com APP a recompor", numero(p.app_recompor || 0), "Camadas da Consulta Pública"),
    ].join("");
    $("radar-funil").innerHTML = barras(CONDICOES.map(([v, t]) => ({ rotulo: t, valor: d.condicoes[v] || 0 })).filter((i) => i.valor));
    $("radar-faixas").innerHTML = barras(FAIXAS.map(([v, t]) => ({ rotulo: t, valor: d.faixas_fila[v] || 0 })));
    $("radar-coortes").innerHTML = coortes(d.coortes);
    $("radar-aviso").textContent = d.aviso;
    renderPerfis();
  }

  function renderPerfis() {
    const totais = r.resumo?.perfis || {};
    const marcados = r.filtros.perfis || [];
    const grupos = {};
    for (const perfil of r.perfis) (grupos[perfil.grupo] ||= []).push(perfil);
    $("radar-perfis").innerHTML = Object.entries(grupos).map(([grupo, itens]) => `
      <div class="perfil-grupo"><span>${esc(grupo)}</span><div>${itens.map((p) => `
        <button type="button" class="perfil${marcados.includes(p.codigo) ? " ativo" : ""}" data-perfil="${p.codigo}" aria-pressed="${marcados.includes(p.codigo)}" ${totais[p.codigo] ? "" : "disabled"}>${esc(p.rotulo)} <b>${numero(totais[p.codigo] || 0)}</b></button>`).join("")}</div></div>`).join("");
  }

  function renderRanking() {
    const [rotulo, formato] = RANKINGS[r.ranking];
    $("radar-ranking-col").textContent = rotulo;
    const lista = [...r.municipios].sort((a, b) => (b[r.ranking] ?? -1) - (a[r.ranking] ?? -1)).slice(0, 20);
    $("radar-ranking-corpo").innerHTML = lista.map((m) => `<tr class="${m.ibge === r.ibge ? "selecionado" : ""}"><td><button type="button" class="link-tabela" data-ibge="${m.ibge}">${esc(m.municipio)}</button></td><td class="num">${formato(m)}</td></tr>`).join("");
  }

  function renderMapa() {
    if (!r.mapa && window.L && raiz.offsetParent !== null) {
      r.mapa = L.map($("radar-mapa"), { preferCanvas: true, scrollWheelZoom: false }).setView([-5, -45], 6);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 12, attribution: "&copy; OpenStreetMap" }).addTo(r.mapa);
      r.camada = L.layerGroup().addTo(r.mapa);
    }
    if (!r.mapa) return;
    r.mapa.invalidateSize();
    r.camada.clearLayers();
    const pontos = r.municipios.filter((m) => m.lat !== null && m.lon !== null);
    const maximo = Math.max(1, ...pontos.map((m) => m.sem_analise));
    for (const m of pontos) {
      const ativo = m.ibge === r.ibge;
      L.circleMarker([m.lat, m.lon], {
        radius: 2 + 13 * Math.sqrt(m.sem_analise / maximo), weight: ativo ? 2.5 : 1,
        color: "#fff", fillColor: ativo ? "#c96f24" : "#16875f", fillOpacity: ativo ? 0.95 : 0.6,
      }).bindTooltip(`<strong>${esc(m.municipio)}</strong><br>${numero(m.sem_analise)} sem análise (${decimal(m.sem_analise_pct)}%)`)
        .on("click", () => escolherMunicipio(m.ibge)).addTo(r.camada);
    }
    if (pontos.length) r.mapa.fitBounds(pontos.map((m) => [m.lat, m.lon]), { padding: [24, 24], maxZoom: 9 });
  }

  function renderEvolucao(dados) {
    const serie = dados.serie.map((s) => ({ dia: s.dia, valor: s.condicoes.aguardando_analise || 0 }));
    if (serie.length < 2) {
      const dia = serie[0];
      $("radar-evolucao").innerHTML = `<p class="radar-destaque">${dia ? numero(dia.valor) : "—"}</p><p class="radar-nota">Cadastros aguardando análise em ${dia ? dataBr(dia.dia) : "—"}. A linha aparece a partir da segunda sincronização diária. ${esc(dados.aviso)}</p>`;
      return;
    }
    const L_ = 600, A = 180, m = 12;
    const valores = serie.map((s) => s.valor);
    const min = Math.min(...valores), max = Math.max(...valores), faixa = max - min || 1;
    const pts = serie.map((s, i) => [m + i * (L_ - 2 * m) / (serie.length - 1), A - m - (s.valor - min) * (A - 2 * m) / faixa, s]);
    $("radar-evolucao").innerHTML = `<svg viewBox="0 0 ${L_} ${A}" class="linha" role="img" aria-label="Evolução dos cadastros aguardando análise"><polyline points="${pts.map((p) => `${p[0]},${p[1]}`).join(" ")}"/>${pts.map((p) => `<circle cx="${p[0]}" cy="${p[1]}" r="5" data-tip="${dataBr(p[2].dia)}: ${numero(p[2].valor)}"/>`).join("")}</svg><p class="radar-nota">${dataBr(serie[0].dia)}: ${numero(serie[0].valor)} · ${dataBr(serie.at(-1).dia)}: ${numero(serie.at(-1).valor)}</p>`;
  }

  function renderGrupos(dados) {
    const q = dados.qualidade;
    $("radar-grupos-nota").textContent = q ? `${dados.aviso} Silhueta ${decimal(q.silhueta, 2)}; estabilidade entre execuções ${decimal(q.estabilidade_ari, 2)}.` : "Os padrões aparecem depois do processamento da base.";
    $("radar-grupos").innerHTML = dados.grupos.map((g) => `<button type="button" class="grupo${r.filtros.grupo === g.grupo ? " ativo" : ""}" data-grupo="${g.grupo}"><strong>${esc(g.rotulo)}</strong><span>${numero(g.total)} imóveis · mediana de ${decimal(g.area_mediana_ha)} ha e ${decimal(g.anos_medianos)} anos · ${decimal(g.sem_analise_pct, 0)}% sem análise</span></button>`).join("");
  }

  function linhaFila(item) {
    return `<tr class="fila-linha"><td class="num"><span class="prio">${item.prioridade_sugerida}</span></td>
      <td><button type="button" class="link-tabela codigo" data-abrir="${esc(item.codigo_car)}" aria-expanded="false">${esc(item.codigo_car)}</button></td>
      <td>${esc(item.municipio)}</td><td>${esc(item.condicao || "—")}</td><td class="num">${decimal(item.area_ha, 2)}</td><td class="num">${decimal(item.anos_desde_criacao)}</td><td class="num">${item.perfis.length}</td></tr>
      <tr class="fila-detalhe" hidden><td colspan="7"><ul>${item.perfis.map((p) => `<li><strong>${esc(p.rotulo)}</strong> (peso ${p.peso}): ${esc(p.motivo)} <em>Fonte: ${esc(p.fonte)}.</em></li>`).join("")}</ul>
      <p class="radar-nota">Situação: ${esc(item.situacao_rotulo)} · criado em ${dataBr(item.data_criacao)} · atualizado em ${dataBr(item.data_atualizacao)}${item.retificacoes === null ? "" : ` · ${item.retificacoes} retificações`}</p>
      ${typeof openPropertyDetails === "function" ? `<button type="button" class="secondary-button" data-cadastro="${esc(item.codigo_car)}">Ver cadastro e camadas no SICAR</button>` : ""}</td></tr>`;
  }

  async function carregarFila() {
    $("radar-erro").hidden = true;
    try {
      const d = await api(`/api/radar/fila?${consulta({ pagina: r.pagina, por_pagina: 25 })}`);
      r.paginas = d.paginas;
      $("radar-fila-total").textContent = `${numero(d.total)} imóveis neste recorte`;
      $("radar-fila").innerHTML = d.itens.map(linhaFila).join("") || '<tr class="empty-row"><td colspan="7">Nenhum imóvel com estes filtros.</td></tr>';
      $("radar-pagina").textContent = d.total ? `Página ${numero(d.pagina)} de ${numero(d.paginas)}` : "—";
      $("radar-ant").disabled = r.pagina <= 1;
      $("radar-prox").disabled = r.pagina >= d.paginas;
    } catch (erro) {
      $("radar-erro").textContent = erro.message;
      $("radar-erro").hidden = false;
    }
  }

  function sincronizarControles() {
    $("f-condicao").value = r.filtros.condicao || "";
    $("f-status").value = r.filtros.status || "";
    $("f-tipo").value = r.filtros.tipo || "";
    $("f-anos").value = r.filtros.anos_min ? String(r.filtros.anos_min) : "";
    $("f-ordem").value = r.filtros.ordem || "prioridade";
    $("radar-municipio").value = r.ibge || "";
  }

  async function carregarRecorte() {
    const [resumo, evolucao] = await Promise.all([
      api(`/api/radar/resumo?uf=${r.uf}${r.ibge ? `&ibge=${r.ibge}` : ""}`),
      api(`/api/radar/evolucao?uf=${r.uf}${r.ibge ? `&ibge=${r.ibge}` : ""}`),
    ]);
    r.resumo = resumo;
    if (!resumo.disponivel) return;
    renderResumo();
    renderEvolucao(evolucao);
    renderRanking();
    renderMapa();
    sincronizarControles();
    r.pagina = 1;
    await carregarFila();
  }

  function escolherMunicipio(ibge) {
    r.ibge = ibge || null;
    carregarRecorte().catch(mostrarErro);
  }

  function aplicarFiltro(alteracao) {
    Object.assign(r.filtros, alteracao);
    r.pagina = 1;
    renderPerfis();
    sincronizarControles();
    carregarFila();
  }

  function mostrarErro(erro) {
    $("radar-sync").textContent = erro.message || "Não foi possível carregar o Radar.";
  }

  async function carregarUf() {
    const [municipios, grupos] = await Promise.all([api(`/api/radar/municipios?uf=${r.uf}`), api(`/api/radar/grupos?uf=${r.uf}`)]);
    r.municipios = municipios.municipios;
    $("radar-municipio").innerHTML = `<option value="">Todo o estado</option>${r.municipios.map((m) => `<option value="${m.ibge}">${esc(m.municipio)}</option>`).join("")}`;
    r.grupos = grupos;
    renderGrupos(grupos);
    await carregarRecorte();
  }

  async function iniciar() {
    const [status, perfis, estados] = await Promise.all([api("/api/sincronizacao/status"), api("/api/perfis"), api("/api/radar/estados")]);
    r.perfis = perfis.perfis;
    $("radar-regras").innerHTML = r.perfis.map((p) => `<tr><td>${esc(p.rotulo)}</td><td>${esc(p.descricao)}</td><td>${esc(p.fonte)}</td><td class="num">${p.peso}</td></tr>`).join("");
    r.estados = estados.estados;
    const prontos = status.estados.filter((e) => e.resumo_em);
    if (!prontos.length) {
      $("radar-sync").textContent = "O índice ainda não foi carregado.";
      $("radar-vazio").hidden = false;
      $("radar-vazio").textContent = "Execute a sincronização para preencher o Radar. Consulte docs/operacao.md.";
      return;
    }
    $("radar-uf").innerHTML = prontos.map((e) => `<option value="${e.uf}">${esc(r.estados.find((x) => x.uf === e.uf)?.nome ?? e.uf)}</option>`).join("");
    r.uf = prontos[0].uf;
    $("radar-ranking").innerHTML = Object.entries(RANKINGS).map(([v, [t]]) => `<option value="${v}">${t}</option>`).join("");
    const e = prontos[0];
    const parcial = e.municipios && e.municipios_indexados < e.municipios ? ` · cobertura parcial: ${numero(e.municipios_indexados)} de ${numero(e.municipios)} municípios` : "";
    $("radar-sync").textContent = `Índice processado em ${dataHora(e.resumo_em)} · ${numero(e.imoveis)} imóveis${parcial} · abrir esta tela não chama o SICAR`;
    $("radar-conteudo").hidden = false;
    r.iniciado = true;
    if (r.pendente) { Object.assign(r, r.pendente); r.pendente = null; }
    await carregarUf();
  }

  raiz.addEventListener("click", (e) => {
    const perfil = e.target.closest("[data-perfil]");
    if (perfil) {
      const atuais = new Set(r.filtros.perfis || []);
      atuais.has(perfil.dataset.perfil) ? atuais.delete(perfil.dataset.perfil) : atuais.add(perfil.dataset.perfil);
      aplicarFiltro({ perfis: [...atuais] });
      return;
    }
    const municipio = e.target.closest("[data-ibge]");
    if (municipio) { escolherMunicipio(Number(municipio.dataset.ibge)); return; }
    const grupo = e.target.closest("[data-grupo]");
    if (grupo) {
      const valor = Number(grupo.dataset.grupo);
      aplicarFiltro({ grupo: r.filtros.grupo === valor ? undefined : valor });
      renderGrupos(r.grupos);
      $("radar-lista").scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    const abrir = e.target.closest("[data-abrir]");
    if (abrir) {
      const detalhe = abrir.closest("tr").nextElementSibling;
      detalhe.hidden = !detalhe.hidden;
      abrir.setAttribute("aria-expanded", String(!detalhe.hidden));
      return;
    }
    const cadastro = e.target.closest("[data-cadastro]");
    if (cadastro) openPropertyDetails(cadastro.dataset.cadastro);
  });
  $("radar-uf").addEventListener("change", (e) => { r.uf = e.target.value; r.ibge = null; r.filtros = {}; carregarUf().catch(mostrarErro); });
  $("radar-municipio").addEventListener("change", (e) => escolherMunicipio(Number(e.target.value) || null));
  $("radar-ranking").addEventListener("change", (e) => { r.ranking = e.target.value; renderRanking(); });
  [["f-condicao", "condicao"], ["f-status", "status"], ["f-tipo", "tipo"], ["f-anos", "anos_min"], ["f-ordem", "ordem"]].forEach(([id, chave]) => {
    $(id).addEventListener("change", (e) => aplicarFiltro({ [chave]: e.target.value || undefined }));
  });
  $("radar-limpar").addEventListener("click", () => { r.filtros = {}; aplicarFiltro({}); renderGrupos(r.grupos); });
  $("radar-ant").addEventListener("click", () => { r.pagina -= 1; carregarFila(); });
  $("radar-prox").addEventListener("click", () => { r.pagina += 1; carregarFila(); });
  $("radar-csv").addEventListener("click", async () => {
    const botao = $("radar-csv");
    botao.disabled = true;
    $("radar-erro").hidden = true;
    try {
      const resposta = await fetch(`/api/radar/fila/export?${consulta()}`);
      if (!resposta.ok) throw new Error((await resposta.json()).detail || "Não foi possível gerar o arquivo.");
      const link = document.createElement("a");
      link.href = URL.createObjectURL(await resposta.blob());
      link.download = `radar_car_${r.uf.toLowerCase()}${r.ibge ? `_${r.ibge}` : ""}.csv`;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (erro) {
      $("radar-erro").textContent = erro.message;
      $("radar-erro").hidden = false;
    } finally {
      botao.disabled = false;
    }
  });

  window.Radar = {
    uf: () => r.uf || "MA",
    visivel: () => { if (r.iniciado) renderMapa(); },
    aplicar(filtros) {
      const { ibge, ...resto } = filtros;
      if (!r.iniciado) { r.pendente = { ibge: ibge || null, filtros: resto }; return; }
      r.ibge = ibge || null;
      r.filtros = resto;
      carregarRecorte().then(() => { renderPerfis(); $("radar-lista").scrollIntoView({ block: "start" }); }).catch(mostrarErro);
    },
  };
  iniciar().catch(mostrarErro);
})();
