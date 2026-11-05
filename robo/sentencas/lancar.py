"""
Preenchimento dos formulários do ProJuris (fase, decisão, evento, documento).

Aqui só o ENSAIO (preenche, confere, tira print e FECHA PELO X) e os auxiliares de
preenchimento. O "Salvar" fica SÓ em gravar.py (processos liberados no config.toml, S/N antes
de cada Salvar).

No ensaio a fase nova e o evento não chegam a existir, então:
- decisão: "Registrar Decisão" na fase ATUAL (sem decisão) só para testar os campos;
- evento: campo Fase = fase atual;
- documento: "Adicionar" da aba documentos do processo (na gravação é DENTRO do evento salvo).

Combos: o robô age como uma pessoa — digita (ou abre a setinha), espera a lista carregar e
CLICA no item. Escolher o valor só por código não dispara o filtro dos combos dependentes
(UF -> Comarca): a lista de comarcas viria vazia. Item = texto EXATO (ou ID); se o texto só
bate depois de normalizar e houver mais de um ("Procedente em parte" x "Procedente em Parte"),
é erro. Nunca chuta.
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import regras as R
from .projuris import Processo, ProJuris, ProJurisErro

JANELA_ATIVA = ".pj-janela.ativa"


def _n(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", t).strip()


@dataclass
class Ensaio:
    etapa: str
    preenchido: dict = field(default_factory=dict)
    invalidos: list = field(default_factory=list)
    erro: str = ""
    print_: str = ""


_JS_TITULO = """() => { const j = document.querySelector('.pj-janela.ativa');
  return j ? j.querySelector('.janela-titulo').innerText.trim() : null; }"""

# leitura do formulário feita pelo robô (não confia em marcação da própria tela)
_JS_LER = r"""() => { const j = document.querySelector('.pj-janela.ativa'); if (!j) return null;
  const out = {}, inv = [];
  j.querySelectorAll('.campo').forEach(c => {
    const t = c.dataset.tipo, rot = c.dataset.rotulo, obr = c.dataset.obrigatorio === '1';
    let v = '', ok = true;
    if (t === 'combo') {
      const txt = c.querySelector('.combo-texto').value.trim(), val = c.querySelector('.combo-valor').value;
      v = txt; if ((obr && !val) || (txt && !val)) ok = false;
    } else if (t === 'check') { v = c.querySelector('input').checked ? 'sim' : '';
    } else if (t === 'radio') { const r = c.querySelector('input:checked');
      v = r ? r.parentElement.innerText.trim() : ''; if (obr && !r) ok = false;
    } else if (t === 'arquivo') { const f = c.querySelector('input').files[0];
      v = f ? f.name : ''; if (obr && !f) ok = false;
    } else { v = c.querySelector('input').value.trim(); if (obr && !v) ok = false;
      if (t === 'data' && v && !/^\d{2}\/\d{2}\/\d{4}$/.test(v)) ok = false; }
    if (v) out[rot] = v;
    if (!ok) inv.push(rot);
  });
  return {valores: out, invalidos: inv}; }"""


class Formularios:
    def __init__(self, pj: ProJuris, pasta_prints: Path):
        self.pj, self.pg = pj, pj.pg
        self.prints = Path(pasta_prints)
        self.prints.mkdir(parents=True, exist_ok=True)

    # ---------- utilidades ----------
    def _janela(self, titulo_esperado: str, seg: float = 15) -> str:
        fim = time.time() + seg
        while time.time() < fim:
            t = self.pg.evaluate(_JS_TITULO)
            if t and titulo_esperado.lower() in t.lower():
                return t
            if self.pj.aviso():
                raise ProJurisErro(f"Em vez da janela '{titulo_esperado}', o ProJuris avisou: {self.pj.aviso()}")
            self.pg.wait_for_timeout(200)
        raise ProJurisErro(f"A janela '{titulo_esperado}' não abriu.")

    def _fechar(self):
        """Fecha a janela ativa pelo X (equivale a Cancelar). Nunca salva."""
        x = self.pg.locator(f"{JANELA_ATIVA} .janela-fechar")
        if x.count():
            x.first.click()
            self.pg.wait_for_timeout(300)
        if self.pg.evaluate(_JS_TITULO):
            raise ProJurisErro("A janela não fechou — PARE e confira a tela.")

    def _campo(self, nome: str):
        c = self.pg.locator(f"{JANELA_ATIVA} .campo[data-campo='{nome}']")
        if c.count() != 1:
            raise ProJurisErro(f"Campo '{nome}' não encontrado no formulário.")
        return c

    def _texto(self, nome: str, valor: str):
        inp = self._campo(nome).locator("input")
        inp.fill(str(valor))
        inp.press("Tab")

    _data = _texto

    def _check(self, nome: str, marcado: bool = True):
        self._campo(nome).locator("input[type=checkbox]").set_checked(marcado)

    def _radio(self, nome: str, valor: str):
        el = self._campo(nome).locator(f"input[type=radio][value='{valor}']")
        if el.count() != 1:
            raise ProJurisErro(f"Opção {nome}={valor} não encontrada.")
        el.check()

    def _arquivo(self, nome: str, arq: Path):
        self._campo(nome).locator("input[type=file]").set_input_files(str(arq))

    def _combo(self, nome: str, texto: str = "", valor_id=None, busca: str | None = None) -> str:
        """Escolhe no combo como uma pessoa: digita (ou abre a setinha) e CLICA no item."""
        el = self._campo(nome)
        cargas = int(el.get_attribute("data-cargas") or 0)
        q = texto if busca is None else busca
        caixa = el.locator(".combo-texto")
        if len(q) >= 2:
            caixa.click()
            caixa.fill("")
            caixa.type(q, delay=35)
        else:
            q = ""
            el.locator(".combo-seta").click()
        fim = time.time() + 15
        while time.time() < fim:
            ok = el.evaluate("(e, [n, q]) => Number(e.dataset.cargas) > n && e.dataset.carregando === '0'"
                             " && e.dataset.ultimaConsulta === q", [cargas, q])
            if ok:
                break
            self.pg.wait_for_timeout(150)
        else:
            raise ProJurisErro(f"A lista de '{nome}' não carregou.")
        itens = el.evaluate("e => [...e.querySelectorAll('.combo-lista li[data-valor]')]"
                            ".map((li, i) => ({i, v: li.dataset.valor, t: li.textContent}))")
        if valor_id is not None:
            alvo = [r for r in itens if str(r["v"]) == str(valor_id)]
        else:
            alvo = [r for r in itens if r["t"].strip() == texto.strip()] or \
                   [r for r in itens if _n(r["t"]) == _n(texto)]
        if len(alvo) != 1:
            caixa.press("Escape")
            achou = ", ".join(r["t"] for r in itens[:8])
            raise ProJurisErro(f"'{texto or valor_id}' não encontrado (ou repetido) na lista de '{nome}'"
                               f" — a lista trouxe: {achou or 'nada'}")
        item = el.locator(".combo-lista li[data-valor]").nth(alvo[0]["i"])
        if not item.is_visible():                 # lista recolheu (perdeu o foco): reabre só a exibição
            el.evaluate("e => e.classList.add('aberto')")
        item.scroll_into_view_if_needed()
        item.click()
        self.pg.wait_for_timeout(250)
        valor = el.locator(".combo-valor").input_value()
        escolhido = caixa.input_value()
        if str(valor) != str(alvo[0]["v"]) or escolhido.strip() != alvo[0]["t"].strip():
            raise ProJurisErro(f"A lista de '{nome}' ficou com '{escolhido}' em vez de '{alvo[0]['t']}'.")
        return escolhido

    def _conferir(self, etapa: str, sufixo: str = "") -> Ensaio:
        r = self.pg.evaluate(_JS_LER) or {"valores": {}, "invalidos": []}
        arq = self.prints / f"{etapa}{sufixo}.png"
        self.pg.screenshot(path=str(arq))
        return Ensaio(etapa, r["valores"], r["invalidos"], print_=str(arq))

    def _botao(self, texto: str):
        b = self.pg.locator("button:visible", has_text=re.compile(rf"^\s*{re.escape(texto)}\s*$"))
        if b.count() != 1:
            raise ProJurisErro(f"Esperava 1 botão '{texto}' visível, achei {b.count()}.")
        b.first.click()

    def _abrir(self, botao: str, titulo: str):
        """Clica no botão que ABRE uma janela e espera por ela. Abrir é idempotente, então um
        clique perdido pode ser repetido. (O "Salvar" nunca é repetido — ver gravar.py.)"""
        for tentativa in range(3):
            self._botao(botao)
            try:
                return self._janela(titulo, seg=5)
            except ProJurisErro:
                if tentativa == 2 or self.pj.aviso():
                    raise

    def _limpar_selecao(self, store: str):
        for c in self.pg.locator(f"[data-store='{store}'] input.sel-linha:checked").all():
            c.uncheck()

    def _selecionar_fase(self, data: str, fase_nome: str):
        self._limpar_selecao("fases")
        ids = self.pg.evaluate("([d, f]) => PJ.stores.fases.registros.filter(r => r.data === d && r.fase === f)"
                               ".map(r => r.id)", [data, fase_nome])
        if len(ids) != 1:
            raise ProJurisErro(f"Não achei uma única fase '{fase_nome}' de {data} (achei {len(ids)}).")
        self.pg.locator(f"[data-store='fases'] tr[data-id='{ids[0]}'] input.sel-linha").check()
        return ids[0]

    # ---------- preenchimento das telas (usado no ensaio e na gravação) ----------
    def preencher_fase(self, atual, dados: dict):
        self._data("DATA", dados["data"])
        self._combo("TIPO_RECURSO", R.FASE_TIPO_RECURSO)
        self._texto("NUMERO_ORIGINAL", atual.numero or dados["cnj"])
        self._combo("ID_FASE", R.FASE_NOME)
        self._combo("ID_TRIBUNAL", atual.tribunal)
        self._combo("ID_JURISDICAO", atual.jurisdicao)
        self._combo("ID_UF", atual.uf)              # clique no item -> carrega as comarcas da UF
        self._combo("ID_COMARCA", atual.comarca)
        self._check("ATUAL", True)

    def preencher_decisao(self, dados: dict):
        self._data("DATA_DECISAO", dados["data"])
        self._combo("ID_DECISAO", dados["decisao"])  # texto exato: há "Procedente em Parte" duplicado
        self._radio("DECISAO_OBJETO", dados["predominante"])

    def preencher_evento(self, fase_rotulo: str, dados: dict):
        self._data("DATA", dados["data"])
        self._combo("ID_EVENTO", dados["evento"], valor_id=dados["evento_id"], busca=dados["evento"][:20])
        self._combo("ID_PROCESSO_DESDOBRAMENTO", fase_rotulo, busca="")

    def preencher_documento(self, pdf: Path, dados: dict):
        self._arquivo("ARQUIVO", pdf)
        self._combo("ID_TIPO_DOCUMENTO", R.TIPO_DOCUMENTO)
        self._data("DATA", dados["data"])

    def _etapa(self, nome: str, fn) -> Ensaio:
        try:
            ens = fn()
        except Exception as e:                       # registra, fecha a janela e segue p/ a próxima
            arq = self.prints / f"{nome}_erro.png"
            try:
                self.pg.screenshot(path=str(arq))
            except Exception:
                pass
            ens = Ensaio(nome, erro=str(e), print_=str(arq))
        self._fechar()
        return ens

    # ---------- ENSAIO das 4 telas ----------
    def ensaiar(self, proc: Processo, dados: dict, pdf: Path) -> list[Ensaio]:
        """dados: data, cnj, decisao, predominante (F/D/P), evento_id, evento."""
        atual = proc.fase_atual
        if not atual:
            raise ProJurisErro("Processo sem uma fase atual.")
        self.pj.abrir_processo(proc.id)              # tela limpa
        out = []

        def fase():
            self.pj.aba("fases (instâncias)", "fases")
            self._limpar_selecao("fases")
            self._abrir("Adicionar", "Fases do Processo - Adicionar")
            self.preencher_fase(atual, dados)
            return self._conferir("ensaio_1_fase")
        out.append(self._etapa("ensaio_1_fase", fase))

        def decisao():
            self.pj.aba("fases (instâncias)", "fases")
            if atual.julgado:
                raise ProJurisErro("A fase atual já tem decisão — ensaio da decisão pulado.")
            self._selecionar_fase(atual.data, atual.fase)
            self._abrir("Registrar Decisão", "Registrar Decisão")
            self.preencher_decisao(dados)
            return self._conferir("ensaio_2_decisao")
        out.append(self._etapa("ensaio_2_decisao", decisao))

        def evento():
            self.pj.aba("eventos", "eventos")
            self._abrir("Adicionar", "Eventos do Processo")
            self.preencher_evento(atual.rotulo, dados)
            return self._conferir("ensaio_3_evento")
        out.append(self._etapa("ensaio_3_evento", evento))

        def documento():
            self.pj.aba("documentos", "documentos")
            self._abrir("Adicionar", "Documentos do Processo")
            self.preencher_documento(pdf, dados)
            return self._conferir("ensaio_4_documento")
        out.append(self._etapa("ensaio_4_documento", documento))
        return out
