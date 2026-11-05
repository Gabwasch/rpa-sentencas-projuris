"""O próprio mock: gerador de PDF, seed e regras da interface do ProJuris."""
import random

import pytest
from fastapi.testclient import TestClient

from mock import seed
from mock.app import criar_app
from mock.pdfgen import gerar_pdf
from sentencas import cnj as C
from sentencas.decisao import texto_pdf


def test_pdf_com_acentos_extraidos_certos(tmp_path):
    arq = gerar_pdf(tmp_path / "a.pdf", "# SENTENÇA\nAção de cobrança — réu: Companhia. ÉÇÃõü º § (art. 487)")
    t = texto_pdf(arq)
    for trecho in ("SENTENÇA", "Ação de cobrança", "réu", "ÉÇÃõü", "(art. 487)"):
        assert trecho in t


def test_pdf_longo_quebra_em_paginas(tmp_path):
    from pypdf import PdfReader
    arq = gerar_pdf(tmp_path / "b.pdf", "\n".join(f"Linha {i} da sentença fictícia." for i in range(150)))
    assert len(PdfReader(str(arq)).pages) >= 3


def test_pdf_escaneado_nao_tem_texto(tmp_path):
    assert texto_pdf(gerar_pdf(tmp_path / "c.pdf", escaneado=True)) == ""


def test_seed_deterministico_e_cnjs_validos(tmp_path):
    a = seed.gerar(tmp_path / "1")["gabarito"]
    b = seed.gerar(tmp_path / "2")["gabarito"]
    assert a == b
    assert all(C.valido(g["cnj"]) for g in a.values())
    assert {g["esperado"] for g in a.values()} == {"pronto", "já lançado", "exceção"}


def test_config_libera_um_processo_do_seed(tmp_path):
    import tomllib
    from pathlib import Path
    cfg = tomllib.loads((Path(__file__).parents[1] / "robo" / "config.toml").read_text(encoding="utf-8"))
    gab = seed.gerar(tmp_path)["gabarito"]
    assert set(cfg["gravacao"]["liberados"]) <= {g["cnj"] for g in gab.values() if g["esperado"] == "pronto"}


@pytest.fixture(scope="module")
def cli(tmp_path_factory):
    app = criar_app(tmp_path_factory.mktemp("dados_pj"))
    c = TestClient(app)
    c.post("/projuris/login", data={"usuario": "operador", "senha": "demo123"})
    return c


def test_sem_login_redireciona_e_api_recusa(tmp_path):
    c = TestClient(criar_app(tmp_path))
    assert c.get("/projuris/", follow_redirects=False).headers["location"] == "/projuris/login"
    assert c.get("/projuris/api/processos").status_code == 401


def test_comarca_depende_da_uf(cli):
    assert cli.get("/projuris/api/combo/comarca").json() == []
    assert [i["texto"] for i in cli.get("/projuris/api/combo/comarca?uf=SC").json()] == seed.COMARCAS["SC"]


def test_decisao_tem_opcoes_parecidas(cli):
    textos = [i["texto"] for i in cli.get("/projuris/api/combo/decisao?q=procedente em parte").json()]
    assert textos == ["Procedente em parte", "Procedente em Parte"]


def test_campos_obrigatorios_no_servidor(cli):
    pid = cli.get("/projuris/api/processos").json()["registros"][0]["id"]
    r = cli.post(f"/projuris/api/processo/{pid}/fases", json={"DATA": "01/01/2026"})
    assert r.status_code == 422 and "obrigatórios" in r.json()["erro"]


def test_evento_devolve_requisicao(cli):
    pid = cli.get("/projuris/api/processos").json()["registros"][0]["id"]
    fid = cli.get(f"/projuris/api/processo/{pid}/fases").json()["registros"][0]["id"]
    r = cli.post(f"/projuris/api/processo/{pid}/eventos",
                 json={"DATA": "01/01/2026", "ID_EVENTO": 4101, "ID_PROCESSO_DESDOBRAMENTO": fid}).json()
    assert r["ok"] and r["requisicao"] > 0


def test_numeros_do_seed_nao_mudam_com_a_data(tmp_path):
    from datetime import date
    a = seed.gerar(tmp_path / "x", hoje=date(2030, 1, 1))["gabarito"]["parcial"]["cnj"]
    assert a == seed.gerar(tmp_path / "y")["gabarito"]["parcial"]["cnj"]
    assert random.Random(42).random() == random.Random(42).random()
