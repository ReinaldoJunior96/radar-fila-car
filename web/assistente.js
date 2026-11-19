/* Assistente em formato de conversa: mostra o que entendeu e permite refinar a pergunta anterior. */
(() => {
  const raiz = document.getElementById("view-assistente");
  if (!raiz) return;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const numero = (v) => Number(v).toLocaleString("pt-BR");
  const EXEMPLOS = [
    "Quantos imóveis estão sem análise há mais de 5 anos?",
    "E só em Itapecuru Mirim?",
    "Quais municípios têm mais imóveis com APP a recompor?",
    "Imóveis analisados no último mês",
    "O que é módulo fiscal?",
    "Cadastros aguardando regularização acima de 100 hectares",
  ];
  raiz.innerHTML = `
    <div class="pagina-estreita">
      <p class="eyebrow">ASSISTENTE</p>
      <div class="radar-titulo-linha"><h1>Pergunte sobre a fila do CAR</h1><button id="assistente-nova" class="secondary-button" type="button">Nova conversa</button></div>
      <p class="pagina-intro">As respostas vêm do índice local e da central de conhecimento. O assistente mostra os filtros que entendeu, não inventa dados e lembra a pergunta anterior: comece com “e”, “só” ou “agora” para refinar.</p>
      <div id="assistente-conversa" class="conversa" aria-live="polite"></div>
      <form id="assistente-form" class="assistente-form"><label class="sr-only" for="assistente-q">Sua pergunta</label>
        <input id="assistente-q" maxlength="300" autocomplete="off" placeholder="Ex.: quantos imóveis estão na fila há mais de 10 anos?" /><button class="primary-button" type="submit">Perguntar</button></form>
      <div class="exemplos">${EXEMPLOS.map((e) => `<button type="button" class="perfil" data-exemplo="${esc(e)}">${esc(e)}</button>`).join("")}</div>
    </div>`;
  const campo = raiz.querySelector("#assistente-q");
  const conversa = raiz.querySelector("#assistente-conversa");
  const filtros = new Map();
  let contexto = null;
  let contador = 0;

  function bolha(classe, html) {
    const item = document.createElement("div");
    item.className = `mensagem ${classe}`;
    item.innerHTML = html;
    conversa.append(item);
    item.scrollIntoView({ behavior: "smooth", block: "nearest" });
    return item;
  }

  function resposta(d) {
    const id = ++contador;
    if (d.filtros) filtros.set(id, d.filtros);
    const entendido = (d.entendido || []).map((i) => `<span class="entendido"><small>${esc(i.campo)}</small>${esc(i.valor)}</span>`).join("");
    const ranking = d.ranking?.length ? `<div class="radar-tabela curta"><table><thead><tr><th>Município</th><th class="num">Imóveis</th></tr></thead><tbody>${d.ranking.map((m) => `<tr><td>${esc(m.municipio)}</td><td class="num">${numero(m.total)}</td></tr>`).join("")}</tbody></table></div>` : "";
    const itens = d.itens?.length ? `<div class="radar-tabela curta"><table><thead><tr><th class="num">Prioridade</th><th>Código CAR</th><th>Município</th><th>Condição</th></tr></thead><tbody>${d.itens.map((i) => `<tr><td class="num">${i.prioridade_sugerida}</td><td class="codigo">${esc(i.codigo_car)}</td><td>${esc(i.municipio)}</td><td>${esc(i.condicao || "—")}</td></tr>`).join("")}</tbody></table></div>` : "";
    const rodape = d.fonte
      ? `<p class="radar-nota">Fonte: ${esc(d.fonte)}, na central de conhecimento.</p>`
      : d.filtros
        ? `<button type="button" class="secondary-button" data-radar="${id}">Abrir no Radar</button><p class="radar-nota">${esc(d.aviso)}</p>`
        : d.entendeu ? "" : '<p class="radar-nota">Use um dos exemplos abaixo como ponto de partida.</p>';
    bolha("assistente", `${entendido ? `<p class="eyebrow">ENTENDI</p><div class="entendidos">${entendido}</div>` : ""}<p class="mensagem-texto">${esc(d.resposta)}</p>${ranking}${itens}${rodape}`);
  }

  async function perguntar(texto) {
    bolha("usuario", `<p class="mensagem-texto">${esc(texto)}</p>`);
    const espera = bolha("assistente espera", '<p class="radar-nota">Consultando o índice…</p>');
    try {
      const uf = window.Radar?.uf() || "MA";
      const parametros = new URLSearchParams({ q: texto, uf });
      if (contexto) parametros.set("contexto", JSON.stringify(contexto));
      const r = await fetch(`/api/assistente?${parametros}`);
      const dados = await r.json();
      if (!r.ok) throw new Error(typeof dados.detail === "string" ? dados.detail : "Escreva uma pergunta um pouco mais longa.");
      espera.remove();
      if (dados.contexto?.filtros) contexto = dados.contexto;
      resposta(dados);
    } catch (erro) {
      espera.remove();
      bolha("assistente", `<p class="radar-erro">${esc(erro.message)}</p>`);
    }
  }

  raiz.querySelector("#assistente-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const texto = campo.value.trim();
    if (!texto) return;
    campo.value = "";
    perguntar(texto);
  });
  raiz.addEventListener("click", (e) => {
    const exemplo = e.target.closest("[data-exemplo]");
    if (exemplo) perguntar(exemplo.dataset.exemplo);
    const abrir = e.target.closest("[data-radar]");
    if (abrir && filtros.has(Number(abrir.dataset.radar))) {
      window.Radar.aplicar(filtros.get(Number(abrir.dataset.radar)));
      location.hash = "#radar";
    }
    if (e.target.id === "assistente-nova") {
      contexto = null;
      filtros.clear();
      conversa.innerHTML = "";
      campo.focus();
    }
  });
})();
