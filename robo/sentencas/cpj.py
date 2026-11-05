"""
Cliente da API REST do CPJ (v3) — SOMENTE LEITURA — e a busca das decisões pendentes.

Credenciais no `.env` ao lado do robô (CPJ_BASE_URL, CPJ_LOGIN, CPJ_SENHA) ou em variáveis de
ambiente com os mesmos nomes — nunca no código, no git ou no log.

Como o CPJ organiza o que o robô precisa:
- A equipe lança no processo o evento DECx (situação "Pendente") a partir da publicação (SNE).
  O DEC é "filho" do SNE (`id_tramitacao_pai`) e o PDF da sentença fica anexado ao DEC
  (documento com `id_origem` == `id_tramitacao` do DEC).
- `sigla_integracao` do processo = PASTA do ProJuris.
- Não há rota de tramitações por evento: lista os processos ATIVOS do grupo de trabalho e lê
  as tramitações de cada um, em paralelo.
- Processos de OUTROS grupos nunca entram: filtro na consulta E conferência de novo em cada
  registro (o mesmo CNJ pode estar cadastrado para outro cliente, em outro grupo).
"""
from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from . import regras as R
from .cnj import so_digitos


class CPJIndisponivel(RuntimeError):
    """A API falhou de um jeito que NÃO permite concluir nada (nunca vira 'não encontrado')."""


CHAVES_ENV = ("CPJ_BASE_URL", "CPJ_LOGIN", "CPJ_SENHA")


def carregar_env(arq: Path | None) -> dict:
    """Lê o .env (se existir) e completa com as variáveis de ambiente."""
    env: dict[str, str] = {}
    if arq and Path(arq).exists():
        for linha in Path(arq).read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.strip().startswith("#"):
                k, v = linha.split("=", 1)
                env[k.strip()] = v.strip()
    for k in CHAVES_ENV:
        if not env.get(k) and os.environ.get(k):
            env[k] = os.environ[k]
    faltando = [k for k in CHAVES_ENV if not env.get(k)]
    if faltando:
        raise CPJIndisponivel(f"Credenciais do CPJ incompletas (faltando {', '.join(faltando)}): "
                              "crie o .env ao lado do robô (veja .env.exemplo).")
    return env


def nome_doc(d: dict) -> str:
    """O `path` às vezes vem com o caminho de rede inteiro (G:\\Setor\\...\\arquivo.pdf)."""
    return re.split(r"[\\/]", d.get("path") or "")[-1]


