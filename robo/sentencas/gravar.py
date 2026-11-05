"""
GRAVAÇÃO no ProJuris (fase -> decisão -> evento -> documento) — um processo por vez.

Travas:
- só processos listados em config.toml [gravacao] liberados;
- antes de CADA "Salvar": mostra o que foi preenchido e pergunta S/N (N = fecha sem salvar e para);
- campo inválido no formulário -> não salva;
- depois de cada "Salvar": confere relendo os dados; se não confirmou, PARA;
- se o ProJuris mostrar pergunta/aviso depois do Salvar, o robô NÃO responde: para e avisa.
  Única exceção: o aviso informativo "Requisição N cadastrada com sucesso" (só botão OK), que o
  sistema mostra sempre que um evento é cadastrado — igual ao lançamento manual;
- auditoria (auditoria.jsonl) e print de cada etapa na pasta da execução.

Etapas iguais ao lançamento manual da equipe: fase nova "Sentença" (atual) -> Registrar Decisão
nessa fase -> evento ligado à fase nova -> PDF anexado DENTRO do evento (ficha do evento).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from . import regras as R
from .lancar import JANELA_ATIVA, Formularios, _n
from .projuris import Processo, ProJuris, ProJurisErro

AVISO_CONHECIDO = re.compile(r"requisi\w*\s+\d+\s+cadastrad\w*\s+com\s+sucesso", re.I)


class Parado(RuntimeError):
    """Gravação interrompida (pelo operador ou por segurança)."""


class Gravacao(Formularios):
    def __init__(self, pj: ProJuris, pasta: Path, perguntar=None):
        super().__init__(pj, pasta)
        self.perguntar = perguntar            # função(texto) -> bool ; None = nunca grava
        self.log = Path(pasta) / "auditoria.jsonl"

    # ---------- registro ----------
    def _audit(self, etapa: str, **kw):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"quando": datetime.now().isoformat(timespec="seconds"), "etapa": etapa, **kw},
                               ensure_ascii=False, default=str) + "\n")

    def _sim(self, texto: str) -> bool:
        return bool(self.perguntar and self.perguntar(texto))

    # ---------- salvar com conferência ----------
    def _confirmar_e_salvar(self, etapa: str, titulo: str):
        ens = self._conferir(etapa, "_preenchido")
        print(f"\n   === {titulo} ===")
        for k, v in ens.preenchido.items():
            print(f"      {k}: {v}")
        if ens.invalidos:
            self._audit(etapa, resultado="campos inválidos", invalidos=ens.invalidos, valores=ens.preenchido)
            self._fechar()
            raise Parado(f"O formulário tem campos inválidos ({', '.join(ens.invalidos)}). Nada salvo nesta etapa.")
        if not self._sim(f"Salvar {titulo}? [S/N]: "):
            self._audit(etapa, resultado="não confirmado", valores=ens.preenchido)
            self._fechar()
            raise Parado(f"{titulo}: não confirmado — janela fechada sem salvar.")
        btn = self.pg.locator(f"{JANELA_ATIVA} button", has_text=re.compile(r"^\s*Salvar\s*$"))
        if btn.count() != 1:
            raise Parado(f"Não achei um único botão 'Salvar' na janela ({btn.count()}).")
        btn.click()

        fim, fechou_em = time.time() + 30, None
        while time.time() < fim:
            txt = self.pj.aviso()
            if txt:
                botoes = self.pj.botoes_aviso()
                if AVISO_CONHECIDO.search(txt) and botoes == ["OK"]:
                    num = re.findall(r"\d{3,}", txt)
                    self._audit(etapa, resultado="requisição criada pelo ProJuris", aviso=txt, requisicao=num)
                    print(f"      (o ProJuris criou a requisição {', '.join(num)} — normal, igual ao lançamento manual)")
                    self.pg.locator("#pj-msg .msg-botoes button", has_text="OK").click()
                    fechou_em = None
                    continue
                self.pg.screenshot(path=str(self.prints / f"{etapa}_aviso.png"))
                self._audit(etapa, resultado="ProJuris respondeu com aviso", aviso=txt, botoes=botoes)
                raise Parado(f"Depois do Salvar, o ProJuris mostrou: \"{txt}\" (botões {botoes}). "
                             "O robô NÃO respondeu — confira a tela.")
            if not self.pg.evaluate(f"() => !!document.querySelector('{JANELA_ATIVA}')"):
                fechou_em = fechou_em or time.time()
                if time.time() - fechou_em > 1.2:      # janela fechada e nenhum aviso atrasado
                    break
            self.pg.wait_for_timeout(200)
        else:
            raise Parado(f"{titulo}: a janela não fechou depois do Salvar — confira a tela.")
        self.pg.screenshot(path=str(self.prints / f"{etapa}_salvo.png"))
        self._audit(etapa, resultado="salvo", valores=ens.preenchido)
        print("      -> salvo.")

    def _esperar_store(self, store: str, versao: int, teste, descricao: str):
        """Confere sem sair da tela: espera o store recarregar e o registro aparecer."""
        fim = time.time() + 15
        while time.time() < fim:
            s = self.pg.evaluate("(s) => PJ.stores[s] || null", store)
            if s and s["carregado"] and s["versao"] > versao and any(teste(r) for r in s["registros"]):
                return [r for r in s["registros"] if teste(r)]
            self.pg.wait_for_timeout(250)
        raise Parado(f"Conferência: {descricao} não apareceu depois do Salvar.")

    def _versao(self, store: str) -> int:
        return self.pg.evaluate("(s) => (PJ.stores[s] || {versao: 0}).versao", store)

    # ---------- as 4 etapas ----------
    def gravar(self, proc: Processo, dados: dict, pdf: Path) -> dict:
        """dados: data, cnj, decisao, predominante, evento_id, evento."""
        atual = proc.fase_atual
        if not atual:
            raise Parado("Processo sem uma fase atual.")
        self._audit("inicio", processo=proc.id, pasta=proc.pasta, cnj=proc.cnj, dados=dados, pdf=pdf.name)
        feito = {"fase": False, "decisao": False, "evento": False, "documento": False}
        try:
            # 1) FASE nova "Sentença", atual (tribunal/jurisdição/UF/comarca copiados da fase atual)
            self.pj.abrir_processo(proc.id)
            self.pj.aba("fases (instâncias)", "fases")
            self._limpar_selecao("fases")
            self._abrir("Adicionar", "Fases do Processo - Adicionar")
            self.preencher_fase(atual, dados)
            self._confirmar_e_salvar("1_fase", "a FASE nova (Sentença)")
            p2 = self.pj.ler_processo(proc.id)
            novas = [f for f in p2.fases if _n(f.fase) == _n(R.FASE_NOME) and f.data == dados["data"]]
            if len(novas) != 1:
                raise Parado(f"Conferência: esperava 1 fase Sentença de {dados['data']}, achei {len(novas)}.")
            nova = novas[0]
            if not nova.atual:
                raise Parado("Conferência: a fase Sentença foi criada mas NÃO ficou como atual.")
            feito["fase"] = True
            self._audit("1_fase", resultado="conferido", fase_id=nova.id, atual=nova.atual)
            print(f"      conferido: fase Sentença {nova.data} (atual)")

            # 2) DECISÃO na fase nova
            self.pj.aba("fases (instâncias)", "fases")
            self._selecionar_fase(nova.data, R.FASE_NOME)
            self._abrir("Registrar Decisão", "Registrar Decisão")
            self.preencher_decisao(dados)
            self._confirmar_e_salvar("2_decisao", "a DECISÃO na fase Sentença")
            p3 = self.pj.ler_processo(proc.id)
            f3 = [f for f in p3.fases if f.id == nova.id]
            if not f3 or not f3[0].julgado or f3[0].decisao != dados["decisao"]:
                raise Parado("Conferência: a fase Sentença não aparece julgada com a decisão esperada.")
            feito["decisao"] = True
            self._audit("2_decisao", resultado="conferido", decisao=f3[0].decisao, predominante=f3[0].predominante)
            print(f"      conferido: fase Sentença julgada ({f3[0].decisao} · {R.NOME_PREDOMINANTE[f3[0].predominante]})")

            # 3) EVENTO ligado à fase nova
            self.pj.aba("eventos", "eventos")
            self._abrir("Adicionar", "Eventos do Processo")
            self.preencher_evento(nova.rotulo, dados)
            v_ev = self._versao("eventos")
            self._confirmar_e_salvar("3_evento", "o EVENTO")
            ev = self._esperar_store("eventos", v_ev, lambda r: r["evento_id"] == dados["evento_id"]
                                     and r["data"] == dados["data"] and r["fase_id"] == nova.id, "o evento")
            feito["evento"] = True
            self._audit("3_evento", resultado="conferido", evento_id=ev[-1]["id"], requisicao=ev[-1].get("requisicao"))
            print(f"      conferido: evento '{ev[-1]['evento']}' ligado à fase Sentença")

            # 4) DOCUMENTO dentro da ficha do evento (abre sozinha depois do OK do aviso)
            self._documento_no_evento(dados, pdf, ev[-1]["id"])
            feito["documento"] = True
        finally:
            self._audit("fim" if all(feito.values()) else "fim_parcial", feito=feito)
        return self.conferencia_final(proc.id, dados, pdf)

    def conferencia_final(self, id_processo: int, dados: dict, pdf: Path) -> dict:
        p = self.pj.ler_processo(id_processo)
        ev = [e for e in p.eventos if _n(e.evento) == _n(dados["evento"]) and e.data == dados["data"]]
        doc = [d for d in p.documentos if _n(d.nome) == _n(pdf.name)]
        final = {"evento": [f"{e.data} | {e.evento} | fase {e.fase} | requisição {e.requisicao}" for e in ev],
                 "documento": [f"{d.data} | {d.tipo} | {d.nome} | no evento: {d.evento or '(processo)'}" for d in doc],
                 "documento_no_evento": any(_n(d.evento) == _n(dados["evento"]) for d in doc)}
        self._audit("conferencia_final", **final)
        return final

    def _documento_no_evento(self, dados: dict, pdf: Path, evento_id: int | None = None,
                             ficha_ja_aberta: bool = True):
        aba = self._esperar_ficha(dados, seg=10) if ficha_ja_aberta else None
        if not aba:
            aba = self._abrir_ficha_evento(dados)
        if not aba:
            raise Parado("O evento foi salvo, mas não achei a ficha do evento para anexar o PDF. "
                         "Anexe o PDF à mão no evento (ou rode o subcomando 'anexar').")
        self.pg.screenshot(path=str(self.prints / "4_ficha_evento.png"))
        eid = int(aba.get_attribute("data-aba").split("-")[1])
        if evento_id is not None and eid != evento_id:
            raise Parado(f"A ficha aberta é do evento {eid}, esperava {evento_id}.")
        botao = self.pg.locator(".painel-aba.visivel button.adicionar-doc-evento")
        if botao.count() != 1:
            raise Parado("Achei a ficha do evento, mas não o botão 'Adicionar' dos documentos do evento.")
        if not self._sim(f"Abrir 'Adicionar documento' DENTRO do evento para anexar {pdf.name}? [S/N]: "):
            raise Parado("Anexo do PDF não confirmado — evento salvo sem o documento (use 'anexar' depois).")
        botao.click()
        self._janela("Documento do Evento")
        self.preencher_documento(pdf, dados)
        store = f"evdocs-{eid}"
        v = self._versao(store)
        self._confirmar_e_salvar("4_documento", f"o DOCUMENTO {pdf.name} no evento")
        self._esperar_store(store, v, lambda r: _n(r["nome"]) == _n(pdf.name), "o documento no evento")
        self._audit("4_documento", resultado="conferido", evento_id=eid, documento=pdf.name)
        print(f"      conferido: {pdf.name} na lista de documentos do evento")

    def _esperar_ficha(self, dados: dict, seg: float):
        alvo = _n(f"Evento: {dados['evento']}")
        fim = time.time() + seg
        while time.time() < fim:
            for a in self.pg.locator(".abas .aba[data-aba^='evento-']").all():
                if _n(a.inner_text()).startswith(alvo):
                    if "ativa" not in (a.get_attribute("class") or ""):
                        a.click()
                    return a
            self.pg.wait_for_timeout(250)
        return None

    def _abrir_ficha_evento(self, dados: dict):
        """Abre a ficha do evento pelo link na lista de eventos."""
        regs = self.pj.aba("eventos", "eventos")
        alvo = [r for r in regs if r["evento_id"] == dados["evento_id"] and r["data"] == dados["data"]]
        if len(alvo) != 1:
            raise Parado(f"Esperava 1 evento '{dados['evento']}' de {dados['data']}, achei {len(alvo)}.")
        self.pg.locator(f"a.link-evento[data-id='{alvo[0]['id']}']").click()
        return self._esperar_ficha(dados, seg=10)

    def anexar(self, proc: Processo, dados: dict, pdf: Path) -> dict:
        """Só a etapa 4: o evento JÁ existe (ex.: a gravação parou depois do evento)."""
        self._audit("anexar_inicio", processo=proc.id, pasta=proc.pasta, pdf=pdf.name, dados=dados)
        p = self.pj.ler_processo(proc.id)
        if [d for d in p.documentos if _n(d.nome) == _n(pdf.name)]:
            raise Parado(f"O documento {pdf.name} já está no processo — nada a fazer.")
        ev = [e for e in p.eventos if _n(e.evento) == _n(dados["evento"]) and e.data == dados["data"]]
        if len(ev) != 1:
            raise Parado(f"Esperava 1 evento '{dados['evento']}' de {dados['data']} no ProJuris, achei {len(ev)}.")
        self._documento_no_evento(dados, pdf, ev[0].id, ficha_ja_aberta=False)
        return self.conferencia_final(proc.id, dados, pdf)


def fechar_janela_aberta(pj: ProJuris) -> bool:
    """Depois de um erro: fecha (sem salvar) a janela de cadastro que tiver ficado aberta."""
    try:
        x = pj.pg.locator(f"{JANELA_ATIVA} .janela-fechar")
        if x.count():
            x.first.click()
            return True
    except Exception:
        pass
    return False


__all__ = ["Gravacao", "Parado", "fechar_janela_aberta", "ProJurisErro"]
