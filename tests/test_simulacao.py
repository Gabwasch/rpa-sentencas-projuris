"""Planejador (simulacao.planejar) com CPJ e ProJuris falsos — sem rede, sem navegador."""
from pathlib import Path

import pytest

from sentencas import regras as R
from sentencas.cpj import Dec
from sentencas.projuris import Evento, Fase, Processo, ProJurisErro, SemSessao
from sentencas.simulacao import EXCECAO, JA_LANCADO, PRONTO, planejar, resumo, salvar_xlsx

CNJ = "1234567-89.2026.8.24.0001"      # formato apenas; não precisa ser válido aqui
PUB = "10/10/2026"
TEXTO_IMPROC = "Relatório genérico de uma ação de consumo. " * 10 + " Ante o exposto, JULGO IMPROCEDENTES os pedidos."


class FakeCPJ:
    def baixar(self, id_ged, destino: Path):
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"%PDF-1.4 falso")
        return destino


def fase(**kw) -> Fase:
    base = dict(id=1, data="01/03/2026", fase="Conhecimento", numero=CNJ, tribunal="TJSC",
                jurisdicao="Juizado Especial Cível", uf="SC", comarca="Porto Sereno", juiz="", atual=True,
                julgado=False)
    base.update(kw)
    return Fase(**base)


class FakeProJuris:
    def __init__(self, processo: Processo | None = None, achados=None, erro: Exception | None = None):
        self.processo = processo
        self.achados = achados if achados is not None else (
            [{"id": processo.id, "pasta": processo.pasta, "cnj": processo.cnj}] if processo else [])
        self.erro = erro

    def buscar_pasta(self, pasta):
        if self.erro:
            raise self.erro
        return self.achados

    def ler_processo(self, id_):
        return self.processo


def dec(**kw) -> Dec:
    base = dict(pj=10, cnj=CNJ, pasta="123456", dec="DEC1", descricao="Sentença Cível Favorável",
                id_tramitacao=99, lancado_em="11/10/2026", data_publicacao=PUB,
                pdf={"id_ged": 5, "path": "G:\\x\\sentenca.pdf"})
    base.update(kw)
    return Dec(**base)


def proc(fases=None, eventos=None, pasta="123456", cnj=CNJ) -> Processo:
    return Processo(id=777, pasta=pasta, cnj=cnj, fases=fases if fases is not None else [fase()],
                    eventos=eventos or [])


def plan(d=None, pj=None, texto=TEXTO_IMPROC, tmp=Path(".")):
    return planejar(d or dec(), FakeCPJ(), pj, tmp, ler_texto=lambda _: texto)


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_pronto():
    it = plan(pj=FakeProJuris(proc()))
    assert it.situacao == PRONTO and it.decisao == R.IMPROCEDENTE
    assert it.predominante == "Favorável" and it.evento == R.REGRAS["DEC1"].evento
    assert "Sentença" in it.fase and "Porto Sereno-SC" in it.fase and it.id_projuris == 777


def test_sem_projuris_fica_pronto_com_aviso():
    it = plan(pj=None)
    assert it.situacao == PRONTO and "--sem-projuris" in it.motivo


def test_dec_fora_da_v1():
    it = plan(d=dec(dec="DEC7"))
    assert it.situacao == EXCECAO and "fora da V1" in it.motivo


def test_sem_pdf():
    it = plan(d=dec(pdf=None, outros_docs=["sentenca.docx"]))
    assert it.situacao == EXCECAO and "sem" not in it.decisao and "sentenca.docx" in it.motivo


def test_pdf_ilegivel():
    it = plan(texto="")
    assert it.situacao == EXCECAO and "escaneada" in it.motivo


def test_erro_ao_ler_pdf_vira_excecao():
    def explode(_):
        raise ValueError("pdf quebrado")
    it = planejar(dec(), FakeCPJ(), None, Path("."), ler_texto=explode)
    assert it.situacao == EXCECAO and "ValueError" in it.motivo


def test_dec_contradiz_texto():
    it = plan(d=dec(dec="DEC3"))
    assert it.situacao == EXCECAO and "não combina com DEC3" in it.motivo