class CPJ:
    def __init__(self, env: dict, grupo_trabalho: int | None = R.GRUPO_TRABALHO, sessao=None,
                 dormir=time.sleep, por_pagina: int = 200):
        self._env = env
        self.grupo_trabalho = grupo_trabalho
        self.base = env["CPJ_BASE_URL"].rstrip("/") + "/api/v3"
        self.s = sessao or requests.Session()        # injetável (testes usam o TestClient do mock)
        self.s.headers.update({"Accept": "application/json"})
        self._dormir = dormir
        self.por_pagina = por_pagina
        self._login()

    # ---- transporte ----
    def _login(self, tentativas: int = 4) -> None:
        """A API às vezes não responde ao login e logo depois responde rápido -> timeout curto +
        novas tentativas. Credencial recusada (4xx) não adianta repetir."""
        ultimo = "sem resposta"
        for n in range(tentativas):
            try:
                r = self.s.post(f"{self.base}/login", timeout=20,
                                json={"login": self._env["CPJ_LOGIN"], "password": self._env["CPJ_SENHA"]})
            except requests.RequestException as e:
                ultimo = type(e).__name__
                self._dormir(3 * (n + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = f"HTTP {r.status_code}"
                self._dormir(3 * (n + 1))
                continue
            try:
                r.raise_for_status()
                self.s.headers["Authorization"] = "Bearer " + r.json()["token"]
                return
            except Exception as e:     # sem detalhes: a resposta pode ecoar dados da credencial
                raise CPJIndisponivel(f"A API do CPJ recusou o login ({type(e).__name__}; "
                                      f"HTTP {r.status_code}). Confira o .env.") from None
        raise CPJIndisponivel(f"Não consegui entrar na API do CPJ ({ultimo}, {tentativas} tentativas).")

    def _req(self, caminho: str, params: dict, tentativas: int = 5):
        """GET com novas tentativas p/ falha passageira (rede, 401 token vencido, 429, 5xx).
        Sob carga a API devolve erro — e um processo parecia 'não encontrado'. Por isso aqui
        erro NUNCA vira resultado vazio."""
        ultimo = "sem resposta"
        for n in range(tentativas):
            try:
                r = self.s.get(f"{self.base}{caminho}", params=params, timeout=120)
            except requests.RequestException as e:
                ultimo = type(e).__name__
                self._dormir(2 * (n + 1))
                continue
            if r.status_code == 401:
                ultimo = "HTTP 401"
                self._login()
                continue
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = f"HTTP {r.status_code}"
                espera = r.headers.get("Retry-After")
                self._dormir(float(espera) if espera and espera.isdigit() else 3 * (n + 1))
                continue
            return r
        raise CPJIndisponivel(f"A API do CPJ não respondeu ({caminho}; {ultimo}).")

    def get(self, caminho: str, params: dict | None = None) -> list:
        """GET paginado (envelope data/total_page). 404/204 -> lista vazia (é a resposta de
        'não existe'); qualquer outro erro -> CPJIndisponivel."""
        params = dict(params or {})
        params.setdefault("per_page", self.por_pagina)
        params["current_page"] = 1
        itens: list = []
        while True:
            r = self._req(caminho, params)
            if r.status_code in (204, 404) or not r.content:
                return itens
            if r.status_code >= 400:
                raise CPJIndisponivel(f"A API do CPJ recusou a consulta ({caminho}; HTTP {r.status_code}).")
            d = r.json()
            if isinstance(d, dict) and "data" in d:
                itens += d["data"] or []
                if params["current_page"] >= (d.get("total_page") or 1):
                    return itens
                params["current_page"] += 1
            else:
                return d if isinstance(d, list) else [d]

    def baixar(self, id_ged, destino: Path) -> Path:
        r = self._req(f"/documentos/{id_ged}", {})
        if r.status_code >= 400:
            raise CPJIndisponivel(f"Não consegui baixar o documento {id_ged} (HTTP {r.status_code}).")
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(r.content)
        return destino

    # ---- consultas ----
    def tramitacoes(self, pj: int) -> list[dict]:
        return [t for t in self.get(f"/processos/{pj}/tramitacoes") if isinstance(t, dict)]

    def documentos(self, pj: int) -> list[dict]:
        return [d for d in self.get(f"/processos/{pj}/documentos") if isinstance(d, dict)]


# =========================================================================================
# Decisões pendentes
# =========================================================================================
def _grupo(p: dict):
    g = p.get("grupo_trabalho")
    return g.get("value") if isinstance(g, dict) else g


def do_grupo(p: dict, grupo: int = R.GRUPO_TRABALHO) -> bool:
    try:
        return int(_grupo(p)) == grupo
    except (TypeError, ValueError):
        return False


def _data(iso: str | None) -> str:
    """'2026-11-04T10:45:26.000-03:00' -> '04/11/2026'"""
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso[:19]).strftime("%d/%m/%Y")
    except ValueError:
        return ""


@dataclass
class Dec:
    pj: int
    cnj: str
    pasta: str
    dec: str
    descricao: str
    id_tramitacao: int
    lancado_em: str                  # data do DEC no CPJ (dd/mm/aaaa)
    data_publicacao: str             # data do SNE (publicação) — usada no ProJuris
    jornal: str = ""                 # linha "Jornal: ..." do SNE (informativo)
    pdf: dict | None = None          # documento do CPJ anexado ao DEC
    outros_docs: list = field(default_factory=list)


def processos_ativos(cpj: CPJ) -> list[dict]:
    procs = cpj.get("/processos", {"filter[grupo_trabalho][_eq]": str(cpj.grupo_trabalho),
                                   "filter[arquivo][_eq]": "N"})
    # conferência de novo, registro a registro (não confiar só no filtro da API)
    return [p for p in procs if isinstance(p, dict) and p.get("pj") and do_grupo(p, cpj.grupo_trabalho)]


def processo_por_cnj(cpj: CPJ, cnj: str) -> dict | None:
    achados = cpj.get("/processos", {"filter[numero_processo_pesq][_eq]": so_digitos(cnj),
                                     "filter[grupo_trabalho][_eq]": str(cpj.grupo_trabalho)})
    achados = [p for p in achados if isinstance(p, dict) and p.get("pj") and do_grupo(p, cpj.grupo_trabalho)]
    achados.sort(key=lambda p: p.get("incidente") or 0)
    return achados[0] if achados else None


def _jornal(texto: str) -> str:
    m = re.search(r"Jornal:\s*([^\r\n]+)", texto or "")
    return m.group(1).strip() if m else ""


def decs_do_processo(cpj: CPJ, proc: dict, eventos: set[str], desde: date | None) -> list[Dec]:
    if not do_grupo(proc, cpj.grupo_trabalho):          # nunca processar outro grupo de trabalho
        return []
    pj = proc["pj"]
    tram = cpj.tramitacoes(pj)
    por_id = {t.get("id_tramitacao"): t for t in tram}
    alvo = []
    for t in tram:
        if (t.get("evento") or "") not in eventos:
            continue
        if (t.get("situacao_desc") or "").strip().lower() != "pendente":
            continue
        lan = (t.get("data_hora_lan") or "")[:10]
        if desde and lan and lan < desde.isoformat():
            continue
        alvo.append(t)
    if not alvo:
        return []
    docs = cpj.documentos(pj)
    out = []
    for t in alvo:
        pai = por_id.get(t.get("id_tramitacao_pai")) or {}
        anexos = [d for d in docs if d.get("id_origem") == t.get("id_tramitacao")]
        pdfs = sorted([d for d in anexos if nome_doc(d).lower().endswith(".pdf")],
                      key=lambda d: d.get("data_criacao") or "")
        out.append(Dec(
            pj=pj, cnj=proc.get("numero_processo") or "", pasta=str(proc.get("sigla_integracao") or "").strip(),
            dec=t["evento"], descricao=t.get("evento_desc") or "", id_tramitacao=t.get("id_tramitacao"),
            lancado_em=_data(t.get("data_hora_lan")),
            data_publicacao=_data(pai.get("data_hora_lan")) if pai.get("evento") == "SNE" else _data(t.get("data_hora_lan")),
            jornal=_jornal(pai.get("texto") or ""), pdf=pdfs[-1] if pdfs else None,
            outros_docs=[nome_doc(d) for d in anexos if d not in pdfs[-1:]]))
    return out


def decs_pendentes(cpj: CPJ, eventos: set[str], dias: int = 30, paralelo: int = 4, progresso=None) -> list[Dec]:
    """Varre os processos ativos do grupo e devolve os DECs pendentes lançados nos últimos `dias`."""
    desde = date.today() - timedelta(days=dias) if dias else None
    procs = processos_ativos(cpj)
    out: list[Dec] = []
    with ThreadPoolExecutor(max_workers=max(1, paralelo)) as ex:
        for feitos, res in enumerate(ex.map(lambda p: decs_do_processo(cpj, p, eventos, desde), procs), 1):
            out += res
            if progresso and feitos % 250 == 0:
                progresso(feitos, len(procs), len(out))
    if progresso:
        progresso(len(procs), len(procs), len(out))
    return out
