/* Navegação entre as áreas. A Consulta só inicia, e só chama o SICAR, quando é aberta. */
(() => {
  const AREAS = ["radar", "consulta", "credito", "assistente", "conhecimento"];
  let consultaIniciada = false;

  function abrir() {
    const pedido = location.hash.slice(1);
    const area = AREAS.includes(pedido) ? pedido : "radar";
    for (const nome of AREAS) {
      document.getElementById(`view-${nome}`).hidden = nome !== area;
      const aba = document.querySelector(`[data-area="${nome}"]`);
      if (nome === area) aba.setAttribute("aria-current", "page");
      else aba.removeAttribute("aria-current");
    }
    document.querySelector(".state-tag").hidden = area !== "consulta";
    window.scrollTo(0, 0);
    if (area === "radar") window.Radar?.visivel();
    if (area === "conhecimento") window.Conhecimento?.abrir();
    if (area === "consulta") {
      if (!consultaIniciada) {
        consultaIniciada = true;
        startApp();
      } else {
        state.map?.invalidateSize();
      }
    }
  }
  addEventListener("hashchange", abrir);
  abrir();
})();
