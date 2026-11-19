/* Radar da Fila do CAR: painel de tela única que lê apenas o índice local. */
(() => {
  const raiz = document.getElementById("view-radar");
  if (!raiz) return;

  /* ---------- Formatação ---------- */
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const numero = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("pt-BR"));
  const decimal = (v, casas = 1) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas }));
  const pct = (parte, todo) => (todo ? (100 * parte) / todo : 0);
  const pctTexto = (parte, todo) => { const v = pct(parte, todo); return v > 0 && v < 0.1 ? "<0,1" : decimal(v); };
  const compacto = (v) => (v >= 1e6 ? `${decimal(v / 1e6, 1)} mi` : v >= 1e4 ? `${decimal(v / 1e3, 0)} mil` : numero(v));
  const hectares = (v) => (v >= 1e6 ? `${decimal(v / 1e6, 2)} milhões de ha` : v >= 1e3 ? `${decimal(v / 1e3, 1)} mil ha` : `${decimal(v, 0)} ha`);
  const dataBr = (v) => (v ? new Date(String(v).length === 10 ? `${v}T12:00:00` : v).toLocaleDateString("pt-BR") : "—");
  const dataHora = (v) => (v ? new Date(v).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—");
  const diasAtras = (dias) => new Date(Date.now() - dias * 864e5).toISOString().slice(0, 10);
  const $ = (id) => raiz.querySelector(`#${id}`);

  /* ---------- Vocabulário ---------- */
  const ETAPAS = [
    ["aguardando_analise", "Aguardando análise", "Ainda não foi analisado pelo órgão estadual."],
    ["em_analise", "Em análise", "O órgão estadual está analisando."],
    ["analisado_notificacao", "Aguardando resposta do produtor", "Analisado; o produtor precisa responder a uma notificação."],
    ["analisado_regularizacao", "Aguardando regularização", "Analisado; precisa regularizar a situação ambiental."],
    ["analisado_conforme", "Em conformidade", "Analisado e em conformidade com o Código Florestal."],
    ["cancelado", "Cancelado", "Cadastro cancelado."],
    ["outro", "Outra condição", "Condição do SICAR fora das etapas acima."],
  ];
  const ETAPA = Object.fromEntries(ETAPAS.map(([v, t]) => [v, t]));
  const FAIXAS = [["ate_1", "Menos de 1 ano", "<1"], ["1_3", "1 a 3 anos", "1–3"], ["3_5", "3 a 5 anos", "3–5"], ["5_10", "5 a 10 anos", "5–10"], ["10_mais", "10 anos ou mais", "10+"]];
  const PRIORIDADES = [["0_24", "0–24", "#d3eadb"], ["25_49", "25–49", "#8cc5a0"], ["50_74", "50–74", "#3f9a6c"], ["75_100", "75–100", "#155f43"]];
  const SITUACOES = [["AT", "Ativo"], ["PE", "Pendente"], ["SU", "Suspenso"], ["CA", "Cancelado"]];
  const TIPOS = [["IRU", "Imóvel rural"], ["AST", "Assentamento"], ["PCT", "Povos e comunidades tradicionais"]];
  const TEMPOS = [[1, "1 ano ou mais"], [3, "3 anos ou mais"], [5, "5 anos ou mais"], [10, "10 anos ou mais"]];
  const TAMANHOS = [["0-50", "Até 50 ha", 0, 50], ["50-500", "50 a 500 ha", 50, 500], ["500-", "Acima de 500 ha", 500, null]];
  const MUDANCAS = [
    ["analisado_desde", "Concluíram análise nos últimos 30 dias", "Concluíram análise"],
    ["alterado_desde", "Mudaram de etapa nos últimos 30 dias", "Mudaram de etapa"],
    ["atualizado_desde", "Atualizados no SICAR nos últimos 30 dias", "Atualizados no SICAR"],
  ];
  const AMBIENTAIS = ["app_recompor", "sobre_embargo", "sobre_indigena", "sobre_uc", "sobre_quilombo", "sobre_uniao"];
  const OUTROS_PERFIS = ["retorno_revisao", "acima_15_modulos", "retificado_3x", "area_atipica"];
  const ATALHOS = [
    { id: "parados", titulo: "Parados há 5 anos ou mais", texto: "Cadastros sem análise criados há pelo menos 5 anos.", filtros: { perfis: ["fila_5_anos"] } },
    { id: "app", titulo: "Com área a recompor", texto: "Imóveis em camadas oficiais de APP a recompor.", filtros: { perfis: ["app_recompor"] } },
    { id: "mes", titulo: "Analisados no último mês", texto: "Concluíram a análise nos últimos 30 dias.", filtros: { analisado_desde: "30" } },
    { id: "indigena", titulo: "Sobre terra indígena", texto: "Sobreposição oficial com terra indígena.", filtros: { perfis: ["sobre_indigena"] } },
    { id: "grandes", titulo: "Grandes imóveis na fila", texto: "Acima de 15 módulos fiscais e sem análise.", filtros: { perfis: ["sem_analise", "acima_15_modulos"] } },
    { id: "prioridade", titulo: "Maior prioridade sugerida", texto: "Prioridade de 75 a 100, pela soma dos perfis.", filtros: { prioridade_min: 75 } },
  ];
  const METRICAS = {
    recorte: ["Imóveis no recorte", (m) => m.total],
    sem_analise: ["Sem análise", (m) => m.sem_analise],
    sem_analise_pct: ["% sem análise", (m) => m.sem_analise_pct],
    fila_5_anos: ["Há 5 anos ou mais", (m) => m.fila_5_anos],
    idade_mediana_anos: ["Espera mediana (anos)", (m) => m.idade_mediana_anos],
  };

  /* ---------- Estado ---------- */
  const s = {
    uf: "", ibge: null, f: {}, pagina: 1, ordem: "prioridade", recorte: null, mapa: null,
    ranking: "municipios", metrica: "recorte", gaveta: null, etapa: "aguardando_analise", iniciado: false, pendente: null,
    base: { estados: [], perfis: [], perfil: {}, municipios: [], municipio: {}, glossario: {}, grupos: [], qualidade: null, aviso_grupos: "", status: null },
  };
  const abertas = new Set();
  let pedido = 0;

  async function api(caminho) {
    const resposta = await fetch(caminho);
    const dados = await resposta.json().catch(() => ({}));
    if (!resposta.ok) throw new Error(typeof dados.detail === "string" ? dados.detail : "Não foi possível carregar os dados.");
    return dados;
  }

  /* Datas "_desde" ficam como número de dias (atalhos) ou como data ISO (assistente). */
  const desde = (v) => (/^\d+$/.test(String(v)) ? diasAtras(Number(v)) : v);

  function parametros(extra = {}) {
    const p = new URLSearchParams({ uf: s.uf });
    if (s.ibge) p.set("ibge", s.ibge);
    const f = s.f;
    if (f.perfis?.length) p.set("perfis", f.perfis.join(","));
    for (const chave of ["condicao", "status", "tipo", "anos_min", "prioridade_min", "grupo", "area_min", "area_max"]) {
      if (f[chave] !== undefined && f[chave] !== null && f[chave] !== "") p.set(chave, f[chave]);
    }
    for (const [chave] of MUDANCAS) if (f[chave]) p.set(chave, desde(f[chave]));
    if (f.bbox) ["oeste", "sul", "leste", "norte"].forEach((c, i) => p.set(c, f.bbox[i]));
    for (const [chave, valor] of Object.entries(extra)) p.set(chave, valor);
    return p.toString();
  }

  function definir(alteracao) {
    Object.assign(s.f, alteracao);
    for (const [chave, valor] of Object.entries(s.f)) {
      if (valor === undefined || valor === null || valor === "" || (Array.isArray(valor) && !valor.length)) delete s.f[chave];
    }
    s.pagina = 1;
  }
  function alternarPerfil(codigo) {
    const atuais = new Set(s.f.perfis || []);
    atuais.has(codigo) ? atuais.delete(codigo) : atuais.add(codigo);
    definir({ perfis: [...atuais] });
  }

  function chips() {
    const f = s.f;
    const lista = [];
    if (s.ibge) lista.push({ chave: "ibge", texto: s.base.municipio[s.ibge]?.municipio || "Município" });
    if (f.bbox) lista.push({ chave: "bbox", texto: "Área do mapa" });
    for (const codigo of f.perfis || []) lista.push({ chave: `perfil:${codigo}`, texto: s.base.perfil[codigo]?.rotulo || codigo });
    if (f.condicao) lista.push({ chave: "condicao", texto: ETAPA[f.condicao] || f.condicao });
    if (f.anos_min) lista.push({ chave: "anos_min", texto: `Criado há ${f.anos_min}+ anos` });
    if (f.status) lista.push({ chave: "status", texto: `Situação: ${SITUACOES.find(([v]) => v === f.status)?.[1] || f.status}` });
    if (f.tipo) lista.push({ chave: "tipo", texto: TIPOS.find(([v]) => v === f.tipo)?.[1] || f.tipo });
    if (f.tamanho) lista.push({ chave: "tamanho", texto: TAMANHOS.find(([v]) => v === f.tamanho)?.[1] });
    else if (f.area_min || f.area_max) lista.push({ chave: "tamanho", texto: `Área ${f.area_min ? `de ${numero(f.area_min)}` : ""} ${f.area_max ? `até ${numero(f.area_max)}` : "ou mais"} ha` });
    if (f.prioridade_min) lista.push({ chave: "prioridade_min", texto: `Prioridade ${f.prioridade_min}+` });
    for (const [chave, , curto] of MUDANCAS) if (f[chave]) lista.push({ chave, texto: /^\d+$/.test(String(f[chave])) ? `${curto} em ${f[chave]} dias` : `${curto} desde ${dataBr(f[chave])}` });
    if (f.grupo !== undefined) lista.push({ chave: "grupo", texto: `Padrão: ${s.base.grupos.find((g) => g.grupo === Number(f.grupo))?.rotulo || f.grupo}` });
    return lista;
  }
  function removerChip(chave) {
    if (chave === "ibge") s.ibge = null;
    else if (chave.startsWith("perfil:")) alternarPerfil(chave.slice(7));
    else if (chave === "tamanho") definir({ tamanho: undefined, area_min: undefined, area_max: undefined });
    else definir({ [chave]: undefined });
  }

  function facetas(r = {}) {
    const f = s.f;
    const ativos = new Set(f.perfis || []);
    const conta = (obj, k) => (obj ? obj[k] ?? 0 : null);
    const perfil = (codigo) => ({ rotulo: s.base.perfil[codigo]?.rotulo || codigo, ativo: ativos.has(codigo), contagem: conta(r.perfis, codigo), acao: { tipo: "perfil", v: codigo } });
    return [
      { id: "etapa", titulo: "Etapa da análise", opcoes: ETAPAS.filter(([v]) => v !== "outro" || r.condicoes?.outro).map(([v, t]) => ({ rotulo: t, ativo: f.condicao === v, contagem: conta(r.condicoes, v), acao: { tipo: "campo", k: "condicao", v } })) },
      { id: "tempo", titulo: "Tempo desde a criação", opcoes: TEMPOS.map(([v, t]) => ({ rotulo: t, ativo: Number(f.anos_min) === v, acao: { tipo: "campo", k: "anos_min", v } })) },
      { id: "ambiental", titulo: "Ambiental e sobreposições", multipla: true, opcoes: AMBIENTAIS.map(perfil) },
      { id: "situacao", titulo: "Situação do cadastro", opcoes: SITUACOES.map(([v, t]) => ({ rotulo: t, ativo: f.status === v, contagem: conta(r.status, v), acao: { tipo: "campo", k: "status", v } })) },
      { id: "tipo", titulo: "Tipo de imóvel", opcoes: TIPOS.map(([v, t]) => ({ rotulo: t, ativo: f.tipo === v, acao: { tipo: "campo", k: "tipo", v } })) },
      { id: "tamanho", titulo: "Tamanho", opcoes: [...TAMANHOS.map(([v, t]) => ({ rotulo: t, ativo: f.tamanho === v, acao: { tipo: "tamanho", v } })), perfil("acima_15_modulos")] },
      { id: "prioridade", titulo: "Prioridade sugerida", opcoes: [25, 50, 75].map((v) => ({ rotulo: `${v} ou mais`, ativo: Number(f.prioridade_min) === v, acao: { tipo: "campo", k: "prioridade_min", v } })) },
      { id: "mudancas", titulo: "Mudanças recentes", opcoes: MUDANCAS.map(([k, t]) => ({ rotulo: t, ativo: Boolean(f[k]), acao: { tipo: "mudanca", k } })) },
      { id: "outros", titulo: "Outros perfis", multipla: true, opcoes: OUTROS_PERFIS.map(perfil) },
      ...(s.base.grupos.length ? [{ id: "padrao", titulo: "Padrão encontrado (K-Means)", opcoes: s.base.grupos.map((g) => ({ rotulo: g.rotulo, ativo: f.grupo !== undefined && Number(f.grupo) === g.grupo, contagem: g.total, acao: { tipo: "campo", k: "grupo", v: g.grupo } })) }] : []),
    ];
  }
  function aplicarOpcao(acao) {
    const f = s.f;
    if (acao.tipo === "perfil") alternarPerfil(acao.v);
    else if (acao.tipo === "campo") definir({ [acao.k]: String(f[acao.k]) === String(acao.v) ? undefined : acao.v });
    else if (acao.tipo === "tamanho") {
      const t = TAMANHOS.find(([v]) => v === acao.v);
      definir(f.tamanho === acao.v ? { tamanho: undefined, area_min: undefined, area_max: undefined } : { tamanho: acao.v, area_min: t[2] || undefined, area_max: t[3] ?? undefined });
    } else if (acao.tipo === "mudanca") {
      const ligado = Boolean(f[acao.k]);
      definir({ analisado_desde: undefined, alterado_desde: undefined, atualizado_desde: undefined, ...(ligado ? {} : { [acao.k]: "30" }) });
    }
  }
  const atalhoAtivo = () => ATALHOS.find((a) => JSON.stringify(Object.entries(a.filtros).sort()) === JSON.stringify(Object.entries(s.f).sort()))?.id || null;

  /* ---------- Estrutura ---------- */
  const tip = (...partes) => `data-tip="${esc(partes.filter((p) => p !== null && p !== undefined && p !== "").join("|"))}"`;
  const info = (termo) => `<button type="button" class="rd-info" data-termo="${esc(termo)}" aria-label="O que é ${esc(termo)}?">i</button>`;

  raiz.innerHTML = `
    <div class="rd-app">
      <aside class="rd-trilho" aria-label="Filtros do Radar">
        <div class="rd-trilho-topo"><strong>Filtros</strong><button type="button" class="rd-icone" id="rd-recolher" aria-label="Recolher filtros" title="Recolher filtros">«</button></div>
        <div class="rd-trilho-corpo">
          <label class="rd-campo">Estado<select id="rd-uf"></select></label>
          <label class="rd-campo">Município<select id="rd-municipio"><option value="">Todo o estado</option></select></label>
          <div id="rd-grupos"></div>
        </div>
        <div class="rd-trilho-pe">
          <button type="button" class="rd-botao-sec" id="rd-limpar">Limpar filtros</button>
          <button type="button" class="rd-origem" id="rd-origem" data-gaveta="dados"></button>
        </div>
      </aside>

      <section class="rd-painel" id="rd-painel" aria-live="polite">
        <div class="rd-faixa">
          <button type="button" class="rd-botao-sec" id="rd-abrir-trilho" hidden>Filtros</button>
          <div id="rd-chips" class="rd-chips"></div>
          <div class="rd-acoes">
            <button type="button" class="rd-botao-sec" data-gaveta="mudancas" title="Linha do tempo e mudanças registradas">Mudanças</button>
            <button type="button" class="rd-botao-sec" data-gaveta="dados" title="Sincronização, regras e qualidade dos dados">Sobre os dados</button>
            <button type="button" class="rd-botao-sec" id="rd-csv" title="Baixar a lista do recorte em CSV">CSV</button>
            <button type="button" class="rd-botao" data-gaveta="imoveis" id="rd-ver">Ver imóveis</button>
          </div>
        </div>
        <p id="rd-erro" class="rd-erro" role="alert" hidden></p>
        <div class="rd-kpis" id="rd-kpis"></div>
        <div class="rd-grade">
          <section class="rd-tile rd-t-mapa">
            <header><h2 id="rd-mapa-titulo">Onde estão</h2><button type="button" class="rd-mini" id="rd-area" title="Filtrar pelo que está visível no mapa">Filtrar área visível</button></header>
            <div id="rd-mapa" class="rd-mapa"></div>
            <p class="rd-mapa-nota" id="rd-mapa-nota"></p>
          </section>
          <section class="rd-tile"><header><h2>Etapa da análise ${info("Condição")}</h2></header><div id="rd-etapas" class="rd-corpo"></div></section>
          <section class="rd-tile"><header><h2>Tempo na fila</h2><span class="rd-leg"><i class="rd-cor-dado"></i>&lt;5 anos <i class="rd-cor-parado"></i>5+ anos</span></header><div id="rd-tempo" class="rd-corpo"></div></section>
          <section class="rd-tile"><header><h2>Cadastros por ano</h2><span class="rd-leg"><i class="rd-cor-parado"></i>Aguardando <i class="rd-cor-demais"></i>Demais</span></header><div id="rd-anos" class="rd-corpo"></div></section>
          <section class="rd-tile">
            <header>
              <div class="rd-alternar" role="tablist" aria-label="Ranking">
                <button type="button" role="tab" data-ranking="municipios" aria-selected="true">Municípios</button>
                <button type="button" role="tab" data-ranking="perfis" aria-selected="false">Perfis</button>
                <button type="button" role="tab" data-ranking="padroes" aria-selected="false">Padrões</button>
              </div>
              <select id="rd-metrica" class="rd-metrica" aria-label="Medida do ranking">${Object.entries(METRICAS).map(([v, [t]]) => `<option value="${v}">${t}</option>`).join("")}</select>
            </header>
            <div id="rd-ranking" class="rd-corpo"></div>
          </section>
        </div>
      </section>
    </div>

    <div class="rd-gaveta" id="rd-gaveta" role="dialog" aria-modal="true" aria-labelledby="rd-gaveta-titulo" hidden>
      <div class="rd-gaveta-cabeca">
        <div class="rd-alternar" role="tablist" aria-label="Painéis">
          <button type="button" role="tab" data-gaveta="imoveis">Imóveis</button>
          <button type="button" role="tab" data-gaveta="mudancas">Mudanças</button>
          <button type="button" role="tab" data-gaveta="dados">Sobre os dados</button>
        </div>
        <h2 id="rd-gaveta-titulo" class="sr-only">Detalhes do recorte</h2>
        <button type="button" class="rd-icone" id="rd-fechar" aria-label="Fechar">×</button>
      </div>
      <div class="rd-gaveta-corpo">
        <div data-painel="imoveis">
          <div class="rd-lista-topo"><p id="rd-lista-total" class="rd-nota"></p>
            <label class="rd-ordem">Ordenar<select id="rd-ordem"><option value="prioridade">Maior prioridade</option><option value="antiguidade">Mais antigos</option><option value="area">Maior área</option></select></label></div>
          <div id="rd-tabela"></div><div id="rd-paginas"></div><p class="rd-nota" id="rd-aviso"></p>
        </div>
        <div data-painel="mudancas">
          <div class="rd-lista-topo"><div><h3>Linha do tempo da fila</h3><p class="rd-nota" id="rd-historico-nota"></p></div>
            <label class="rd-ordem">Etapa<select id="rd-etapa">${ETAPAS.filter(([v]) => v !== "outro").map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}</select></label></div>
          <div id="rd-evolucao"></div>
          <h3 class="rd-sub">Mudanças registradas por dia</h3><div id="rd-movimentos"></div>
        </div>
        <div data-painel="dados">
          <div class="rd-lista-topo"><div><h3>Como estes dados chegam aqui</h3><p class="rd-nota">O Radar lê um índice local. Só a rotina abaixo consulta o SICAR, aos poucos e com limites.</p></div><span id="sync-ao-vivo" class="sync-ao-vivo" hidden>Atualizando</span></div>
          <div id="sync-kpis" class="sync-kpis"></div>
          <h3 class="sync-sub">Etapas da rotina</h3><ol id="sync-etapas" class="sync-etapas"></ol>
          <div class="sync-grade">
            <div><h3 class="sync-sub">Chamadas ao SICAR por dia</h3><div id="sync-dias"></div></div>
            <div><h3 class="sync-sub">Proteções</h3><ul id="sync-regras" class="sync-regras"></ul></div>
          </div>
          <h3 class="sync-sub">Últimas execuções</h3>
          <div class="radar-tabela sync-card"><table><thead><tr><th>Tarefa</th><th>Início</th><th class="num">Duração</th><th class="num">Chamadas</th><th class="num">Transferido</th><th class="num">Lidos</th><th class="num">Novos</th><th class="num">Alterados</th><th class="num">Removidos</th><th>Resultado</th></tr></thead><tbody id="sync-execucoes"></tbody></table></div>
          <h3 class="sync-sub">Como cada perfil é calculado</h3>
          <div class="radar-tabela"><table><thead><tr><th>Perfil</th><th>Regra</th><th>Fonte</th><th class="num">Peso</th></tr></thead><tbody id="rd-regras"></tbody></table></div>
          <h3 class="sync-sub">Padrões encontrados (K-Means)</h3><p class="rd-nota" id="rd-qualidade"></p>
        </div>
      </div>
    </div>
    <div class="rd-veu" id="rd-veu" hidden></div>
    <div class="rd-tip" id="rd-tip" role="tooltip" hidden></div>`;

  /* ---------- Filtros ---------- */
  function renderTrilho() {
    const ativo = atalhoAtivo();
    const r = s.recorte || {};
    const atalhos = `<details class="rd-grupo" data-id="atalhos" ${abertas.has("atalhos") ? "open" : ""}>
      <summary><span>Atalhos</span>${ativo ? '<b class="rd-contador">1</b>' : ""}</summary>
      <div class="rd-atalhos">${ATALHOS.map((a) => `<button type="button" class="rd-atalho${ativo === a.id ? " ativo" : ""}" data-atalho="${a.id}" aria-pressed="${ativo === a.id}" ${tip(a.titulo, a.texto)}>${esc(a.titulo)}</button>`).join("")}</div></details>`;
    $("rd-grupos").innerHTML = atalhos + facetas(r).map((g) => {
      const n = g.opcoes.filter((o) => o.ativo).length;
      return `<details class="rd-grupo" data-id="${g.id}" ${abertas.has(g.id) ? "open" : ""}>
        <summary><span>${esc(g.titulo)}</span>${n ? `<b class="rd-contador">${n}</b>` : ""}</summary>
        <div class="rd-opcoes">${g.opcoes.map((o) => `<button type="button" class="rd-opcao${o.ativo ? " ativa" : ""}${o.contagem === 0 && !o.ativo ? " zerada" : ""}" role="${g.multipla ? "checkbox" : "radio"}" aria-checked="${o.ativo}" data-acao='${esc(JSON.stringify(o.acao))}'>
          <span class="rd-marcador" aria-hidden="true"></span><span class="rd-opcao-rotulo">${esc(o.rotulo)}</span>${o.contagem !== null && o.contagem !== undefined ? `<span class="rd-opcao-n">${compacto(o.contagem)}</span>` : ""}</button>`).join("")}</div></details>`;
    }).join("");
  }

  function renderFaixa() {
    const lista = chips();
    const nomeUf = s.base.estados.find((e) => e.uf === s.uf)?.nome || s.uf;
    $("rd-chips").innerHTML = lista.length
      ? `${lista.map((c) => `<span class="rd-chip">${esc(c.texto)}<button type="button" data-chip="${esc(c.chave)}" aria-label="Remover ${esc(c.texto)}">×</button></span>`).join("")}<button type="button" class="rd-link" data-limpar>Limpar</button>`
      : `<span class="rd-sem-filtro">Todos os imóveis do ${esc(nomeUf)}</span>`;
    const n = lista.filter((c) => c.chave !== "ibge").length;
    $("rd-abrir-trilho").textContent = n ? `Filtros (${n})` : "Filtros";
    $("rd-municipio").value = s.ibge || "";
  }

  /* ---------- Indicadores e gráficos ---------- */
  function renderKpis(r) {
    const p = r.perfis || {};
    const prio = PRIORIDADES.map(([k, rot, cor]) => `<i style="flex:${r.faixas_prioridade[k] || 0};background:${cor}" ${tip(`Prioridade ${rot}`, `${numero(r.faixas_prioridade[k] || 0)} imóveis`, `${pctTexto(r.faixas_prioridade[k] || 0, r.total)}% do recorte`)}></i>`).join("");
    $("rd-kpis").innerHTML = `
      <div class="rd-kpi" ${tip("Imóveis no recorte", `${numero(r.total)} imóveis`, `${hectares(r.area_ha || 0)} declarados`, `${numero(r.municipios_no_recorte)} municípios`)}>
        <span>Imóveis</span><strong>${numero(r.total)}</strong></div>
      <div class="rd-kpi" ${tip("Sem análise concluída", `${numero(r.sem_analise)} imóveis`, `${decimal(r.sem_analise_pct)}% do recorte`, "Condição informada pelo SICAR")}>
        <span>Aguardando análise</span><strong>${decimal(r.sem_analise_pct)}<small>%</small></strong><i class="rd-medidor"><b style="width:${r.sem_analise_pct || 0}%"></b></i></div>
      <div class="rd-kpi" ${tip("Espera mediana", "Tempo desde a criação, para quem aguarda análise", r.idade_p90_anos !== null ? `10% esperam ${decimal(r.idade_p90_anos)} anos ou mais` : "Nenhum aguardando análise")}>
        <span>Espera mediana</span><strong>${r.idade_mediana_anos !== null ? decimal(r.idade_mediana_anos) : "—"}<small> anos</small></strong></div>
      <div class="rd-kpi" ${tip("Na fila há 5 anos ou mais", `${numero(p.fila_5_anos || 0)} imóveis`, `${numero(p.fila_10_anos || 0)} há 10 anos ou mais`)}>
        <span>Na fila há 5+ anos</span><strong>${compacto(p.fila_5_anos || 0)}</strong></div>
      <div class="rd-kpi" ${tip("APP a recompor", `${numero(p.app_recompor || 0)} imóveis`, `${pctTexto(p.app_recompor || 0, r.total)}% do recorte`, "Camadas oficiais da Consulta Pública")}>
        <span>APP a recompor</span><strong>${compacto(p.app_recompor || 0)}</strong></div>
      <div class="rd-kpi rd-largo"><span>Prioridade sugerida ${info("Prioridade sugerida")}</span><div class="rd-pilha">${prio}</div><span class="rd-escala"><em>0</em><em>100</em></span></div>`;
  }

  function hbarras(itens, maior = Math.max(1, ...itens.map((i) => i.n))) {
    return `<div class="rd-hbarras">${itens.map((i) => `
      <button type="button" class="rd-hbarra${i.ativo ? " ativa" : ""}${i.n ? "" : " zero"}" ${i.attr} ${i.tip}>
        <span class="r">${esc(i.rotulo)}</span><span class="t"><i class="${i.classe || ""}" style="width:${(100 * i.n) / maior}%"></i></span><span class="n">${i.valor ?? compacto(i.n)}</span></button>`).join("")}</div>`;
  }

  function renderEtapas(r) {
    const itens = ETAPAS.filter(([v]) => v !== "outro" || r.condicoes.outro).map(([v, t, d]) => {
      const n = r.condicoes[v] || 0;
      return { rotulo: t, n, ativo: s.f.condicao === v, classe: v === "aguardando_analise" ? "parado" : "", attr: `data-etapa="${v}"`, tip: tip(t, `${numero(n)} imóveis · ${pctTexto(n, r.total)}%`, d, "Clique para filtrar") };
    });
    $("rd-etapas").innerHTML = hbarras(itens);
  }

  function colunas(itens, empilhado = false) {
    const maior = Math.max(1, ...itens.map((i) => i.total));
    return `<div class="rd-colunas">${itens.map((i) => `
      <div class="rd-col" ${i.tip}><div class="rd-col-area"><div class="rd-col-barra" style="height:${i.total ? Math.max(2, (100 * i.total) / maior) : 0}%">
        ${empilhado ? `<i class="rd-cor-demais" style="flex:${i.total - i.parado}"></i><i class="rd-cor-parado" style="flex:${i.parado}"></i>` : `<i class="${i.classe}" style="flex:1"></i>`}
      </div></div><span>${esc(i.rotulo)}</span></div>`).join("")}</div>`;
  }

  function renderTempo(r) {
    const soma = Object.values(r.faixas_fila).reduce((a, b) => a + b, 0);
    if (!soma) { $("rd-tempo").innerHTML = '<p class="rd-vazio">Nenhum imóvel aguardando análise.</p>'; return; }
    $("rd-tempo").innerHTML = colunas(FAIXAS.map(([k, t, curto]) => ({
      rotulo: curto, total: r.faixas_fila[k] || 0, classe: k === "5_10" || k === "10_mais" ? "rd-cor-parado" : "rd-cor-dado",
      tip: tip(t, `${numero(r.faixas_fila[k] || 0)} imóveis aguardando análise`, `${pctTexto(r.faixas_fila[k] || 0, soma)}% dos que aguardam`),
    }))) + '<p class="rd-eixo">anos desde a criação</p>';
  }

  function renderAnos(r) {
    const lista = r.coortes.filter((c) => c.total);
    $("rd-anos").innerHTML = lista.length ? colunas(lista.map((c) => ({
      rotulo: String(c.ano).slice(2), total: c.total, parado: c.sem_analise || 0,
      tip: tip(`Criados em ${c.ano}`, `${numero(c.total)} cadastros`, `${numero(c.sem_analise || 0)} aguardando análise (${pctTexto(c.sem_analise || 0, c.total)}%)`),
    })), true) : '<p class="rd-vazio">Sem datas de criação neste recorte.</p>';
  }

  function renderRanking() {
    const r = s.recorte;
    if (!r) return;
    raiz.querySelectorAll("[data-ranking]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.ranking === s.ranking)));
    $("rd-metrica").hidden = s.ranking !== "municipios" || Boolean(s.ibge);
    let itens;
    if (s.ranking === "municipios") {
      if (s.ibge) {
        const m = s.base.municipio[s.ibge] || {};
        $("rd-ranking").innerHTML = `<div class="rd-foco"><strong>${esc(m.municipio)}</strong><span>${numero(r.total)} imóveis no recorte</span>
          <span class="rd-nota">No município: ${numero(m.sem_analise)} sem análise (${decimal(m.sem_analise_pct)}%) · ${numero(m.fila_5_anos)} há 5+ anos · mediana ${decimal(m.idade_mediana_anos)} anos</span>
          <button type="button" class="rd-link" data-voltar-uf>Ver todos os municípios</button></div>`;
        return;
      }
      const [rotulo, valor] = METRICAS[s.metrica];
      const recorte = s.metrica === "recorte";
      const fonte = recorte ? r.municipios.map((m) => ({ ...s.base.municipio[m.ibge], ...m })) : s.base.municipios;
      const ordenados = [...fonte].filter((m) => valor(m) !== null && valor(m) !== undefined).sort((a, b) => valor(b) - valor(a)).slice(0, 8);
      const maior = Math.max(1, ...ordenados.map(valor));
      itens = ordenados.map((m) => ({
        rotulo: m.municipio, n: valor(m), attr: `data-rank="m:${m.ibge}"`,
        valor: s.metrica === "sem_analise_pct" ? `${decimal(m.sem_analise_pct)}%` : s.metrica === "idade_mediana_anos" ? decimal(m.idade_mediana_anos) : compacto(valor(m)),
        tip: tip(m.municipio, recorte ? `${numero(m.total)} imóveis no recorte` : `${rotulo}: ${s.metrica === "sem_analise_pct" ? `${decimal(m.sem_analise_pct)}%` : decimal(valor(m), Number.isInteger(valor(m)) ? 0 : 1)}`,
          `No município: ${numero(m.sem_analise)} sem análise (${decimal(m.sem_analise_pct)}%)`, `${numero(m.fila_5_anos)} há 5+ anos · mediana ${decimal(m.idade_mediana_anos)} anos`,
          recorte ? "" : "Medida sobre todo o índice, sem os demais filtros", "Clique para focar"),
      }));
      $("rd-ranking").innerHTML = hbarras(itens, maior);
      return;
    }
    if (s.ranking === "perfis") {
      const fora = new Set(["sem_analise", "em_analise", "analisado_conforme", "status_cancelado"]);
      itens = Object.entries(r.perfis).filter(([k, n]) => !fora.has(k) && n).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([k, n]) => {
        const p = s.base.perfil[k] || {};
        return { rotulo: p.rotulo || k, n, ativo: (s.f.perfis || []).includes(k), attr: `data-rank="p:${k}"`, tip: tip(p.rotulo || k, `${numero(n)} imóveis · ${pctTexto(n, r.total)}%`, p.descricao, `Peso ${p.peso ?? "—"} na prioridade`, "Clique para somar ao filtro") };
      });
    } else {
      itens = s.base.grupos.map((g) => ({
        rotulo: g.rotulo, n: g.total, ativo: s.f.grupo !== undefined && Number(s.f.grupo) === g.grupo, attr: `data-rank="g:${g.grupo}"`,
        tip: tip(g.rotulo, `${numero(g.total)} imóveis no estado`, `Área mediana ${decimal(g.area_mediana_ha)} ha · ${decimal(g.anos_medianos)} anos`, `${decimal(g.sem_analise_pct, 0)}% sem análise`, "Grupo do K-Means · clique para filtrar"),
      }));
    }
    $("rd-ranking").innerHTML = itens.length ? hbarras(itens) : '<p class="rd-vazio">Nada para mostrar neste recorte.</p>';
  }

  /* ---------- Mapa ---------- */
  const corPrioridade = (p) => (p >= 75 ? "#155f43" : p >= 50 ? "#3f9a6c" : p >= 25 ? "#8cc5a0" : "#d3eadb");
  let pedidoMapa = 0;

  async function renderMapa() {
    const r = s.recorte;
    if (!r || !window.L || raiz.offsetParent === null) return;
    if (!s.mapa) {
      s.mapa = L.map($("rd-mapa"), { preferCanvas: true, scrollWheelZoom: false }).setView([-5, -45], 6);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(s.mapa);
      s.camada = L.layerGroup().addTo(s.mapa);
    }
    s.mapa.invalidateSize();
    const meu = ++pedidoMapa;
    const nota = $("rd-mapa-nota");
    const nome = s.ibge ? s.base.municipio[s.ibge]?.municipio : null;
    if (s.ibge || s.f.bbox) {
      $("rd-mapa-titulo").textContent = nome ? `Imóveis de ${nome}` : "Imóveis na área do mapa";
      const dados = await api(`/api/radar/mapa?${parametros()}`).catch(() => ({ features: [] }));
      if (meu !== pedidoMapa) return;
      s.camada.clearLayers();
      if (dados.features.length) {
        const g = L.geoJSON(dados, {
          style: (f) => ({ color: "#fff", weight: 0.5, fillColor: corPrioridade(f.properties.prioridade), fillOpacity: 0.9 }),
          onEachFeature: (f, c) => c.bindTooltip(`${esc(f.properties.codigo)}<br>Prioridade ${f.properties.prioridade}`),
        }).addTo(s.camada);
        if (!s.f.bbox) s.mapa.fitBounds(g.getBounds(), { padding: [10, 10] });
        nota.innerHTML = `<span>${numero(dados.features.length)} limites${dados.truncado ? `, os ${numero(dados.limite)} de maior prioridade` : ""}</span><span class="rd-leg">${PRIORIDADES.map(([, rot, cor]) => `<i style="background:${cor}"></i>${rot}`).join(" ")}</span>`;
        return;
      }
      nota.textContent = "Os limites deste recorte ainda não estão no índice espacial; mostrando os municípios.";
    } else {
      $("rd-mapa-titulo").textContent = "Onde estão";
      nota.textContent = "Círculo proporcional aos imóveis do recorte. Clique para focar.";
    }
    s.camada.clearLayers();
    const lista = r.municipios.map((m) => ({ ...s.base.municipio[m.ibge], ...m })).filter((m) => m.lat !== null && m.lat !== undefined);
    const maior = Math.max(1, ...lista.map((m) => m.total));
    for (const m of lista) {
      const ativo = m.ibge === s.ibge;
      L.circleMarker([m.lat, m.lon], { radius: 3 + 16 * Math.sqrt(m.total / maior), color: "#fff", weight: ativo ? 2.5 : 1, fillColor: ativo ? "#c2692a" : "#245244", fillOpacity: 0.72 })
        .bindTooltip(`<strong>${esc(m.municipio)}</strong><br>${numero(m.total)} imóveis no recorte<br>${numero(m.sem_analise)} aguardando análise`)
        .on("click", () => { s.ibge = m.ibge; atualizar(); }).addTo(s.camada);
    }
    if (lista.length && !s.ibge && !s.f.bbox) s.mapa.fitBounds(lista.map((m) => [m.lat, m.lon]), { padding: [20, 20], maxZoom: 9 });
  }

  /* ---------- Gaveta: imóveis ---------- */
  const EVENTOS = { novo: "Entrou no SICAR", removido: "Saiu do SICAR", condicao: "Mudou de etapa", situacao: "Mudou de situação", cadastro: "Dados do cadastro alterados" };
  const podeConsultar = () => typeof openPropertyDetails === "function";

  function tabela(fila) {
    if (!fila.itens.length) return '<p class="rd-vazio">Nenhum imóvel neste recorte. Tente remover um filtro.</p>';
    return `<div class="radar-tabela rd-tabela"><table><thead><tr>
        <th class="num">Prioridade</th><th>Código CAR</th><th>Município</th><th>Etapa</th><th class="num">Área (ha)</th><th class="num">Anos</th><th>Perfis</th></tr></thead><tbody>
      ${fila.itens.map((i) => `
        <tr class="rd-linha" data-codigo="${esc(i.codigo_car)}" tabindex="0" aria-expanded="false">
          <td class="num"><span class="rd-prio" style="--p:${i.prioridade_sugerida}">${i.prioridade_sugerida}</span></td>
          <td class="codigo">${esc(i.codigo_car)}</td><td>${esc(i.municipio)}</td><td>${esc(ETAPA[i.condicao_grupo] || i.condicao || "—")}</td>
          <td class="num">${decimal(i.area_ha, 1)}</td><td class="num">${decimal(i.anos_desde_criacao)}</td>
          <td><span class="rd-perfis-mini">${i.perfis.slice(0, 2).map((p) => `<em>${esc(p.rotulo)}</em>`).join("")}${i.perfis.length > 2 ? `<em>+${i.perfis.length - 2}</em>` : ""}</span></td>
        </tr>
        <tr class="rd-detalhe" hidden><td colspan="7"><div class="rd-detalhe-grade">
          <div><h4>Por que tem prioridade ${i.prioridade_sugerida}</h4><ul class="rd-motivos">${i.perfis.map((p) => `<li><b>+${p.peso}</b><span><strong>${esc(p.rotulo)}</strong> ${esc(p.motivo)} <small>Fonte: ${esc(p.fonte)}</small></span></li>`).join("") || "<li><span>Nenhum perfil com peso.</span></li>"}</ul></div>
          <div><h4>Cadastro</h4><dl>
            <dt>Situação</dt><dd>${esc(i.situacao_rotulo)}</dd><dt>Condição no SICAR</dt><dd>${esc(i.condicao || "—")}</dd>
            <dt>Criado em</dt><dd>${dataBr(i.data_criacao)}</dd><dt>Atualizado em</dt><dd>${dataBr(i.data_atualizacao)}</dd>
            <dt>Módulos fiscais</dt><dd>${decimal(i.modulos_fiscais, 2)}</dd><dt>Retificações</dt><dd>${i.retificacoes === null ? "—" : numero(i.retificacoes)}</dd></dl>
            <div class="linha-cadastro" data-linha="${esc(i.codigo_car)}"></div>
            ${podeConsultar() ? `<button type="button" class="rd-botao-sec" data-cadastro="${esc(i.codigo_car)}">Ver cadastro e camadas no SICAR</button>` : ""}</div>
        </div></td></tr>`).join("")}</tbody></table></div>`;
  }

  async function carregarLinhaCadastro(alvo) {
    if (!alvo || alvo.dataset.carregado) return;
    alvo.dataset.carregado = "1";
    try {
      const d = await api(`/api/radar/imovel/${encodeURIComponent(alvo.dataset.linha)}`);
      const rotulo = (v) => d.condicoes_rotulos[v] || v || "—";
      const passos = [
        [d.data_criacao, "Inscrito no SICAR"],
        ...(d.no_indice_desde ? [[d.no_indice_desde, `No índice, com condição: ${esc(d.condicao || "—")}`]] : []),
        ...d.historico.map((h) => [h.dia, `${EVENTOS[h.evento] || h.evento}${h.evento === "condicao" ? `: ${esc(rotulo(h.condicao_anterior))} → ${esc(rotulo(h.condicao_nova))}` : h.evento === "situacao" ? `: ${esc(h.status_anterior)} → ${esc(h.status_novo)}` : ""}`]),
      ];
      alvo.innerHTML = `<h4>Linha do tempo do cadastro</h4><ol class="linha-eventos">${passos.map(([dia, texto]) => `<li><time>${dataBr(dia)}</time><span>${texto}</span></li>`).join("")}</ol>${d.area_limite_ha ? `<p class="rd-nota">Área do limite no índice espacial: ${decimal(d.area_limite_ha, 2)} ha.</p>` : ""}`;
    } catch {
      alvo.textContent = "";
    }
  }

  async function renderTabela() {
    const alvo = $("rd-tabela");
    alvo.classList.add("rd-carregando");
    try {
      const fila = await api(`/api/radar/fila?${parametros({ pagina: s.pagina, por_pagina: 25, ordem: s.ordem })}`);
      $("rd-lista-total").textContent = `${numero(fila.total)} imóveis · clique numa linha para ver os motivos e o histórico`;
      alvo.innerHTML = tabela(fila);
      $("rd-paginas").innerHTML = fila.paginas > 1 ? `<nav class="rd-paginacao" aria-label="Páginas"><button type="button" class="rd-botao-sec" data-pagina="${fila.pagina - 1}" ${fila.pagina <= 1 ? "disabled" : ""}>Anterior</button>
        <span>Página ${numero(fila.pagina)} de ${numero(fila.paginas)}</span><button type="button" class="rd-botao-sec" data-pagina="${fila.pagina + 1}" ${fila.pagina >= fila.paginas ? "disabled" : ""}>Próxima</button></nav>` : "";
    } catch (erro) {
      alvo.innerHTML = `<p class="rd-erro">${esc(erro.message)}</p>`;
    } finally {
      alvo.classList.remove("rd-carregando");
    }
  }

  /* ---------- Gaveta: mudanças ---------- */
  async function renderMudancas() {
    const dados = await api(`/api/radar/movimentos?uf=${s.uf}${s.ibge ? `&ibge=${s.ibge}` : ""}`).catch(() => null);
    if (!dados) { $("rd-evolucao").innerHTML = '<p class="rd-vazio">Não foi possível carregar o histórico.</p>'; return; }
    const onde = s.ibge ? s.base.municipio[s.ibge]?.municipio : "todo o estado";
    $("rd-historico-nota").textContent = `${dados.historico_desde ? `Mudanças registradas desde ${dataBr(dados.historico_desde)}` : "As mudanças passam a ser registradas na primeira atualização diária"} · ${onde}, sem os demais filtros.`;
    const nomeEtapa = ETAPA[s.etapa] || s.etapa;
    const serie = dados.etapas.map((x) => ({ dia: x.dia, valor: x.condicoes[s.etapa] || 0 }));
    if (serie.length < 2) {
      const dia = serie[0];
      $("rd-evolucao").innerHTML = `<p class="rd-destaque">${dia ? numero(dia.valor) : "—"}</p><p class="rd-nota">${esc(nomeEtapa)} em ${dia ? dataBr(dia.dia) : "—"}. A linha aparece a partir do segundo dia de sincronização.</p>`;
    } else {
      const L_ = 600, A = 160, m = 12;
      const valores = serie.map((x) => x.valor);
      const min = Math.min(...valores), faixa = Math.max(...valores) - min || 1;
      const pts = serie.map((x, i) => [m + (i * (L_ - 2 * m)) / (serie.length - 1), A - m - ((x.valor - min) * (A - 2 * m)) / faixa, x]);
      $("rd-evolucao").innerHTML = `<svg viewBox="0 0 ${L_} ${A}" class="rd-linha-svg" role="img" aria-label="Evolução da etapa ${esc(nomeEtapa)}"><polyline points="${pts.map((p) => `${p[0]},${p[1]}`).join(" ")}"/>${pts.map((p) => `<circle cx="${p[0]}" cy="${p[1]}" r="5" ${tip(dataBr(p[2].dia), `${numero(p[2].valor)} · ${nomeEtapa}`)}/>`).join("")}</svg>
        <p class="rd-nota">${dataBr(serie[0].dia)}: ${numero(serie[0].valor)} · ${dataBr(serie.at(-1).dia)}: ${numero(serie.at(-1).valor)}</p>`;
    }
    const cols = ["novo", "em_analise", "analisado", "aguardando_analise", "cancelado", "removido", "outro"];
    $("rd-movimentos").innerHTML = dados.movimentos.length
      ? `<div class="radar-tabela"><table><thead><tr><th>Dia</th>${cols.map((c) => `<th class="num">${esc(dados.rotulos[c])}</th>`).join("")}</tr></thead><tbody>${[...dados.movimentos].reverse().map((x) => `<tr><td>${dataBr(x.dia)}</td>${cols.map((c) => `<td class="num">${numero(x[c] || 0)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
      : '<p class="rd-nota">Nenhuma mudança registrada ainda neste território.</p>';
  }

  /* ---------- Gaveta: sobre os dados ---------- */
  const TAREFAS_ROTULO = { geometrias: "Limites dos imóveis", carga: "Carga", indicadores: "Indicadores", diario: "Atualização diária", conferencia: "Conferência", retificacoes: "Retificações" };
  const SITUACAO_SYNC = {
    em_dia: ["✓", "Em dia"], pendente: ["•", "Pendente"], em_andamento: ["↻", "Em andamento"],
    concluida: ["✓", "Concluída"], orcamento_esgotado: ["⏸", "Continua amanhã"], bloqueada: ["■", "Pausada pela fonte"], falhou: ["!", "Falhou"],
  };
  const mb = (bytes) => ((bytes || 0) < 1e6 ? `${numero(Math.round((bytes || 0) / 1e3))} KB` : `${decimal(bytes / 1e6)} MB`);
  const duracao = (inicio, fim) => {
    if (!inicio || !fim) return "—";
    const seg = Math.max(0, (new Date(fim) - new Date(inicio)) / 1000);
    return seg < 60 ? `${Math.round(seg)} s` : seg < 3600 ? `${Math.round(seg / 60)} min` : `${Math.floor(seg / 3600)} h ${Math.round((seg % 3600) / 60)} min`;
  };
  const selo = (codigo) => { const [icone, texto] = SITUACAO_SYNC[codigo] || ["•", codigo]; return `<span class="selo selo-${codigo}"><span aria-hidden="true">${icone}</span>${texto}</span>`; };
  const medidor = (valor, total) => `<span class="medidor"><i style="width:${Math.min(100, total ? (100 * valor) / total : 0)}%"></i></span>`;
  let relogioSync = null;

  function renderOrigem() {
    const status = s.base.status;
    const e = status?.estados.find((x) => x.uf === s.uf);
    if (!e) return;
    const parcial = e.municipios && e.municipios_indexados < e.municipios;
    $("rd-origem").innerHTML = `<span class="rd-ponto${status.execucoes.some((x) => x.ativa) ? " ativo" : ""}"></span><span><strong>Dados do SICAR até ${dataBr(e.marca)}</strong>
      <small>Índice de ${dataHora(e.resumo_em)}${parcial ? ` · ${numero(e.municipios_indexados)} de ${numero(e.municipios)} municípios` : ""} · esta tela não chama o SICAR</small></span>`;
  }

  function renderSync() {
    const status = s.base.status;
    const e = status?.estados.find((x) => x.uf === s.uf) || status?.estados[0];
    if (!e) return;
    const ativa = status.execucoes.some((x) => x.ativa);
    $("sync-ao-vivo").hidden = !ativa;
    const kpi = (rotulo, valor, detalhe, barra = "") => `<div class="radar-kpi"><span>${rotulo}</span><strong>${valor}</strong>${barra}<small>${detalhe}</small></div>`;
    $("sync-kpis").innerHTML = [
      kpi("Municípios carregados", `${numero(e.municipios_indexados)} de ${numero(e.municipios)}`, `${numero(e.imoveis)} imóveis no índice`, medidor(e.municipios_indexados, e.municipios)),
      kpi("Chamadas hoje", `${numero(status.hoje.chamadas)} de ${numero(status.hoje.orcamento)}`, `${mb(status.hoje.bytes)} transferidos hoje`, medidor(status.hoje.chamadas, status.hoje.orcamento)),
      kpi("Desde o início", `${numero(status.totais.chamadas)} chamadas`, `${mb(status.totais.bytes)} em ${numero(status.totais.execucoes)} execuções`),
      kpi("Índice espacial", `${numero(e.municipios_geometria)} de ${numero(e.municipios)}`, `${numero(e.geometrias)} limites de imóveis`, medidor(e.municipios_geometria, e.municipios)),
      kpi("Dados do SICAR até", dataBr(e.marca), e.ultimo_diario ? `Última atualização diária em ${dataBr(e.ultimo_diario)}` : "Aguardando a primeira atualização diária"),
    ].join("");
    $("sync-etapas").innerHTML = e.tarefas.map((t) => `<li class="etapa etapa-${t.situacao}">
      <div class="etapa-topo"><strong>${esc(t.rotulo)}</strong>${selo(t.situacao)}</div>
      <span>${t.frequencia_dias ? (t.frequencia_dias === 1 ? "Todo dia" : `A cada ${t.frequencia_dias} dias`) : "Uma vez"}</span>
      <span>Última: ${dataBr(t.ultima)}${t.proxima ? ` · Próxima: ${dataBr(t.proxima)}` : ""}</span></li>`).join("")
      + `<li class="etapa"><div class="etapa-topo"><strong>Recarga gradual</strong>${selo(e.recarga_feitos >= e.municipios ? "em_dia" : "pendente")}</div><span>Todo mês, por município</span><span>${e.municipios ? `${numero(e.recarga_feitos)} de ${numero(e.municipios)} municípios renovados neste mês` : ""}</span></li>`;
    const dias = status.por_dia;
    const maximo = Math.max(1, status.hoje.orcamento, ...dias.map((d) => d.chamadas));
    $("sync-dias").innerHTML = dias.length ? `<div class="sync-dias">${dias.map((d) => `<div class="sync-dia" ${tip(dataBr(d.dia), `${numero(d.chamadas)} chamadas`, mb(d.bytes))}><b>${numero(d.chamadas)}</b><div class="sync-dia-trilho"><i style="height:${Math.max(2, (100 * d.chamadas) / maximo)}%"></i></div><span>${dataBr(d.dia).slice(0, 5)}</span></div>`).join("")}</div><p class="rd-nota">A linha tracejada marca o orçamento de ${numero(status.hoje.orcamento)} chamadas por dia.</p>` : '<p class="rd-nota">Nenhuma execução nos últimos 14 dias.</p>';
    const regras = status.regras;
    $("sync-regras").innerHTML = [
      "Uma chamada por vez", `${numero(regras.intervalo_segundos)} segundos entre chamadas`, `Janela das ${regras.janela}`,
      `Até ${numero(regras.orcamento_diario)} chamadas por dia`, "Retoma do último município concluído", "Pausa automática se a fonte recusar acesso",
      `Até ${numero(regras.orcamento_mb_diario)} MB por dia`, "Limites dos imóveis em tarefa própria, de menor prioridade",
    ].map((t) => `<li><span aria-hidden="true">✓</span>${t}</li>`).join("");
    $("sync-execucoes").innerHTML = status.execucoes.map((x) => `<tr>
      <td>${esc(TAREFAS_ROTULO[x.tipo] || x.tipo)}${x.detalhe && x.detalhe !== x.tipo ? `<small class="sync-detalhe">${esc(x.detalhe)}</small>` : ""}</td>
      <td>${dataHora(x.iniciado_em)}</td><td class="num">${x.ativa ? "—" : duracao(x.iniciado_em, x.terminado_em)}</td>
      <td class="num">${numero(x.chamadas)}</td><td class="num">${mb(x.bytes)}</td><td class="num">${numero(x.registros)}</td>
      <td class="num">${numero(x.novos)}</td><td class="num">${numero(x.alterados)}</td><td class="num">${numero(x.removidos)}</td>
      <td>${selo(x.ativa ? "em_andamento" : x.status)}</td></tr>`).join("");
    $("rd-regras").innerHTML = s.base.perfis.map((p) => `<tr><td>${esc(p.rotulo)}</td><td>${esc(p.descricao)}</td><td>${esc(p.fonte)}</td><td class="num">${p.peso}</td></tr>`).join("");
    const q = s.base.qualidade;
    $("rd-qualidade").textContent = q ? `${s.base.aviso_grupos} Silhueta ${decimal(q.silhueta, 2)}; estabilidade entre execuções (ARI) ${decimal(q.estabilidade_ari, 2)}.` : "Os padrões aparecem depois do processamento da base.";
    clearTimeout(relogioSync);
    if (ativa) relogioSync = setTimeout(atualizarSync, 30000);
  }

  async function atualizarSync() {
    try {
      s.base.status = await api("/api/sincronizacao/status");
      renderOrigem();
      if (s.gaveta === "dados") renderSync();
    } catch { /* mantém o último estado exibido */ }
  }

  function abrirGaveta(qual) {
    s.gaveta = qual;
    $("rd-gaveta").hidden = !qual;
    $("rd-veu").hidden = !qual;
    if (!qual) return;
    raiz.querySelectorAll("#rd-gaveta [data-gaveta]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.gaveta === qual)));
    raiz.querySelectorAll("[data-painel]").forEach((p) => { p.hidden = p.dataset.painel !== qual; });
    if (qual === "imoveis") { renderTabela(); $("rd-aviso").textContent = s.recorte?.aviso || ""; }
    if (qual === "mudancas") renderMudancas();
    if (qual === "dados") renderSync();
    $("rd-fechar").focus();
  }

  /* ---------- Ciclo ---------- */
  async function atualizar() {
    const meu = ++pedido;
    renderFaixa();
    renderTrilho();
    $("rd-painel").classList.add("rd-carregando");
    $("rd-erro").hidden = true;
    try {
      const r = await api(`/api/radar/recorte?${parametros({ municipios: 300 })}`);
      if (meu !== pedido) return;
      s.recorte = r;
      renderTrilho();
      renderKpis(r);
      renderEtapas(r);
      renderTempo(r);
      renderAnos(r);
      renderRanking();
      $("rd-ver").textContent = `Ver ${compacto(r.total)} imóveis`;
      $("rd-csv").disabled = r.total > 50000 || !r.total;
      $("rd-csv").title = r.total > 50000 ? `O CSV aceita até 50.000 imóveis; filtre o recorte (hoje ${numero(r.total)}).` : "Baixar a lista do recorte em CSV";
      renderMapa();
      if (s.gaveta === "imoveis") { s.pagina = 1; renderTabela(); }
      if (s.gaveta === "mudancas") renderMudancas();
    } catch (erro) {
      $("rd-erro").textContent = erro.message;
      $("rd-erro").hidden = false;
    } finally {
      if (meu === pedido) $("rd-painel").classList.remove("rd-carregando");
    }
  }

  async function carregarUf() {
    const [municipios, grupos] = await Promise.all([api(`/api/radar/municipios?uf=${s.uf}`), api(`/api/radar/grupos?uf=${s.uf}`).catch(() => ({ grupos: [] }))]);
    s.base.municipios = municipios.municipios;
    s.base.municipio = Object.fromEntries(municipios.municipios.map((m) => [m.ibge, m]));
    s.base.grupos = grupos.grupos || [];
    s.base.qualidade = grupos.qualidade || null;
    s.base.aviso_grupos = grupos.aviso || "";
    $("rd-municipio").innerHTML = `<option value="">Todo o estado</option>${[...s.base.municipios].sort((a, b) => a.municipio.localeCompare(b.municipio, "pt-BR")).map((m) => `<option value="${m.ibge}">${esc(m.municipio)}</option>`).join("")}`;
    renderOrigem();
    await atualizar();
  }

  /* ---------- Dica flutuante e glossário ---------- */
  function ligarDica() {
    const caixa = $("rd-tip");
    let atual = null;
    const mostrar = (alvo, x, y) => {
      if (alvo !== atual) {
        atual = alvo;
        const [titulo, ...linhas] = alvo.dataset.tip.split("|");
        caixa.innerHTML = `<strong>${esc(titulo)}</strong>${linhas.map((l) => `<span>${esc(l)}</span>`).join("")}`;
        caixa.hidden = false;
      }
      const w = caixa.offsetWidth, h = caixa.offsetHeight;
      caixa.style.left = `${Math.max(8, Math.min(x + 14, innerWidth - w - 8))}px`;
      caixa.style.top = `${y + 16 + h > innerHeight ? y - h - 10 : y + 16}px`;
    };
    raiz.addEventListener("mousemove", (e) => {
      const alvo = e.target.closest("[data-tip]");
      if (alvo) mostrar(alvo, e.clientX, e.clientY);
      else if (atual) { atual = null; caixa.hidden = true; }
    });
    raiz.addEventListener("mouseleave", () => { atual = null; caixa.hidden = true; });
    raiz.addEventListener("focusin", (e) => {
      const alvo = e.target.closest("[data-tip]");
      if (alvo) { const b = alvo.getBoundingClientRect(); mostrar(alvo, b.left, b.bottom); }
    });
    raiz.addEventListener("focusout", () => { atual = null; caixa.hidden = true; });
  }

  let caixaInfo = null;
  function mostrarInfo(botao) {
    caixaInfo?.remove();
    const termo = botao.dataset.termo;
    caixaInfo = document.createElement("div");
    caixaInfo.className = "rd-info-caixa";
    caixaInfo.setAttribute("role", "tooltip");
    caixaInfo.innerHTML = `<strong>${esc(termo)}</strong><p>${esc(s.base.glossario[termo.toLowerCase()] || "Definição na aba Conhecimento.")}</p>`;
    document.body.append(caixaInfo);
    const b = botao.getBoundingClientRect();
    const largura = Math.min(300, innerWidth - 24);
    caixaInfo.style.width = `${largura}px`;
    caixaInfo.style.left = `${Math.max(12, Math.min(b.left - 12, innerWidth - largura - 12))}px`;
    caixaInfo.style.top = `${b.bottom + 8}px`;
  }
  document.addEventListener("click", (e) => { if (caixaInfo && !e.target.closest(".rd-info")) { caixaInfo.remove(); caixaInfo = null; } });

  async function baixarCsv(botao) {
    botao.disabled = true;
    $("rd-erro").hidden = true;
    try {
      const resposta = await fetch(`/api/radar/fila/export?${parametros({ ordem: s.ordem })}`);
      if (!resposta.ok) throw new Error((await resposta.json().catch(() => ({}))).detail || "Não foi possível gerar o arquivo.");
      const link = document.createElement("a");
      link.href = URL.createObjectURL(await resposta.blob());
      link.download = `radar_car_${s.uf.toLowerCase()}${s.ibge ? `_${s.ibge}` : ""}.csv`;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (erro) {
      $("rd-erro").textContent = erro.message;
      $("rd-erro").hidden = false;
    } finally {
      botao.disabled = false;
    }
  }

  function trilhoAberto(abrir) {
    const app = raiz.querySelector(".rd-app");
    const estreito = innerWidth <= 900;
    app.classList.toggle(estreito ? "trilho-aberto" : "trilho-recolhido", estreito ? abrir : !abrir);
    $("rd-abrir-trilho").hidden = !estreito && abrir;
    setTimeout(() => s.mapa?.invalidateSize(), 220);
  }

  /* ---------- Eventos ---------- */
  raiz.addEventListener("click", (e) => {
    const alvo = e.target;
    const el = (seletor) => alvo.closest(seletor);
    if (el(".rd-info")) { e.stopPropagation(); return mostrarInfo(el(".rd-info")); }
    if (el("[data-acao]")) { aplicarOpcao(JSON.parse(el("[data-acao]").dataset.acao)); return atualizar(); }
    if (el("[data-atalho]")) {
      const id = el("[data-atalho]").dataset.atalho;
      s.f = atalhoAtivo() === id ? {} : structuredClone(ATALHOS.find((a) => a.id === id).filtros);
      s.pagina = 1;
      return atualizar();
    }
    if (el("[data-chip]")) { removerChip(el("[data-chip]").dataset.chip); return atualizar(); }
    if (el("[data-limpar]") || alvo.id === "rd-limpar") { s.f = {}; s.ibge = null; s.pagina = 1; return atualizar(); }
    if (el("[data-etapa]")) { aplicarOpcao({ tipo: "campo", k: "condicao", v: el("[data-etapa]").dataset.etapa }); return atualizar(); }
    if (el("[data-rank]")) {
      const [tipo, valor] = el("[data-rank]").dataset.rank.split(":");
      if (tipo === "m") s.ibge = Number(valor);
      if (tipo === "p") alternarPerfil(valor);
      if (tipo === "g") aplicarOpcao({ tipo: "campo", k: "grupo", v: Number(valor) });
      return atualizar();
    }
    if (el("[data-ranking]")) { s.ranking = el("[data-ranking]").dataset.ranking; return renderRanking(); }
    if (el("[data-voltar-uf]")) { s.ibge = null; return atualizar(); }
    if (alvo.id === "rd-area" && s.mapa) {
      const b = s.mapa.getBounds();
      const fixo = (v) => Number(v.toFixed(5));
      definir({ bbox: [fixo(b.getWest()), fixo(b.getSouth()), fixo(b.getEast()), fixo(b.getNorth())] });
      return atualizar();
    }
    if (alvo.id === "rd-csv") return baixarCsv(alvo);
    if (el("[data-gaveta]")) return abrirGaveta(el("[data-gaveta]").dataset.gaveta);
    if (alvo.id === "rd-fechar" || alvo.id === "rd-veu") return abrirGaveta(null);
    if (el("[data-pagina]")) { s.pagina = Number(el("[data-pagina]").dataset.pagina); return renderTabela(); }
    if (el("[data-cadastro]")) return openPropertyDetails(el("[data-cadastro]").dataset.cadastro);
    const linha = el("tr.rd-linha");
    if (linha) {
      const detalhe = linha.nextElementSibling;
      detalhe.hidden = !detalhe.hidden;
      linha.setAttribute("aria-expanded", String(!detalhe.hidden));
      if (!detalhe.hidden) carregarLinhaCadastro(detalhe.querySelector("[data-linha]"));
      return;
    }
    if (alvo.id === "rd-recolher") return trilhoAberto(false);
    if (alvo.id === "rd-abrir-trilho") return trilhoAberto(innerWidth <= 900 ? !raiz.querySelector(".rd-app").classList.contains("trilho-aberto") : true);
  });
  raiz.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches("tr.rd-linha")) { e.preventDefault(); e.target.click(); }
    if (e.key === "Escape") { if (s.gaveta) abrirGaveta(null); caixaInfo?.remove(); caixaInfo = null; }
  });
  $("rd-grupos").addEventListener("toggle", (e) => {
    const d = e.target;
    if (d.open) abertas.add(d.dataset.id); else abertas.delete(d.dataset.id);
  }, true);
  $("rd-uf").addEventListener("change", (e) => { s.uf = e.target.value; s.ibge = null; s.f = {}; carregarUf().catch(mostrarErro); });
  $("rd-municipio").addEventListener("change", (e) => { s.ibge = Number(e.target.value) || null; atualizar(); });
  $("rd-metrica").addEventListener("change", (e) => { s.metrica = e.target.value; renderRanking(); });
  $("rd-ordem").addEventListener("change", (e) => { s.ordem = e.target.value; s.pagina = 1; renderTabela(); });
  $("rd-etapa").addEventListener("change", (e) => { s.etapa = e.target.value; renderMudancas(); });
  ligarDica();

  function mostrarErro(erro) {
    $("rd-erro").textContent = erro.message || "Não foi possível carregar o Radar.";
    $("rd-erro").hidden = false;
  }

  async function iniciar() {
    if (innerWidth <= 900) $("rd-abrir-trilho").hidden = false;
    const [status, perfis, estados, conhecimento] = await Promise.all([
      api("/api/sincronizacao/status"), api("/api/perfis"), api("/api/radar/estados"), api("/api/conhecimento").catch(() => ({ glossario: [] })),
    ]);
    const b = s.base;
    b.status = status;
    b.perfis = perfis.perfis;
    b.perfil = Object.fromEntries(perfis.perfis.map((p) => [p.codigo, p]));
    b.estados = estados.estados;
    b.glossario = Object.fromEntries((conhecimento.glossario || []).map((g) => [g.termo.toLowerCase(), g.definicao]));
    b.glossario["prioridade"] = b.glossario["prioridade sugerida"];
    const prontos = status.estados.filter((e) => e.resumo_em);
    if (!prontos.length) {
      mostrarErro(new Error("O índice ainda não foi carregado. Execute a sincronização; consulte docs/operacao.md."));
      return;
    }
    $("rd-uf").innerHTML = prontos.map((e) => `<option value="${e.uf}">${esc(b.estados.find((x) => x.uf === e.uf)?.nome ?? e.uf)}</option>`).join("");
    s.uf = prontos[0].uf;
    s.iniciado = true;
    if (s.pendente) { s.ibge = s.pendente.ibge; s.f = s.pendente.f; s.pendente = null; }
    await carregarUf();
  }

  /* Usado pela navegação e pelo assistente. */
  window.Radar = {
    uf: () => s.uf || "MA",
    visivel: () => { if (s.iniciado) { renderMapa(); atualizarSync(); } },
    aplicar(filtros) {
      const { ibge, ...resto } = filtros;
      if (!s.iniciado) { s.pendente = { ibge: ibge || null, f: resto }; return; }
      s.ibge = ibge || null;
      s.f = resto;
      s.pagina = 1;
      atualizar();
    },
  };
  iniciar().catch(mostrarErro);
})();