def test_pasta_nao_encontrada():
    it = plan(pj=FakeProJuris(achados=[]))
    assert it.situacao == EXCECAO and "não encontrada" in it.motivo


def test_pasta_com_dois_processos():
    it = plan(pj=FakeProJuris(achados=[{"id": 1, "cnj": CNJ}, {"id": 2, "cnj": CNJ}]))
    assert it.situacao == EXCECAO and "mais de um" in it.motivo


def test_pasta_de_outro_cnj():
    it = plan(pj=FakeProJuris(achados=[{"id": 1, "cnj": "7654321-00.2024.8.24.0001"}]))
    assert it.situacao == EXCECAO and "é do processo" in it.motivo


def test_processo_aberto_de_outra_pasta():
    it = plan(pj=FakeProJuris(proc(pasta="999999"), achados=[{"id": 777, "cnj": CNJ}]))
    assert it.situacao == EXCECAO and "pasta 999999" in it.motivo


def test_ja_lancado_dentro_de_30_dias():
    ev = Evento(id=1, evento="Sentença Favorável ao Cliente", data="12/10/2026", fase="x")
    it = plan(pj=FakeProJuris(proc(eventos=[ev])))
    assert it.situacao == JA_LANCADO


def test_evento_antigo_nao_conta_como_ja_lancado():
    ev = Evento(id=1, evento="Sentença Favorável ao Cliente", data="01/01/2025", fase="x")
    assert plan(pj=FakeProJuris(proc(eventos=[ev]))).situacao == PRONTO


def test_evento_de_outro_tipo_nao_conta():
    ev = Evento(id=1, evento="Sentença Desfavorável ao Cliente", data="12/10/2026", fase="x")
    assert plan(pj=FakeProJuris(proc(eventos=[ev]))).situacao == PRONTO


def test_lancamento_incompleto():
    fs = [fase(atual=False), fase(id=2, fase="Sentença", data=PUB, atual=True)]
    it = plan(pj=FakeProJuris(proc(fases=fs)))
    assert it.situacao == EXCECAO and "incompleto" in it.motivo


@pytest.mark.parametrize("fases", [[fase(atual=False)], [fase(), fase(id=2)]])
def test_sem_uma_fase_atual(fases):
    it = plan(pj=FakeProJuris(proc(fases=fases)))
    assert it.situacao == EXCECAO and "UMA fase" in it.motivo


def test_fase_atual_sem_comarca():
    it = plan(pj=FakeProJuris(proc(fases=[fase(comarca="")])))
    assert it.situacao == EXCECAO and "comarca" in it.motivo


def test_erro_de_tela_vira_excecao_mas_sem_sessao_para_tudo():
    assert plan(pj=FakeProJuris(erro=ProJurisErro("aba não carregou"))).motivo == "aba não carregou"
    with pytest.raises(SemSessao):
        plan(pj=FakeProJuris(erro=SemSessao("login")))


def test_dec13_sem_merito():
    texto = "Relatório. " * 30 + " Ante o exposto, JULGO EXTINTO o processo, sem resolução do mérito."
    it = plan(d=dec(dec="DEC13"), pj=FakeProJuris(proc()), texto=texto)
    assert it.situacao == PRONTO and it.decisao == R.SEM_MERITO and it.predominante == "Favorável"


def test_planilha(tmp_path):
    itens = [plan(pj=FakeProJuris(proc())), plan(d=dec(pdf=None))]
    arq = salvar_xlsx(itens, tmp_path / "plano.xlsx")
    from openpyxl import load_workbook
    wb = load_workbook(arq)
    ws = wb["Simulação"]
    assert ws.max_row == 3 and ws["A2"].value == PRONTO and ws["A3"].value == EXCECAO
    assert ws["A2"].fill.fgColor.rgb.endswith("E2EFDA")
    assert resumo(itens) == {PRONTO: 1, JA_LANCADO: 0, EXCECAO: 1}
    assert wb["Resumo"]["B5"].value == 2
