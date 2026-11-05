"""
Mock executável (um processo só) com os dois sistemas que o robô usa — dados FICTÍCIOS:

  /cpj/api/v3/...   API REST "tipo CPJ" (login com token Bearer, filtros filter[campo][_eq],
                    envelope de paginação data/total_page, download de documentos)
  /projuris/...     interface web "tipo ProJuris": login, menu lateral, lista com Busca Rápida,
                    página do processo com abas e janelas de cadastro

O ProJuris real é ExtJS 3; aqui o DOM é simplificado (HTML + JS puro), mas mantém o que importa
para o robô: combos dependentes que só carregam com interação "humana", opções duplicadas
parecidas, campos obrigatórios, avisos depois do Salvar e a ficha do evento com documentos.

    uvicorn mock.app:app --port 8702
"""
from __future__ import annotations

import base64
import copy
import json
import re
import unicodedata
import urllib.parse
from datetime import datetime
from pathlib import Path
from secrets import token_hex

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import seed as S

ESTATICOS = Path(__file__).parent / "static"
COOKIE = "pj_sessao"


def _n(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).lower().strip()


def _data_ok(v: str) -> bool:
    try:
        datetime.strptime(v or "", "%d/%m/%Y")
        return True
    except ValueError:
        return False


class Estado:
    """Banco em memória. `reset()` volta tudo ao seed (cada subida do mock começa limpa)."""

    def __init__(self, pasta: Path):
        self.pasta = Path(pasta)
        self.reset()

    def reset(self):
        self.dados = copy.deepcopy(S.gerar(self.pasta))
        self.tokens: set[str] = set()
        self.sessoes: set[str] = set()
        self.falhas_cpj: list[int] = []        # injeção de falhas p/ testes (ex.: [503, 429])
        self.uploads = self.pasta / "uploads"
        self.uploads.mkdir(parents=True, exist_ok=True)

    @property
    def cpj(self) -> dict:
        return self.dados["cpj"]

    @property
    def pj(self) -> dict:
        return self.dados["projuris"]

    def proc(self, pid: int) -> dict:
        for p in self.pj["processos"]:
            if p["id"] == pid:
                return p
        raise HTTPException(404, "processo não encontrado")

    def prox(self, k: str) -> int:
        v = self.pj["proximos"][k]
        self.pj["proximos"][k] = v + 1
        return v


