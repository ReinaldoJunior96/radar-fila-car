/* Verificação de imóveis para crédito rural, lida do índice local. */
(() => {
  const raiz = document.getElementById("view-credito");
  if (!raiz) return;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const numero = (v) => Number(v ?? 0).toLocaleString("pt-BR");
  const decimal = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 2 }));
  const NIVEL = { alta: "Atenção alta", atencao: "Atenção", info: "Informativo" };
  const RESULTADO = { atencao_alta: ["alta", "Atenção alta"], atencao: ["atencao", "Atenção"], sem_pontos: ["ok", "Sem pontos de atenção"] };
  const LIMITE = 1000;
  let ultimo = [];

  raiz.innerHTML = `
    <div class="pagina-estreita larga">
      <p class="eyebrow">CRÉDITO RURAL</p><h1>Verifique imóveis antes da análise de crédito</h1>
      <p class="pagina-intro">Cole até ${numero(LIMITE)} códigos CAR. A resposta vem do índice local, sem baixar arquivos do SICAR, e mostra os pontos públicos que merecem conferência.</p>
      <form id="credito-form" class="radar-card credito-form">
        <label for="credito-codigos">Códigos CAR, um por linha ou separados por vírgula</label>
        <textarea id="credito-codigos" rows="6" spellcheck="false" placeholder="MA-2105401-..."></textarea>
        <div class="credito-acoes">
          <button class="primary-button" type="submit">Verificar</button>
          <label class="secondary-button arquivo">Enviar CSV ou TXT<input id="credito-arquivo" type="file" accept=".csv,.txt,text/csv,text/plain" /></label>
          <button id="credito-exemplo" class="secondary-button" type="button">Usar exemplo</button>
          <span id="credito-contagem" class="radar-nota"></span>
        </div>
      </form>
      <div id="credito-saida" aria-live="polite"></div>
    </div>`;

  const campo = raiz.querySelector("#credito-codigos");
  const saida = raiz.querySelector("#credito-saida");
  const extrair = (texto) => [...new Set((texto.toUpperCase().match(/[A-Z]{2}-\d{7}-[0-9A-F.]{32,}/g) || []).map((c) => c.replace(/\./g, "")))];

  function contar() {
    const n = extrair(campo.value).length;
    raiz.querySelector("#credito-contagem").textContent = n ? `${numero(n)} código${n > 1 ? "s" : ""} reconhecido${n > 1 ? "s" : ""}${n > LIMITE ? `, o limite é ${numero(LIMITE)}` : ""}` : "";
  }

  function chips(pontos) {
    return pontos.length
      ? pontos.map((p) => `<span class="ponto ponto-${p.nivel}" title="${esc(p.fonte)}">${esc(p.texto)}</span>`).join("")
      : '<span class="radar-nota">Nenhum ponto público</span>';
  }

  function render(d) {
    ultimo = d.itens.map((i) => i.codigo_car);
    const r = d.resumo;
    const kpi = (rotulo, valor, nota) => `<div class="radar-kpi"><span>${rotulo}</span><strong>${valor}</strong>${nota ? `<small>${nota}</small>` : ""}</div>`;
    saida.innerHTML = `
      <div class="radar-kpis credito-kpis">
        ${kpi("Imóveis verificados", numero(r.unicos), `${numero(r.no_indice)} do índice local${r.ao_vivo ? `, ${numero(r.ao_vivo)} ao vivo` : ""}`)}
        ${kpi("Atenção alta", numero(r.atencao_alta), "Cancelado, suspenso, embargo ou terra indígena")}
        ${kpi("Atenção", numero(r.atencao), "Conferir antes de seguir")}
        ${kpi("Sem pontos de atenção", numero(r.sem_pontos), "Nas fontes públicas usadas")}
        ${kpi("Tempo e custo", `${decimal(d.tempo_ms)} ms`, `${numero(d.chamadas_sicar)} chamada${d.chamadas_sicar === 1 ? "" : "s"} ao SICAR`)}
      </div>
      <article class="radar-card">
        <div class="radar-titulo-linha"><h2>Resultado por imóvel</h2><button id="credito-csv" class="secondary-button" type="button">Baixar CSV</button></div>
        <div class="radar-tabela"><table><thead><tr><th>Código CAR</th><th>Resultado</th><th>Município</th><th>Situação e condição</th><th class="num">Área (ha)</th><th>Pontos</th></tr></thead><tbody>
        ${d.itens.map((i) => {
          const [classe, rotulo] = RESULTADO[i.resultado];
          return `<tr><td class="codigo">${esc(i.codigo_car)}</td><td><span class="resultado resultado-${classe}">${rotulo}</span></td><td>${esc(i.municipio || "—")}${i.uf ? ` · ${esc(i.uf)}` : ""}</td>
            <td>${esc(i.situacao || "—")}${i.condicao ? `<br><small>${esc(i.condicao)}</small>` : ""}</td><td class="num">${decimal(i.area_ha)}</td><td><div class="pontos">${chips(i.pontos)}</div></td></tr>`;
        }).join("")}</tbody></table></div>
        <p class="radar-nota">Níveis: ${Object.values(NIVEL).join(", ")}. Passe o mouse sobre um ponto para ver a fonte. ${esc(d.aviso)}</p>
      </article>`;
  }

  async function verificar(codigos) {
    saida.innerHTML = '<p class="radar-nota">Verificando no índice local…</p>';
    try {
      const resposta = await fetch("/api/credito/verificacao", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ codigos }) });
      const dados = await resposta.json();
      if (!resposta.ok) throw new Error(typeof dados.detail === "string" ? dados.detail : "Não foi possível verificar os códigos.");
      render(dados);
    } catch (erro) {
      saida.innerHTML = `<p class="radar-erro">${esc(erro.message)}</p>`;
    }
  }

  async function baixar() {
    const resposta = await fetch("/api/credito/verificacao.csv", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ codigos: ultimo }) });
    if (!resposta.ok) return;
    const url = URL.createObjectURL(await resposta.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: "verificacao-credito.csv" });
    a.click();
    URL.revokeObjectURL(url);
  }

  campo.addEventListener("input", contar);
  raiz.querySelector("#credito-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const codigos = extrair(campo.value);
    if (!codigos.length) { saida.innerHTML = '<p class="radar-erro">Nenhum código CAR reconhecido. O formato é UF-código IBGE-identificador.</p>'; return; }
    if (codigos.length > LIMITE) { saida.innerHTML = `<p class="radar-erro">Envie no máximo ${numero(LIMITE)} códigos por vez.</p>`; return; }
    verificar(codigos);
  });
  raiz.querySelector("#credito-arquivo").addEventListener("change", async (e) => {
    const arquivo = e.target.files[0];
    if (!arquivo) return;
    campo.value = extrair(await arquivo.text()).join("\n");
    contar();
    e.target.value = "";
  });
  raiz.querySelector("#credito-exemplo").addEventListener("click", async () => {
    try {
      const uf = window.Radar?.uf() || "MA";
      const partes = await Promise.all(["status_cancelado", "app_recompor", "analisado_conforme", "sem_analise"].map((p) =>
        fetch(`/api/radar/fila?uf=${uf}&perfis=${p}&ordem=antiguidade&por_pagina=3`).then((r) => r.json())));
      campo.value = partes.flatMap((p) => p.itens.map((i) => i.codigo_car)).join("\n");
      contar();
    } catch {
      saida.innerHTML = '<p class="radar-erro">Não foi possível montar o exemplo.</p>';
    }
  });
  raiz.addEventListener("click", (e) => { if (e.target.id === "credito-csv") baixar(); });
})();
