/* Página do processo: abas, grades e as janelas de cadastro (fase, decisão, evento, documento). */
(function () {
  "use strict";
  const { h } = PJ;
  const ID = Number(location.pathname.split("/").pop());
  const API = `/projuris/api/processo/${ID}`;
  const PREDOM = { F: "Favorável", D: "Desfavorável", P: "Favorável em parte" };

  // ---------- cabeçalho ----------
  PJ.api(API).then((p) => {
    const cab = document.getElementById("cabecalho");
    cab.dataset.id = p.id; cab.dataset.pasta = p.pasta; cab.dataset.cnj = p.cnj;
    document.getElementById("cab-pasta").textContent = p.pasta;
    document.getElementById("cab-cnj").textContent = p.cnj;
    document.getElementById("cab-cliente").textContent = p.cliente;
    document.getElementById("cab-parte").textContent = p.parte_contraria;
    cab.dataset.pronto = "1";
  });

  // ---------- abas ----------
  const abas = document.getElementById("abas");
  function ativar(nome) {
    abas.querySelectorAll(".aba").forEach((a) => a.classList.toggle("ativa", a.dataset.aba === nome));
    document.querySelectorAll(".painel-aba").forEach((p) => p.classList.toggle("visivel", p.dataset.painel === nome));
    if (nome === "fases") recarregar.fases();
    if (nome === "eventos") recarregar.eventos();
    if (nome === "documentos") recarregar.documentos();
    if (nome.startsWith("evento-")) recarregar.evdocs(Number(nome.slice(7)));
  }
  abas.addEventListener("click", (e) => {
    const a = e.target.closest(".aba");
    if (e.target.classList.contains("aba-fechar")) {
      const nome = a.dataset.aba;
      a.remove(); document.querySelector(`[data-painel="${nome}"]`).remove(); ativar("eventos");
      return;
    }
    if (a) ativar(a.dataset.aba);
  });

  const sel = (id) => h("td", {}, h("input", { type: "checkbox", class: "sel-linha", "data-id": id }));
  const linhas = (store, regs, fn) => {
    const tb = document.querySelector(`[data-store="${store}"] tbody`);
    tb.innerHTML = "";
    regs.forEach((r) => tb.append(fn(r)));
    if (!regs.length) tb.append(h("tr", { class: "vazia" }, h("td", { colspan: 20, texto: "Nenhum registro." })));
  };

  const recarregar = {
    fases: () => PJ.carregar("fases", `${API}/fases`, (regs) => linhas("fases", regs, (f) =>
      h("tr", { "data-id": f.id }, sel(f.id), h("td", { texto: f.data }), h("td", { texto: f.fase }),
        h("td", { texto: f.numero }), h("td", { texto: f.tribunal }), h("td", { texto: f.jurisdicao }),
        h("td", { texto: f.uf }), h("td", { texto: f.comarca }), h("td", { texto: f.juiz }),
        h("td", { class: "marca", texto: PJ.marca(f.atual) }), h("td", { class: "marca", texto: PJ.marca(f.julgado) }),
        h("td", { texto: f.decisao }), h("td", { texto: PREDOM[f.predominante] || "" })))),
    eventos: () => PJ.carregar("eventos", `${API}/eventos`, (regs) => linhas("eventos", regs, (e) =>
      h("tr", { "data-id": e.id }, sel(e.id), h("td", { texto: e.data }),
        h("td", {}, h("a", { class: "link-evento link-comum", "data-id": e.id, onclick: () => abrirFicha(e) }, e.evento)),
        h("td", { texto: e.fase }), h("td", { texto: e.requisicao || "" })))),
    documentos: () => PJ.carregar("documentos", `${API}/documentos`, (regs) => linhas("documentos", regs, (d) =>
      h("tr", { "data-id": d.id }, sel(d.id), h("td", { texto: d.data }), h("td", { texto: d.nome }),
        h("td", { texto: d.tipo }), h("td", { texto: d.evento })))),
    evdocs: (eid) => PJ.carregar(`evdocs-${eid}`, `${API}/documentos?evento=${eid}`, (regs) =>
      linhas(`evdocs-${eid}`, regs, (d) => h("tr", { "data-id": d.id }, sel(d.id), h("td", { texto: d.data }),
        h("td", { texto: d.nome }), h("td", { texto: d.tipo })))),
  };

  const selecionadas = (store) =>
    [...document.querySelectorAll(`[data-store="${store}"] input.sel-linha:checked`)].map((c) => Number(c.dataset.id));

  // ---------- campos reutilizados ----------
  const cData = (campo = "DATA", rotulo = "Data") => ({ campo, rotulo, tipo: "data", obrigatorio: true });
  const post = (url, corpo) => PJ.api(url, { method: "POST", body: JSON.stringify(corpo) });

  // ---------- 1) Adicionar fase ----------
  document.getElementById("fase-adicionar").addEventListener("click", () => PJ.janela({
    titulo: "Fases do Processo - Adicionar",
    campos: [
      cData(),
      { campo: "TIPO_RECURSO", rotulo: "Tipo", tipo: "combo", fonte: "tipo_recurso", obrigatorio: true },
      { campo: "NUMERO_ORIGINAL", rotulo: "Número", tipo: "texto" },
      { campo: "ID_FASE", rotulo: "Fase", tipo: "combo", fonte: "fase", obrigatorio: true },
      { campo: "ID_TRIBUNAL", rotulo: "Tribunal", tipo: "combo", fonte: "tribunal", obrigatorio: true },
      { campo: "ID_JURISDICAO", rotulo: "Jurisdição", tipo: "combo", fonte: "jurisdicao", obrigatorio: true },
      { campo: "ID_UF", rotulo: "UF", tipo: "combo", fonte: "uf", obrigatorio: true,
        // a UF escolhida (com clique na lista) é que filtra as comarcas
        aoSelecionar: (it, jan) => { const c = jan.campo("ID_COMARCA"); c.dataset.uf = it.valor; c.limpar(); } },
      { campo: "ID_COMARCA", rotulo: "Comarca", tipo: "combo", fonte: "comarca", obrigatorio: true,
        params: (jan) => ({ uf: jan.campo("ID_COMARCA").dataset.uf || "" }) },
      { campo: "ATUAL", rotulo: "Atual", tipo: "check" },
    ],
    salvar: (v) => post(`${API}/fases`, v),
    depois: () => recarregar.fases(),
  }));

  // ---------- 2) Registrar decisão ----------
  document.getElementById("fase-decisao").addEventListener("click", async () => {
    const s = selecionadas("fases");
    if (s.length !== 1) return PJ.msg("Selecione uma (e só uma) fase para registrar a decisão.");
    const fase = PJ.stores.fases.registros.find((f) => f.id === s[0]);
    if (fase.julgado) return PJ.msg("Esta fase já possui decisão registrada.");
    PJ.janela({
      titulo: "Fases do Processo - Registrar Decisão",
      campos: [
        cData("DATA_DECISAO", "Data da decisão"),
        { campo: "ID_DECISAO", rotulo: "Decisão", tipo: "combo", fonte: "decisao", obrigatorio: true },
        { campo: "DECISAO_OBJETO", rotulo: "Decisão predominante", tipo: "radio", obrigatorio: true,
          opcoes: [["F", "Favorável"], ["D", "Desfavorável"], ["P", "Favorável em parte"]] },
      ],
      salvar: (v) => post(`${API}/fases/${fase.id}/decisao`, v),
      depois: () => recarregar.fases(),
    });
  });

  // ---------- 3) Adicionar evento ----------
  document.getElementById("evento-adicionar").addEventListener("click", () => PJ.janela({
    titulo: "Eventos do Processo - Adicionar",
    campos: [
      cData(),
      { campo: "ID_EVENTO", rotulo: "Evento", tipo: "combo", fonte: "evento", obrigatorio: true },
      { campo: "ID_PROCESSO_DESDOBRAMENTO", rotulo: "Fase", tipo: "combo", fonte: "desdobramento",
        obrigatorio: true, params: () => ({ processo: ID }) },
    ],
    salvar: (v) => post(`${API}/eventos`, v),
    depois: async (r) => {
      recarregar.eventos();
      // aviso informativo do sistema; depois do OK a ficha do evento abre sozinha
      await PJ.msg(`Requisição ${r.requisicao} cadastrada com sucesso.`, ["OK"], "Informação");
      const ev = (await PJ.api(`${API}/eventos`)).registros.find((e) => e.id === r.id);
      abrirFicha(ev);
    },
  }));

  // ---------- ficha do evento (aba própria, com documentos do evento) ----------
  function abrirFicha(ev) {
    const nome = `evento-${ev.id}`;
    if (!abas.querySelector(`[data-aba="${nome}"]`)) {
      abas.append(h("span", { class: "aba", "data-aba": nome }, `Evento: ${ev.evento}`,
        h("b", { class: "aba-fechar", title: "Fechar" }, " ×")));
      const painel = h("section", { class: "painel-aba", "data-painel": nome },
        h("div", { class: "ficha" }, h("div", {}, h("span", { class: "rot" }, "Evento: "), h("b", { texto: ev.evento })),
          h("div", {}, h("span", { class: "rot" }, "Data: "), ev.data),
          h("div", {}, h("span", { class: "rot" }, "Fase: "), ev.fase || "")),
        h("h3", { texto: "Documentos do evento" }),
        h("div", { class: "barra" }, h("button", { class: "btn adicionar-doc-evento", type: "button",
          onclick: () => janelaDocumento(`${API}/eventos/${ev.id}/documentos`, "Documento do Evento do Processo",
            () => recarregar.evdocs(ev.id)) }, "Adicionar")),
        h("table", { class: "grade", "data-store": nome.replace("evento-", "evdocs-") },
          h("thead", {}, h("tr", {}, h("th"), h("th", { texto: "Data" }), h("th", { texto: "Nome" }), h("th", { texto: "Tipo" }))),
          h("tbody")));
      document.querySelector("main").append(painel);
    }
    ativar(nome);
  }

  // ---------- 4) documento (do processo ou do evento) ----------
  function janelaDocumento(url, titulo, depois) {
    PJ.janela({
      titulo,
      campos: [
        { campo: "ARQUIVO", rotulo: "Arquivo", tipo: "arquivo", obrigatorio: true },
        { campo: "ID_TIPO_DOCUMENTO", rotulo: "Tipo de documento", tipo: "combo", fonte: "tipo_documento", obrigatorio: true },
        cData(),
      ],
      salvar: async (v, jan) => {
        const arq = await PJ.lerArquivo(jan.campo("ARQUIVO").querySelector("input"));
        return post(url, { ARQUIVO_NOME: arq.nome, ARQUIVO_B64: arq.b64, ID_TIPO_DOCUMENTO: v.ID_TIPO_DOCUMENTO, DATA: v.DATA });
      },
      depois,
    });
  }
  document.getElementById("doc-adicionar").addEventListener("click", () =>
    janelaDocumento(`${API}/documentos`, "Documentos do Processo - Adicionar", () => recarregar.documentos()));
})();