def criar_app(pasta_dados: Path | None = None) -> FastAPI:
    app = FastAPI(title="Mock CPJ + ProJuris (dados fictícios)", docs_url="/docs")
    est = Estado(pasta_dados or S.PASTA_DADOS)
    app.state.estado = est
    app.mount("/projuris/static", StaticFiles(directory=ESTATICOS), name="static")

    @app.get("/saude")
    def saude():
        return {"ok": True}

    @app.post("/mock/reset")
    def reset():
        est.reset()
        return {"ok": True}

    @app.get("/mock/gabarito")
    def gabarito():
        return est.dados["gabarito"]

    # =====================================================================================
    # CPJ  (API REST)
    # =====================================================================================
    base = "/cpj/api/v3"

    def _auth(req: Request):
        if est.falhas_cpj:
            cod = est.falhas_cpj.pop(0)
            raise HTTPException(cod, "falha simulada", headers={"Retry-After": "0"} if cod == 429 else None)
        h = req.headers.get("authorization", "")
        if not h.startswith("Bearer ") or h[7:] not in est.tokens:
            raise HTTPException(401, "token inválido ou vencido")

    def _paginar(req: Request, itens: list) -> dict:
        por = max(1, min(int(req.query_params.get("per_page", 50)), 200))
        pag = max(1, int(req.query_params.get("current_page", 1)))
        total_page = max(1, -(-len(itens) // por))
        return {"data": itens[(pag - 1) * por: pag * por], "current_page": pag, "per_page": por,
                "total": len(itens), "total_page": total_page}

    @app.post(f"{base}/login")
    async def cpj_login(req: Request):
        if est.falhas_cpj:
            raise HTTPException(est.falhas_cpj.pop(0), "falha simulada")
        corpo = await req.json()
        if est.cpj["usuarios"].get(corpo.get("login")) != corpo.get("password"):
            raise HTTPException(401, "credenciais inválidas")
        tok = token_hex(16)
        est.tokens.add(tok)
        return {"token": tok, "expires_in": 3600}

    @app.post("/mock/cpj/expirar-tokens")
    def expirar():
        est.tokens.clear()
        return {"ok": True}

    @app.get(f"{base}/processos")
    def cpj_processos(req: Request):
        _auth(req)
        itens = est.cpj["processos"]
        for k, v in req.query_params.items():
            m = re.fullmatch(r"filter\[(\w+)\]\[_eq\]", k)
            if not m:
                continue
            campo = m.group(1)

            def val(p, c=campo):
                x = p.get(c)
                return str(x.get("value") if isinstance(x, dict) else x)
            itens = [p for p in itens if val(p) == str(v)]
        return _paginar(req, itens)

    @app.get(base + "/processos/{pj}/tramitacoes")
    def cpj_tramitacoes(pj: int, req: Request):
        _auth(req)
        if str(pj) not in est.cpj["tramitacoes"]:
            raise HTTPException(404)
        return _paginar(req, est.cpj["tramitacoes"][str(pj)])

    @app.get(base + "/processos/{pj}/documentos")
    def cpj_documentos(pj: int, req: Request):
        _auth(req)
        if str(pj) not in est.cpj["documentos"]:
            raise HTTPException(404)
        return _paginar(req, est.cpj["documentos"][str(pj)])

    @app.get(base + "/documentos/{id_ged}")
    def cpj_baixar(id_ged: int, req: Request):
        _auth(req)
        rel = est.cpj["arquivos"].get(str(id_ged))
        if not rel or not (est.pasta / rel).exists():
            raise HTTPException(404)
        return FileResponse(est.pasta / rel, media_type="application/pdf")

    # =====================================================================================
    # ProJuris  (interface web)
    # =====================================================================================
    def _logado(req: Request) -> bool:
        return req.cookies.get(COOKIE) in est.sessoes

    def _api(req: Request):
        if not _logado(req):
            raise HTTPException(401, "sessão expirada")

    def _pagina(nome: str) -> HTMLResponse:
        return HTMLResponse((ESTATICOS / nome).read_text(encoding="utf-8"))

    @app.get("/")
    def raiz():
        return RedirectResponse("/projuris/")

    @app.get("/projuris/login")
    def login_form():
        return _pagina("login.html")

    @app.post("/projuris/login")
    async def login(req: Request):
        f = urllib.parse.parse_qs((await req.body()).decode())
        usuario, senha = (f.get("usuario") or [""])[0], (f.get("senha") or [""])[0]
        if est.pj["usuarios"].get(usuario) != senha:
            return RedirectResponse("/projuris/login?erro=1", status_code=303)
        sid = token_hex(16)
        est.sessoes.add(sid)
        r = RedirectResponse("/projuris/", status_code=303)
        r.set_cookie(COOKIE, sid, httponly=True, samesite="lax")
        return r

    @app.get("/projuris/sair")
    def sair(req: Request):
        est.sessoes.discard(req.cookies.get(COOKIE))
        return RedirectResponse("/projuris/login")

    @app.get("/projuris/")
    def inicio(req: Request):
        return _pagina("inicio.html") if _logado(req) else RedirectResponse("/projuris/login")

    @app.get("/projuris/processo/{pid}")
    def pagina_processo(pid: int, req: Request):
        return _pagina("processo.html") if _logado(req) else RedirectResponse("/projuris/login")

    # ---- API usada pelas páginas ----
    def _resumo(p: dict) -> dict:
        atual = next((f for f in p["fases"] if f["atual"]), None)
        return {"id": p["id"], "pasta": p["pasta"], "cnj": p["cnj"], "cliente": p["cliente"],
                "parte_contraria": p["parte_contraria"], "status": p["status"],
                "comarca": (atual or {}).get("comarca", "")}

    @app.get("/projuris/api/processos")
    def lista(req: Request, campo: str = "pasta", valor: str = "", inicio: int = 0, limite: int = 25):
        _api(req)
        regs = [_resumo(p) for p in est.pj["processos"]]
        if valor:
            regs = [r for r in regs if _n(valor) in _n(r.get(campo, ""))]
        return {"total": len(regs), "registros": regs[inicio:inicio + limite]}

    def _rot_fase(f: dict) -> str:
        return f"{f['data']}, {f['numero']}, {f['fase']}"

    @app.get("/projuris/api/processo/{pid}")
    def processo(pid: int, req: Request):
        _api(req)
        return _resumo(est.proc(pid))

    @app.get("/projuris/api/processo/{pid}/fases")
    def fases(pid: int, req: Request):
        _api(req)
        return {"registros": est.proc(pid)["fases"]}

    @app.get("/projuris/api/processo/{pid}/eventos")
    def eventos(pid: int, req: Request):
        _api(req)
        p = est.proc(pid)
        por_id = {f["id"]: f for f in p["fases"]}
        return {"registros": [dict(e, fase=_rot_fase(por_id[e["fase_id"]]) if e["fase_id"] in por_id else "")
                              for e in p["eventos"]]}

    @app.get("/projuris/api/processo/{pid}/documentos")
    def documentos(pid: int, req: Request, evento: int | None = None):
        _api(req)
        p = est.proc(pid)
        nome_ev = {e["id"]: e["evento"] for e in p["eventos"]}
        regs = [dict(d, evento=nome_ev.get(d.get("evento_id"), "")) for d in p["documentos"]]
        if evento is not None:
            regs = [d for d in regs if d.get("evento_id") == evento]
        return {"registros": regs}

    COMBOS = {
        "tipo_recurso": lambda: [{"valor": i + 1, "texto": t} for i, t in enumerate(S.TIPOS_RECURSO)],
        "fase": lambda: [{"valor": i + 1, "texto": t} for i, t in enumerate(S.FASES)],
        "tribunal": lambda: [{"valor": t, "texto": t} for t in sorted(set(S.TRIBUNAL.values()))],
        "jurisdicao": lambda: [{"valor": i + 1, "texto": t} for i, t in enumerate(S.JURISDICOES)],
        "uf": lambda: [{"valor": u, "texto": u} for u in S.UFS],
        "decisao": lambda: S.DECISOES,
        "evento": lambda: S.EVENTOS,
        "tipo_documento": lambda: [{"valor": i + 1, "texto": t} for i, t in enumerate(S.TIPOS_DOCUMENTO)],
    }

    @app.get("/projuris/api/combo/{nome}")
    def combo(nome: str, req: Request, q: str = "", uf: str = "", processo: int | None = None):
        _api(req)
        if nome == "comarca":
            # dependente: SEM a UF escolhida no combo de UF a lista vem vazia
            itens = [{"valor": c, "texto": c} for c in S.COMARCAS.get(uf, [])]
        elif nome == "desdobramento":
            itens = [{"valor": f["id"], "texto": _rot_fase(f)} for f in est.proc(processo)["fases"]] if processo else []
        elif nome in COMBOS:
            itens = COMBOS[nome]()
        else:
            raise HTTPException(404)
        if q:
            itens = [i for i in itens if _n(q) in _n(i["texto"])]
        return itens

    # ---- gravações ----
    def _exigir(corpo: dict, campos: dict[str, str]):
        faltando = [rot for k, rot in campos.items() if not str(corpo.get(k) or "").strip()]
        if faltando:
            raise HTTPException(422, f"Campos obrigatórios: {', '.join(faltando)}")
        for k in ("DATA", "DATA_DECISAO"):
            if k in corpo and not _data_ok(corpo[k]):
                raise HTTPException(422, f"Data inválida: {corpo[k]}")

    def _texto_de(nome: str, valor) -> str:
        for i in COMBOS[nome]():
            if str(i["valor"]) == str(valor):
                return i["texto"]
        raise HTTPException(422, f"Valor inválido para {nome}: {valor}")

    @app.post("/projuris/api/processo/{pid}/fases")
    async def nova_fase(pid: int, req: Request):
        _api(req)
        p, c = est.proc(pid), await req.json()
        _exigir(c, {"DATA": "Data", "TIPO_RECURSO": "Tipo", "ID_FASE": "Fase", "ID_TRIBUNAL": "Tribunal",
                    "ID_JURISDICAO": "Jurisdição", "ID_UF": "UF", "ID_COMARCA": "Comarca"})
        if c["ID_COMARCA"] not in S.COMARCAS.get(c["ID_UF"], []):
            raise HTTPException(422, "Comarca não pertence à UF")
        f = {"id": est.prox("fase"), "data": c["DATA"], "fase": _texto_de("fase", c["ID_FASE"]),
             "tipo_recurso": _texto_de("tipo_recurso", c["TIPO_RECURSO"]), "numero": c.get("NUMERO_ORIGINAL", ""),
             "tribunal": c["ID_TRIBUNAL"], "jurisdicao": _texto_de("jurisdicao", c["ID_JURISDICAO"]),
             "uf": c["ID_UF"], "comarca": c["ID_COMARCA"], "juiz": "", "atual": bool(c.get("ATUAL")),
             "julgado": False, "decisao": "", "predominante": "", "data_decisao": ""}
        if f["atual"]:
            for o in p["fases"]:
                o["atual"] = False
        p["fases"].append(f)
        return {"ok": True, "id": f["id"]}

    @app.post("/projuris/api/processo/{pid}/fases/{fid}/decisao")
    async def decisao(pid: int, fid: int, req: Request):
        _api(req)
        p, c = est.proc(pid), await req.json()
        _exigir(c, {"DATA_DECISAO": "Data da decisão", "ID_DECISAO": "Decisão", "DECISAO_OBJETO": "Decisão predominante"})
        if c["DECISAO_OBJETO"] not in ("F", "D", "P"):
            raise HTTPException(422, "Decisão predominante inválida")
        f = next((x for x in p["fases"] if x["id"] == fid), None)
        if not f:
            raise HTTPException(404, "fase não encontrada")
        f.update(julgado=True, decisao=_texto_de("decisao", c["ID_DECISAO"]), predominante=c["DECISAO_OBJETO"],
                 data_decisao=c["DATA_DECISAO"])
        return {"ok": True}

    @app.post("/projuris/api/processo/{pid}/eventos")
    async def novo_evento(pid: int, req: Request):
        _api(req)
        p, c = est.proc(pid), await req.json()
        _exigir(c, {"DATA": "Data", "ID_EVENTO": "Evento", "ID_PROCESSO_DESDOBRAMENTO": "Fase"})
        if not any(str(f["id"]) == str(c["ID_PROCESSO_DESDOBRAMENTO"]) for f in p["fases"]):
            raise HTTPException(422, "Fase inválida")
        e = {"id": est.prox("ev"), "data": c["DATA"], "evento": _texto_de("evento", c["ID_EVENTO"]),
             "evento_id": int(c["ID_EVENTO"]), "fase_id": int(c["ID_PROCESSO_DESDOBRAMENTO"]),
             "requisicao": est.prox("requisicao")}
        p["eventos"].append(e)
        # como no sistema real: o cadastro do evento gera sozinho uma requisição de conferência
        return {"ok": True, "id": e["id"], "requisicao": e["requisicao"]}

    async def _salvar_doc(pid: int, req: Request, evento_id: int | None):
        _api(req)
        p, c = est.proc(pid), await req.json()
        _exigir(c, {"ARQUIVO_NOME": "Arquivo", "ID_TIPO_DOCUMENTO": "Tipo", "DATA": "Data"})
        if evento_id is not None and not any(e["id"] == evento_id for e in p["eventos"]):
            raise HTTPException(404, "evento não encontrado")
        nome = Path(c["ARQUIVO_NOME"]).name
        conteudo = base64.b64decode(c.get("ARQUIVO_B64") or "")
        if not conteudo.startswith(b"%PDF"):
            raise HTTPException(422, "O arquivo não é um PDF")
        d = {"id": est.prox("doc"), "data": c["DATA"], "nome": nome,
             "tipo": _texto_de("tipo_documento", c["ID_TIPO_DOCUMENTO"]), "evento_id": evento_id,
             "tamanho": len(conteudo)}
        (est.uploads / f"{d['id']}_{nome}").write_bytes(conteudo)
        p["documentos"].append(d)
        return {"ok": True, "id": d["id"]}

    @app.post("/projuris/api/processo/{pid}/eventos/{eid}/documentos")
    async def doc_evento(pid: int, eid: int, req: Request):
        return await _salvar_doc(pid, req, eid)

    @app.post("/projuris/api/processo/{pid}/documentos")
    async def doc_processo(pid: int, req: Request):
        return await _salvar_doc(pid, req, None)

    @app.exception_handler(HTTPException)
    async def erro(req: Request, exc: HTTPException):
        if exc.status_code == 204:
            return Response(status_code=204)
        return JSONResponse({"erro": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    return app


app = criar_app()

if __name__ == "__main__":
    import uvicorn
    print(json.dumps({"cpj": "http://127.0.0.1:8702/cpj/api/v3", "projuris": "http://127.0.0.1:8702/projuris"}))
    uvicorn.run(app, host="127.0.0.1", port=8702)
