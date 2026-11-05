/* ProJuris de mentira — componentes compartilhados (avisos, janelas, combos, "stores").
 *
 * Os dados de cada grade ficam em window.PJ.stores[nome] = {carregado, versao, registros},
 * no mesmo espírito dos stores do ExtJS que o robô real lê. A tela desenha a partir deles.
 */
(function () {
  "use strict";
  const PJ = (window.PJ = window.PJ || {});
  PJ.stores = {};

  const h = (tag, attrs = {}, ...filhos) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") el.className = v;
      else if (k === "texto") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v === true ? "" : v);
    }
    filhos.flat().forEach((f) => f != null && el.append(f.nodeType ? f : document.createTextNode(String(f))));
    return el;
  };
  PJ.h = h;

  // ---------- API ----------
  PJ.api = async (url, opcoes = {}) => {
    const r = await fetch(url, Object.assign({ headers: { "Content-Type": "application/json" } }, opcoes));
    if (r.status === 401) { location.href = "/projuris/login"; throw new Error("sessão expirada"); }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.erro || "HTTP " + r.status);
    return j;
  };

  PJ.carregar = async (nome, url, desenhar) => {
    const ant = PJ.stores[nome] || { versao: 0 };
    PJ.stores[nome] = { carregado: false, versao: ant.versao, registros: ant.registros || [] };
    const j = await PJ.api(url);
    PJ.stores[nome] = { carregado: true, versao: ant.versao + 1, registros: j.registros, total: j.total };
    if (desenhar) desenhar(PJ.stores[nome].registros);
    return PJ.stores[nome];
  };

  // ---------- aviso (equivalente ao Ext.Msg) ----------
  PJ.msg = (texto, botoes = ["OK"], titulo = "Aviso") =>
    new Promise((ok) => {
      const caixa = document.getElementById("pj-msg");
      caixa.querySelector(".msg-titulo").textContent = titulo;
      caixa.querySelector(".msg-texto").textContent = texto;
      const area = caixa.querySelector(".msg-botoes");
      area.innerHTML = "";
      botoes.forEach((b) =>
        area.append(h("button", { class: "btn" + (b === botoes[0] ? " primario" : ""), type: "button",
          onclick: () => { caixa.classList.remove("visivel"); ok(b); } }, b)));
      caixa.classList.add("visivel");
    });

  // ---------- campos ----------
  const RE_DATA = /^\d{2}\/\d{2}\/\d{4}$/;

  function valorDe(campo) {
    const t = campo.dataset.tipo;
    if (t === "combo") return campo.querySelector(".combo-valor").value;
    if (t === "check") return campo.querySelector("input").checked ? "1" : "";
    if (t === "radio") { const r = campo.querySelector("input:checked"); return r ? r.value : ""; }
    if (t === "arquivo") { const f = campo.querySelector("input").files[0]; return f ? f.name : ""; }
    return campo.querySelector("input").value.trim();
  }
  PJ.valorDe = valorDe;

  function validarCampo(campo) {
    const v = valorDe(campo);
    let ok = !(campo.dataset.obrigatorio === "1" && !v);
    if (ok && campo.dataset.tipo === "data" && v && !RE_DATA.test(v)) ok = false;
    if (ok && campo.dataset.tipo === "combo" && !v && campo.querySelector(".combo-texto").value.trim()) ok = false;
    campo.classList.toggle("invalido", !ok);
    return ok;
  }

  function combo(def, janela) {
    const el = h("div", { class: "campo combo", "data-campo": def.campo, "data-rotulo": def.rotulo,
      "data-tipo": "combo", "data-obrigatorio": def.obrigatorio ? "1" : "0", "data-cargas": "0" });
    const txt = h("input", { class: "combo-texto", type: "text", autocomplete: "off" });
    const val = h("input", { class: "combo-valor", type: "hidden", name: def.campo });
    const lista = h("ul", { class: "combo-lista" });
    let timer = null;

    async function carregar(q) {
      el.dataset.carregando = "1";
      const params = new URLSearchParams(Object.assign({ q }, def.params ? def.params(janela) : {}));
      let itens = [];
      try { itens = await PJ.api(`/projuris/api/combo/${def.fonte}?${params}`); } catch (e) { itens = []; }
      lista.innerHTML = "";
      itens.forEach((it) => lista.append(h("li", { "data-valor": it.valor, texto: it.texto,
        onmousedown: (ev) => ev.preventDefault(),
        onclick: () => selecionar(it) })));
      if (!itens.length) lista.append(h("li", { class: "vazio", texto: "Nenhum registro encontrado" }));
      el.dataset.ultimaConsulta = q;
      el.dataset.cargas = String(Number(el.dataset.cargas) + 1);
      el.dataset.carregando = "0";
      el.classList.add("aberto");
    }

    function selecionar(it) {
      txt.value = it.texto;
      val.value = it.valor;
      el.classList.remove("aberto");
      validarCampo(el);
      // é ESTE evento (clique no item) que avisa os combos dependentes — mudar o valor por
      // código não dispara nada, como no combo do sistema real
      el.dispatchEvent(new CustomEvent("pj:selecionado", { detail: it, bubbles: true }));
    }

    txt.addEventListener("input", () => {
      val.value = "";
      clearTimeout(timer);
      timer = setTimeout(() => carregar(txt.value.trim()), 250);
    });
    txt.addEventListener("blur", () => setTimeout(() => el.classList.remove("aberto"), 150));
    el.limpar = () => { txt.value = ""; val.value = ""; lista.innerHTML = ""; };
    el.append(h("label", {}, def.rotulo, def.obrigatorio ? h("b", {}, " *") : null),
      h("div", { class: "combo-caixa" }, txt,
        h("button", { class: "combo-seta", type: "button", tabindex: "-1", title: "Abrir lista",
          onclick: () => { txt.focus(); carregar(""); } }, "▾")),
      val, lista);
    if (def.aoSelecionar) el.addEventListener("pj:selecionado", (ev) => def.aoSelecionar(ev.detail, janela));
    return el;
  }

  function campo(def, janela) {
    if (def.tipo === "combo") return combo(def, janela);
    const base = { class: "campo", "data-campo": def.campo, "data-rotulo": def.rotulo, "data-tipo": def.tipo,
      "data-obrigatorio": def.obrigatorio ? "1" : "0" };
    const rot = h("label", {}, def.rotulo, def.obrigatorio ? h("b", {}, " *") : null);
    if (def.tipo === "check")
      return h("div", base, h("label", { class: "check" }, h("input", { type: "checkbox", name: def.campo }), " " + def.rotulo));
    if (def.tipo === "radio")
      return h("div", base, rot, h("div", { class: "radios" }, def.opcoes.map(([v, t]) =>
        h("label", { class: "radio" }, h("input", { type: "radio", name: def.campo, value: v }), " " + t))));
    if (def.tipo === "arquivo")
      return h("div", base, rot, h("input", { type: "file", name: def.campo, accept: "application/pdf" }));
    const inp = h("input", { type: "text", name: def.campo, placeholder: def.tipo === "data" ? "dd/mm/aaaa" : "",
      autocomplete: "off" });
    const el = h("div", base, rot, inp);
    inp.addEventListener("blur", () => validarCampo(el));
    return el;
  }

  // ---------- janela modal (equivalente à Ext.Window) ----------
  PJ.janela = (opcoes) => {
    PJ.fecharJanela();
    const corpo = h("form", { class: "janela-corpo", onsubmit: (e) => e.preventDefault() });
    const jan = h("div", { class: "pj-janela ativa", role: "dialog", "aria-label": opcoes.titulo },
      h("div", { class: "janela-cab" }, h("span", { class: "janela-titulo", texto: opcoes.titulo }),
        h("button", { class: "janela-fechar", type: "button", title: "Fechar", onclick: () => PJ.fecharJanela() }, "×")),
      corpo,
      h("div", { class: "janela-rodape" },
        h("button", { class: "btn primario", type: "button", "data-acao": "salvar", onclick: () => salvar() }, "Salvar"),
        h("button", { class: "btn", type: "button", "data-acao": "cancelar", onclick: () => PJ.fecharJanela() }, "Cancelar")));
    opcoes.campos.forEach((d) => corpo.append(campo(d, jan)));
    jan.campo = (nome) => jan.querySelector(`.campo[data-campo="${nome}"]`);
    document.body.append(h("div", { class: "pj-mascara" }), jan);

    async function salvar() {
      const campos = [...jan.querySelectorAll(".campo")];
      const ruins = campos.filter((c) => !validarCampo(c)).map((c) => c.dataset.rotulo);
      if (ruins.length) { await PJ.msg("Existem campos inválidos: " + ruins.join(", "), ["OK"], "Atenção"); return; }
      const valores = {};
      campos.forEach((c) => (valores[c.dataset.campo] = valorDe(c)));
      jan.querySelectorAll(".janela-rodape button").forEach((b) => (b.disabled = true));
      try {
        const r = await opcoes.salvar(valores, jan);
        PJ.fecharJanela();
        if (opcoes.depois) opcoes.depois(r);
      } catch (e) {
        jan.querySelectorAll(".janela-rodape button").forEach((b) => (b.disabled = false));
        await PJ.msg("Erro ao salvar: " + e.message, ["OK"], "Erro");
      }
    }
    return jan;
  };

  PJ.fecharJanela = () => document.querySelectorAll(".pj-janela, .pj-mascara").forEach((e) => e.remove());

  PJ.lerArquivo = (input) =>
    new Promise((ok, erro) => {
      const f = input.files[0];
      if (!f) return erro(new Error("nenhum arquivo"));
      const r = new FileReader();
      r.onload = () => ok({ nome: f.name, b64: String(r.result).split(",")[1] });
      r.onerror = () => erro(r.error);
      r.readAsDataURL(f);
    });

  PJ.marca = (v) => (v ? "✔" : "");
})();
