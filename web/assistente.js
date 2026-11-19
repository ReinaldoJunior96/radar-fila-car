/* Assistente: mostra o que entendeu antes do resultado. */
(() => {
  const raiz = document.getElementById("view-assistente");
  if (!raiz) return;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const numero = (v) => Number(v).toLocaleString("pt-BR");
  const EXEMPLOS = [
    "Quantos imóveis estão sem análise há mais de 5 anos?",
    "Quais municípios têm mais imóveis com APP a recompor?",
    "Mostre os 10 imóveis mais antigos na fila em Itapecuru Mirim",
    "Imóveis com sobreposição em território quilombola",
    "Cadastros aguardando regularização acima de 100 hectares",
  ];
  raiz.innerHTML = `
    <div class="pagina-estreita">
      <p class="eyebrow">ASSISTENTE</p><h1>Pergunte sobre a fila do CAR</h1>
      <p class="pagina-intro">As respostas vêm do índice local. O assistente mostra os filtros que entendeu e não inventa dados.</p>
      <form id="assistente-form" class="assistente-form"><label class="sr-only" for="assistente-q">Sua pergunta</label>
        <input id="assistente-q" maxlength="300" autocomplete="off" placeholder="Ex.: quantos imóveis estão na fila há mais de 10 anos?" /><button class="primary-button" type="submit">Perguntar</button></form>
      <div class="exemplos">${EXEMPLOS.map((e) => `<button type="button" class="perfil" data-exemplo="${esc(e)}">${esc(e)}</button>`).join("")}</div>
      <div id="assistente-resposta" aria-live="polite"></div>
    </div>`;
  const campo = raiz.querySelector("#assistente-q");
  const saida = raiz.querySelector("#assistente-resposta");
  let filtrosAtuais = null;

  function render(d) {
    filtrosAtuais = d.filtros || null;
    const entendido = (d.entendido || []).map((i) => `<span class="entendido"><small>${esc(i.campo)}</small>${esc(i.valor)}</span>`).join("");
    const ranking = d.ranking?.length ? `<div class="radar-tabela"><table><thead><tr><th>Município</th><th class="num">Imóveis</th></tr></thead><tbody>${d.ranking.map((m) => `<tr><td>${esc(m.municipio)}</td><td class="num">${numero(m.total)}</td></tr>`).join("")}</tbody></table></div>` : "";
    const itens = d.itens?.length ? `<div class="radar-tabela"><table><thead><tr><th class="num">Prioridade</th><th>Código CAR</th><th>Município</th><th>Condição</th></tr></thead><tbody>${d.itens.map((i) => `<tr><td class="num">${i.prioridade_sugerida}</td><td class="codigo">${esc(i.codigo_car)}</td><td>${esc(i.municipio)}</td><td>${esc(i.condicao || "—")}</td></tr>`).join("")}</tbody></table></div>` : "";
    saida.innerHTML = `<article class="radar-card resposta">
      ${entendido ? `<p class="eyebrow">ENTENDI ESTES FILTROS</p><div class="entendidos">${entendido}</div>` : ""}
      <h2>${esc(d.resposta)}</h2>${ranking}${itens}
      ${d.entendeu ? '<button id="assistente-radar" type="button" class="secondary-button">Abrir no Radar</button>' : '<p class="radar-nota">Use um dos exemplos acima como ponto de partida.</p>'}
      <p class="radar-nota">${esc(d.aviso)}</p></article>`;
  }

  async function perguntar(texto) {
    saida.innerHTML = '<p class="radar-nota">Consultando o índice…</p>';
    try {
      const uf = window.Radar?.uf() || "MA";
      const resposta = await fetch(`/api/assistente?${new URLSearchParams({ q: texto, uf })}`);
      const dados = await resposta.json();
      if (!resposta.ok) throw new Error(typeof dados.detail === "string" ? dados.detail : "Escreva uma pergunta um pouco mais longa.");
      render(dados);
    } catch (erro) {
      saida.innerHTML = `<p class="radar-erro">${esc(erro.message)}</p>`;
    }
  }
  raiz.querySelector("#assistente-form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (campo.value.trim()) perguntar(campo.value.trim());
  });
  raiz.addEventListener("click", (e) => {
    const exemplo = e.target.closest("[data-exemplo]");
    if (exemplo) { campo.value = exemplo.dataset.exemplo; perguntar(campo.value); }
    if (e.target.id === "assistente-radar" && filtrosAtuais) {
      window.Radar.aplicar(filtrosAtuais);
      location.hash = "#radar";
    }
  });
})();
