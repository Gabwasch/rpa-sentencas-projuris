"""
ProJuris — LEITURA pela sessão já aberta no Chrome (Playwright conectado via CDP).

O robô NUNCA faz login: o operador abre o Chrome do robô (porta de depuração), entra no
ProJuris e o robô usa essa sessão. Se cair na tela de login, para com `SemSessao` (código 2).

Neste repositório o alvo é o mock (`mock/`). No sistema real (ExtJS 3) o adaptador lê os
*stores* dos componentes Ext (`Ext.ComponentMgr`); o mock expõe o equivalente em
`window.PJ.stores` e as grades/janelas em HTML simples. O fluxo e as travas são os mesmos:
- pasta -> id interno pela Busca Rápida da lista PROCESSOS > Todos (campo padrão = Pasta),
  conferindo PASTA e CNJ do resultado;
- processo aberto por URL com o id interno; abas "fases (instâncias)", "eventos", "documentos".
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


class SemSessao(RuntimeError):
    """Sem Chrome / sem ProJuris aberto / sessão caiu na tela de login."""


class ProJurisErro(RuntimeError):
    """Tela diferente do esperado — o robô para em vez de improvisar."""


@dataclass
class Fase:
    id: int
    data: str
    fase: str
    numero: str
    tribunal: str
    jurisdicao: str
    uf: str
    comarca: str
    juiz: str
    atual: bool
    julgado: bool
    decisao: str = ""
    predominante: str = ""

    @property
    def rotulo(self) -> str:
        """Como a fase aparece no combo "Fase" do evento."""
        return f"{self.data}, {self.numero}, {self.fase}"


@dataclass
class Evento:
    id: int
    evento: str
    data: str
    fase: str
    requisicao: str = ""


@dataclass
class Documento:
    id: int
    nome: str
    tipo: str
    data: str
    evento: str = ""


@dataclass
class Processo:
    id: int
    pasta: str
    cnj: str
    fases: list = field(default_factory=list)
    eventos: list = field(default_factory=list)
    documentos: list = field(default_factory=list)

    @property
    def fase_atual(self) -> Fase | None:
        atuais = [f for f in self.fases if f.atual]
        return atuais[0] if len(atuais) == 1 else None


def eh_local(url: str) -> bool:
    return (urlparse(url).hostname or "") in ("127.0.0.1", "localhost", "::1")


class ProJuris:
    def __init__(self, url: str, cdp: str):
        self.url = url.rstrip("/")                  # ex.: http://127.0.0.1:8702/projuris
        self._pw = sync_playwright().start()
        try:
            self.b = self._pw.chromium.connect_over_cdp(cdp)
        except Exception:
            self._pw.stop()
            raise SemSessao(f"Não encontrei o Chrome do robô aberto ({cdp}). "
                            "Abra o Chrome do robô e faça o login no ProJuris.") from None
        paginas = [p for c in self.b.contexts for p in c.pages if (p.url or "").startswith(self.url)]
        if not paginas:
            self.fechar()
            raise SemSessao("O Chrome do robô está aberto, mas sem o ProJuris. Entre no ProJuris nele.")
        self.pg = paginas[0]
        self.checar_sessao()
        # Chrome sem janela às vezes ignora o 1º evento de mouse logo após conectar: "acorda" a aba
        self.pg.bring_to_front()
        self.pg.mouse.move(5, 5)

    def fechar(self):
        """Solta a conexão com o Chrome (não fecha o navegador do operador)."""
        try:
            self._pw.stop()
        except Exception:
            pass

    # ---- sessão ----
    def checar_sessao(self):
        if "/login" in self.pg.url or self.pg.locator("input[name=senha]:visible").count():
            raise SemSessao("A sessão do ProJuris caiu (tela de login). Faça o login no Chrome do "
                            "robô e rode de novo — o robô não digita senha.")
        if not self.pg.evaluate("() => !!window.PJ"):
            raise SemSessao("O ProJuris ainda não terminou de carregar. Aguarde e rode de novo.")

    def esperar(self, js: str, arg=None, seg: float = 20):
        fim = time.time() + seg
        while time.time() < fim:
            v = self.pg.evaluate(js, arg)
            if v:
                return v
            self.pg.wait_for_timeout(200)
        return None

    def aviso(self) -> str:
        """Texto do aviso (caixa de mensagem) visível, ou ''. Só LÊ — quem decide é quem pediu a leitura."""
        return self.pg.evaluate("""() => { const m = document.getElementById('pj-msg');
            return m && m.classList.contains('visivel') ? m.querySelector('.msg-texto').innerText.trim() : ''; }""")

    def botoes_aviso(self) -> list[str]:
        return self.pg.evaluate("""() => [...document.querySelectorAll('#pj-msg.visivel .msg-botoes button')]
            .map(b => b.innerText.trim())""")

    # ---- pasta -> id ----
    def _abrir_lista(self):
        lista_visivel = "() => !!document.querySelector('#painel-lista.visivel') && !!(PJ.stores.lista||{}).carregado"
        if self.pg.evaluate(lista_visivel):
            return
        if urlparse(self.pg.url).path.rstrip("/") != urlparse(self.url).path.rstrip("/"):
            self.pg.goto(self.url + "/", wait_until="domcontentloaded")
            self.checar_sessao()
        # menu lateral: Processos > Todos (o "Todos" de PROCESSOS, não o da Agenda)
        raiz = self.pg.locator("li.no").filter(
            has=self.pg.locator("a.raiz", has_text=re.compile(r"^\s*Processos\s*$")))
        if raiz.count() != 1:
            raise ProJurisErro("Não achei o menu Processos do ProJuris.")
        todos = raiz.locator("ul.sub a.no-ancora", has_text=re.compile(r"^\s*Todos\s*$"))
        if todos.count() != 1:
            raise ProJurisErro("Não achei o item Processos > Todos do menu.")
        # o clique em "Processos" abre OU fecha o menu -> confere e tenta de novo
        for _ in range(3):
            if todos.is_visible():
                break
            raiz.locator("a.raiz").click()
            self._visivel_logo(todos)
        if not todos.is_visible():
            raise ProJurisErro("O menu Processos não abriu.")
        for _ in range(3):
            todos.click()
            if self.esperar(lista_visivel, seg=6):
                return
        raise ProJurisErro("Não consegui abrir a lista de processos do ProJuris.")

    def _visivel_logo(self, loc, seg: float = 1.5) -> bool:
        fim = time.time() + seg
        while time.time() < fim:
            if loc.is_visible():
                return True
            self.pg.wait_for_timeout(100)
        return False

    def buscar_pasta(self, pasta: str) -> list[dict]:
        """Busca Rápida da lista de processos (campo Pasta). Devolve [{id, pasta, cnj, status}]."""
        self.checar_sessao()
        self._abrir_lista()
        self.pg.select_option("#busca-campo", "pasta")
        versao = self.pg.evaluate("() => PJ.stores.lista.versao")
        campo = self.pg.locator("#busca-rapida")
        campo.fill(str(pasta))
        campo.press("Enter")
        if not self.esperar("(v) => PJ.stores.lista.carregado && PJ.stores.lista.versao > v", versao, seg=20):
            raise ProJurisErro(f"A busca da pasta {pasta} não respondeu.")
        regs = self.pg.evaluate("() => PJ.stores.lista.registros")
        return [{"id": r["id"], "pasta": str(r["pasta"]), "cnj": r["cnj"], "status": r["status"]}
                for r in regs if str(r["pasta"]).strip() == str(pasta).strip()]

    # ---- leitura do processo ----
    def aba(self, nome: str, store: str) -> list[dict]:
        """Clica na aba (como uma pessoa) e espera o store dela recarregar."""
        aba = self.pg.locator(".abas .aba", has_text=re.compile(rf"^\s*{re.escape(nome)}\s*$"))
        if not aba.count():
            raise ProJurisErro(f"Aba '{nome}' não encontrada no processo.")
        if self.aviso():
            raise ProJurisErro(f"O ProJuris mostrou um aviso: {self.aviso()}")
        versao = self.pg.evaluate("(s) => (PJ.stores[s] || {versao: 0}).versao", store)
        ok = None
        for _ in range(3):                      # clique não registrado -> confere e clica de novo
            aba.first.click()
            ok = self.esperar("([s, v]) => PJ.stores[s] && PJ.stores[s].carregado && PJ.stores[s].versao > v",
                              [store, versao], seg=7)
            if ok:
                break
        if not ok:
            raise ProJurisErro(f"A aba '{nome}' não carregou.")
        return self.pg.evaluate("(s) => PJ.stores[s].registros", store)

    def abrir_processo(self, id_processo: int):
        self.checar_sessao()
        self.pg.goto(f"{self.url}/processo/{int(id_processo)}", wait_until="domcontentloaded")
        self.checar_sessao()
        if not self.esperar("() => document.getElementById('cabecalho')?.dataset.pronto === '1'", seg=20):
            raise ProJurisErro(f"O processo {id_processo} não abriu.")

    def ler_processo(self, id_processo: int) -> Processo:
        self.abrir_processo(id_processo)
        cab = self.pg.evaluate("() => ({...document.getElementById('cabecalho').dataset})")
        proc = Processo(id=int(id_processo), pasta=cab.get("pasta", ""), cnj=cab.get("cnj", ""))
        for d in self.aba("fases (instâncias)", "fases"):
            proc.fases.append(Fase(id=d["id"], data=d["data"], fase=d["fase"], numero=d["numero"],
                                   tribunal=d["tribunal"], jurisdicao=d["jurisdicao"], uf=d["uf"],
                                   comarca=d["comarca"], juiz=d.get("juiz", ""), atual=bool(d["atual"]),
                                   julgado=bool(d["julgado"]), decisao=d.get("decisao", ""),
                                   predominante=d.get("predominante", "")))
        for d in self.aba("eventos", "eventos"):
            proc.eventos.append(Evento(id=d["id"], evento=d["evento"], data=d["data"], fase=d.get("fase", ""),
                                       requisicao=str(d.get("requisicao") or "")))
        for d in self.aba("documentos", "documentos"):
            proc.documentos.append(Documento(id=d["id"], nome=d["nome"], tipo=d["tipo"], data=d["data"],
                                             evento=d.get("evento", "")))
        return proc
