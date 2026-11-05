"""Cliente do CPJ contra a API do mock (TestClient, sem rede) + planejador ponta a ponta."""
import pytest
from fastapi.testclient import TestClient

from mock.app import criar_app
from sentencas import regras as R
from sentencas.cpj import CPJ, CPJIndisponivel, decs_do_processo, decs_pendentes, processo_por_cnj, processos_ativos
from sentencas.projuris import Evento, Fase, Processo
from sentencas.simulacao import planejar

ENV = {"CPJ_BASE_URL": "http://testserver/cpj", "CPJ_LOGIN": "robo.demo", "CPJ_SENHA": "senha-demo"}


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    return criar_app(tmp_path_factory.mktemp("dados"))


@pytest.fixture
def estado(app):
    app.state.estado.reset()
    return app.state.estado


@pytest.fixture
def cpj(app, estado):
    esperas = []
    c = CPJ(ENV, sessao=TestClient(app), dormir=esperas.append, por_pagina=4)   # páginas pequenas
    c.esperas = esperas
    return c


def test_login_errado(app, estado):
    with pytest.raises(CPJIndisponivel, match="recusou o login"):
        CPJ(dict(ENV, CPJ_SENHA="errada"), sessao=TestClient(app), dormir=lambda s: None)


def test_login_tenta_de_novo_em_5xx(app, estado):
    estado.falhas_cpj[:] = [503, 502]
    c = CPJ(ENV, sessao=TestClient(app), dormir=lambda s: None)
    assert c.s.headers["Authorization"].startswith("Bearer ")


def test_paginacao_e_filtro_do_grupo(cpj, estado):
    procs = processos_ativos(cpj)
    esperado = [p for p in estado.cpj["processos"] if p["grupo_trabalho"]["value"] == R.GRUPO_TRABALHO]
    assert len(procs) == len(esperado) > 4                 # veio em várias páginas
    assert all(p["grupo_trabalho"]["value"] == R.GRUPO_TRABALHO for p in procs)


def test_retry_em_429_e_503(cpj, estado):
    estado.falhas_cpj[:] = [429, 503]
    assert processos_ativos(cpj)
    assert len(cpj.esperas) >= 2


def test_token_vencido_reloga(cpj, estado):
    estado.tokens.clear()
    assert processos_ativos(cpj)


def test_erro_persistente_nunca_vira_nao_encontrado(cpj, estado):
    estado.falhas_cpj[:] = [500] * 20
    with pytest.raises(CPJIndisponivel):
        processo_por_cnj(cpj, estado.dados["gabarito"]["parcial"]["cnj"])


def test_processo_por_cnj_e_dec_filho_do_sne(cpj, estado):
    g = estado.dados["gabarito"]["parcial"]
    proc = processo_por_cnj(cpj, g["cnj"])
    decs = decs_do_processo(cpj, proc, set(R.REGRAS), None)
    assert len(decs) == 1
    d = decs[0]
    assert d.dec == "DEC3" and d.pasta == g["pasta"] and d.pdf and d.pdf["path"].endswith(".pdf")
    assert d.jornal.startswith("Diário da Justiça Eletrônico")
    assert d.data_publicacao != d.lancado_em               # data do SNE, não do DEC


def test_processo_de_outro_grupo_nao_entra(cpj, estado):
    outro = next(p for p in estado.cpj["processos"] if p["grupo_trabalho"]["value"] != R.GRUPO_TRABALHO)
    assert processo_por_cnj(cpj, outro["numero_processo"]) is None
    assert decs_do_processo(cpj, outro, set(R.REGRAS), None) == []   # conferência registro a registro


def test_varredura_acha_so_os_pendentes_da_janela(cpj, estado):
    decs = decs_pendentes(cpj, set(R.REGRAS), dias=30, paralelo=3)
    cnjs = {d.cnj for d in decs}
    assert cnjs == {g["cnj"] for g in estado.dados["gabarito"].values()}


def test_baixar_pdf(cpj, estado, tmp_path):
    g = estado.dados["gabarito"]["improcedente_favoravel"]
    d = decs_do_processo(cpj, processo_por_cnj(cpj, g["cnj"]), set(R.REGRAS), None)[0]
    arq = cpj.baixar(d.pdf["id_ged"], tmp_path / "s.pdf")
    assert arq.read_bytes().startswith(b"%PDF")


# ---------- ponta a ponta: CPJ do mock + ProJuris "lido" direto do banco do mock ----------
class ProJurisDoMock:
    """Mesma interface do adaptador real, mas lendo o estado do mock sem navegador."""

    def __init__(self, estado):
        self.p = estado.pj["processos"]

    def buscar_pasta(self, pasta):
        return [{"id": x["id"], "pasta": x["pasta"], "cnj": x["cnj"]} for x in self.p if x["pasta"] == pasta]

    def ler_processo(self, id_):
        x = next(p for p in self.p if p["id"] == id_)
        rot = {f["id"]: f"{f['data']}, {f['numero']}, {f['fase']}" for f in x["fases"]}
        return Processo(
            id=x["id"], pasta=x["pasta"], cnj=x["cnj"],
            fases=[Fase(id=f["id"], data=f["data"], fase=f["fase"], numero=f["numero"], tribunal=f["tribunal"],
                        jurisdicao=f["jurisdicao"], uf=f["uf"], comarca=f["comarca"], juiz=f["juiz"],
                        atual=f["atual"], julgado=f["julgado"]) for f in x["fases"]],
            eventos=[Evento(id=e["id"], evento=e["evento"], data=e["data"], fase=rot.get(e["fase_id"], ""))
                     for e in x["eventos"]])


def test_planejador_bate_com_o_gabarito_do_seed(cpj, estado, tmp_path):
    decs = decs_pendentes(cpj, set(R.REGRAS), dias=30)
    pj = ProJurisDoMock(estado)
    gab = {g["cnj"]: (k, g["esperado"]) for k, g in estado.dados["gabarito"].items()}
    for d in decs:
        it = planejar(d, cpj, pj, tmp_path)
        chave, esperado = gab[d.cnj]
        assert it.situacao == esperado, f"{chave}: {it.situacao} — {it.motivo}"
