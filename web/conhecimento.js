/* Central de conhecimento, carregada somente quando a aba é aberta. */
(() => {
  const raiz = document.getElementById("view-conhecimento");
  if (!raiz) return;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const link = (i) => `<article class="saber-item" data-busca><h3><a href="${esc(i.url)}" target="_blank" rel="noopener noreferrer">${esc(i.titulo)}</a></h3><p>${esc(i.descricao)}</p></article>`;
  let carregado = false;

  function secao(id, titulo, corpo) {
    return `<section class="saber-secao" id="saber-${id}"><h2>${titulo}</h2>${corpo}</section>`;
  }

  function render(d) {
    const secoes = [
      ["guias", "Guias rápidos", `<div class="saber-grade">${d.guias.map((g) => `<article class="saber-item" data-busca><h3>${esc(g.titulo)}</h3><ol>${g.passos.map((p) => `<li>${esc(p)}</li>`).join("")}</ol></article>`).join("")}</div>`],
      ["faq", "Perguntas frequentes", d.faq.map((f) => `<details class="saber-faq" data-busca><summary>${esc(f.pergunta)}</summary><p>${esc(f.resposta)}</p></details>`).join("")],
      ["glossario", "Glossário", `<div class="saber-grade">${d.glossario.map((g) => `<article class="saber-item" data-busca><h3>${esc(g.termo)}</h3><p>${esc(g.definicao)}</p></article>`).join("")}</div>`],
      ["dicionario", "Dicionário de dados", `<p class="radar-nota">Baseado no Dicionário de Dados do SICAR. A coluna “No serviço” mostra o nome usado no WFS público.</p><div class="radar-tabela"><table><thead><tr><th>Campo</th><th>No serviço</th><th>Tipo</th><th>Descrição</th></tr></thead><tbody>${d.dicionario.map((c) => `<tr data-busca><td class="codigo">${esc(c.campo)}</td><td class="codigo">${esc(c.servico)}</td><td>${esc(c.tipo)}</td><td>${esc(c.descricao)}</td></tr>`).join("")}</tbody></table></div>`],
      ["metodologia", "Metodologia", `<div class="saber-grade">${d.metodologia.map((m) => `<article class="saber-item" data-busca><h3>${esc(m.titulo)}</h3><p>${esc(m.texto)}</p></article>`).join("")}</div>`],
      ["limites", "Limites", `<ul class="saber-lista">${d.limites.map((l) => `<li data-busca>${esc(l)}</li>`).join("")}</ul>`],
      ["biblioteca", "Biblioteca técnica", `<div class="saber-grade">${(d.biblioteca || []).map(link).join("")}</div>`],
      ["legislacao", "Legislação", `<div class="saber-grade">${d.legislacao.map(link).join("")}</div>`],
      ["links", "Links oficiais", `<div class="saber-grade">${d.links.map(link).join("")}</div>`],
    ];
    raiz.querySelector("#saber-indice").innerHTML = secoes.map(([id, titulo]) => `<a href="#conhecimento" data-ir="saber-${id}">${titulo}</a>`).join("");
    raiz.querySelector("#saber-corpo").innerHTML = secoes.map(([id, titulo, corpo]) => secao(id, titulo, corpo)).join("");
  }

  raiz.innerHTML = `<div class="pagina-estreita larga"><p class="eyebrow">CENTRAL DE CONHECIMENTO</p><h1>Entenda os dados e o método</h1>
    <label class="sr-only" for="saber-busca">Buscar na central</label><input id="saber-busca" class="saber-busca" type="search" placeholder="Buscar por termo, campo ou norma" />
    <p id="saber-resultado" class="radar-nota" aria-live="polite"></p><nav id="saber-indice" class="saber-indice" aria-label="Seções"></nav><div id="saber-corpo"></div></div>`;

  raiz.querySelector("#saber-busca").addEventListener("input", (e) => {
    const termo = e.target.value.trim().toLocaleLowerCase("pt-BR");
    let achados = 0;
    raiz.querySelectorAll("[data-busca]").forEach((item) => {
      const ok = !termo || item.textContent.toLocaleLowerCase("pt-BR").includes(termo);
      item.hidden = !ok;
      achados += ok ? 1 : 0;
    });
    raiz.querySelectorAll(".saber-secao").forEach((s) => { s.hidden = !s.querySelector("[data-busca]:not([hidden])"); });
    raiz.querySelector("#saber-resultado").textContent = termo ? `${achados} resultados` : "";
  });
  raiz.addEventListener("click", (e) => {
    const alvo = e.target.closest("[data-ir]");
    if (!alvo) return;
    e.preventDefault();
    document.getElementById(alvo.dataset.ir)?.scrollIntoView({ behavior: "smooth" });
  });

  window.Conhecimento = {
    async abrir() {
      if (carregado) return;
      try {
        const resposta = await fetch("/api/conhecimento");
        if (!resposta.ok) throw new Error();
        render(await resposta.json());
        carregado = true;
      } catch {
        raiz.querySelector("#saber-corpo").innerHTML = '<p class="radar-erro">Não foi possível carregar a central.</p>';
      }
    },
  };
})();
