"""Classificador do dispositivo — textos 100% fictícios (nenhum trecho de processo real)."""
import pytest

from sentencas import regras as R
from sentencas.decisao import Sugestao, avaliar, normalizar, sugerir

RELATORIO = ("Dispensado o relatório. A parte autora alega cobrança indevida nas faturas de água e pede "
             "o refaturamento e indenização por danos morais. A ré sustenta a regularidade da medição. ") * 4


def s(dispositivo: str, antes: str = "") -> Sugestao:
    return sugerir(RELATORIO + antes + " " + dispositivo + " Publique-se. Registre-se. Intimem-se.")


# ---------- resultados básicos ----------
@pytest.mark.parametrize("texto, esperado", [
    ("Diante do exposto, JULGO PROCEDENTE o pedido para condenar a ré.", R.PROCEDENTE),
    ("Ante o exposto, julgo improcedentes os pedidos.", R.IMPROCEDENTE),
    ("Isso posto, julgo procedente em parte o pedido.", R.PARCIAL),
    ("Ante o exposto, JULGO PARCIALMENTE PROCEDENTES os pedidos formulados.", R.PARCIAL),
    ("Pelo exposto, opino pela PROCEDÊNCIA EM PARTE da ação.", R.PARCIAL),
    ("Ante ao exposto, opino pela PARCIAL PROCEDÊNCIA da ação movida pelo autor.", R.PARCIAL),
    ("Diante do exposto, opino pela IMPROCEDÊNCIA da ação.", R.IMPROCEDENTE),
    ("Diante do exposto, acolho os pedidos formulados pela autora.", R.PROCEDENTE),
    ("Ante o exposto, REJEITO OS PEDIDOS iniciais.", R.IMPROCEDENTE),
    ("Ante o exposto, DENEGO A SEGURANÇA pleiteada.", R.IMPROCEDENTE),
    ("Ante o exposto, CONCEDO A SEGURANÇA para anular o ato.", R.PROCEDENTE),
    ("Ante o exposto, CONCEDO PARCIALMENTE A SEGURANÇA.", R.PARCIAL),
    ("Ex positis, JULGO IMPROCEDENTE a demanda.", R.IMPROCEDENTE),
    ("Isto posto, JULGO PROCEDENTES os pedidos.", R.PROCEDENTE),
    ("Posto isso, julgo procedente a ação.", R.PROCEDENTE),
    ("Em face do exposto, julgo improcedente o pedido.", R.IMPROCEDENTE),
    ("Por todo o exposto, julgo parcialmente procedente o pedido.", R.PARCIAL),
    ("III - DISPOSITIVO. JULGO IMPROCEDENTES os pedidos da inicial.", R.IMPROCEDENTE),
])
def test_resultados(texto, esperado):
    assert s(texto).decisao == esperado


# ---------- termos colados pelo pypdf ----------
@pytest.mark.parametrize("texto, esperado", [
    ("Ante o exposto, JULGO PARCIALMENTEPROCEDENTES os pedidos.", R.PARCIAL),
    ("Ante o exposto, opino pela IMPROCEDÊNCIA dospedidos formulados.", R.IMPROCEDENTE),
    ("Anteo exposto, opino peloacolhimento parcial dos pedidos.", R.PARCIAL),
    ("Diantedo exposto, julgoprocedente o pedido.", R.PROCEDENTE),
    ("Issoposto, julgo procedenteem parte o pedido.", R.PARCIAL),
    ("Expositis, julgo improcedente.", R.IMPROCEDENTE),
])
def test_termos_colados(texto, esperado):
    assert s(texto).decisao == esperado


# ---------- só o dispositivo conta ----------
def test_relatorio_citando_outra_decisao_nao_conta():
    antes = "Na inicial, o autor cita caso em que outro juízo julgou procedentes pedidos semelhantes."
    assert s("Ante o exposto, JULGO IMPROCEDENTE a ação.", antes).decisao == R.IMPROCEDENTE


def test_preliminar_rejeitada_antes_do_dispositivo():
    antes = ("Rejeito a preliminar de ilegitimidade passiva, pois a ré é a concessionária. "
             "Afasto também a alegação de incompetência.")
    assert s("DISPOSITIVO. Ante o exposto, julgo PROCEDENTE o pedido.", antes).decisao == R.PROCEDENTE


def test_preliminar_rejeitada_dentro_do_dispositivo():
    t = ("II – DISPOSITIVO Diante do exposto, opino pela REJEIÇÃO da preliminar de ilegitimidade passiva e, "
         "no mérito, pela IMPROCEDÊNCIA dospedidos formulados pela autora em face da ré.")
    assert s(t).decisao == R.IMPROCEDENTE


def test_usa_o_ultimo_marcador_com_resultado():
    t = ("Ante o exposto na fundamentação, passo ao dispositivo. DISPOSITIVO: Isso posto, JULGO "
         "PARCIALMENTE PROCEDENTE o pedido.")
    assert s(t).decisao == R.PARCIAL


def test_marcador_final_sem_resultado_volta_para_o_anterior():
    t = ("Ante o exposto, JULGO IMPROCEDENTES os pedidos. Do exposto acima, intimem-se as partes.")
    assert s(t).decisao == R.IMPROCEDENTE


# ---------- sem resolução do mérito ----------
@pytest.mark.parametrize("texto", [
    "Ante o exposto, JULGO EXTINTO o processo, sem resolução do mérito, art. 485, VI, do CPC.",
    "Diante do exposto, extingo o feito sem julgamento de mérito.",
    "Ante o exposto, EXTINGO O PROCESSO, SEM RESOLUÇÃO DO MÉRITO, pela desistência.",
    "Isso posto, extingo o processo, sem exame do mérito.",
])
def test_sem_merito(texto):
    assert s(texto).decisao == R.SEM_MERITO


# ---------- pedido contraposto / reconvenção não definem o resultado ----------
def test_contraposto_improcedente_ignorado():
    t = ("Ante o exposto, opino pela PROCEDÊNCIA da ação para declarar inexigível o débito. "
         "Outrossim, OPINO PELA IMPROCEDÊNCIA do pedido contraposto formulado pela requerida.")
    assert s(t).decisao == R.PROCEDENTE


def test_parcial_bem_como_improcedencia_do_contraposto():
    t = ("Ante o exposto, opino pela PARCIAL PROCEDÊNCIA da pretensão deduzida pela autora, "
         "bem como pela IMPROCEDÊNCIA DO PEDIDO CONTRAPOSTO deduzido pela demandada.")
    assert s(t).decisao == R.PARCIAL


def test_improcedente_com_contraposto_parcial():
    t = ("Ante o exposto, a) julgo IMPROCEDENTES os pedidos da autora; b) julgo PARCIALMENTE "
         "PROCEDENTE o pedido contraposto formulado pela ré.")
    assert s(t).decisao == R.IMPROCEDENTE


def test_reconvencao_parcial_mascarada():
    t = ("Ex positis, JULGO IMPROCEDENTES os pedidos da ação principal e JULGO PARCIALMENTE PROCEDENTE "
         "a reconvenção para condenar o autor-reconvindo ao pagamento das faturas.")
    assert s(t).decisao == R.IMPROCEDENTE


def test_reconvencao_improcedente_mascarada():
    t = "Ante o exposto, julgo PROCEDENTE a ação e IMPROCEDENTE a reconvenção."
    assert s(t).decisao == R.PROCEDENTE


# ---------- nunca chuta ----------
def test_conflito_vira_excecao():
    sug = s("Ante o exposto, julgo procedente o pedido A e improcedente o pedido B.")
    assert sug.decisao == "" and "procedente E improcedente" in sug.motivo


def test_sem_dispositivo():
    sug = s("Intimem-se as partes para manifestação sobre o laudo.")
    assert sug.decisao == "" and "dispositivo" in sug.motivo


@pytest.mark.parametrize("texto", ["", "   ", "SENTENÇA. Ante o exposto, julgo procedente."])
def test_texto_curto_ou_vazio_eh_pdf_escaneado(texto):
    sug = sugerir(texto)
    assert sug.decisao == "" and "escaneada" in sug.motivo


def test_trecho_mostra_o_dispositivo_no_texto_original():
    sug = s("Ante o exposto, JULGO IMPROCEDENTES os pedidos formulados na inicial.")
    assert "JULGO IMPROCEDENTES" in sug.trecho          # com acentos/maiúsculas originais
    assert sug.trecho.startswith("…")


def test_normalizar_mantem_tamanho():
    t = "Ação JULGADA PROCEDÊNCIA ºª"
    assert len(normalizar(t)) == len(t)
    assert normalizar(t).startswith("acao julgada procedencia")


# ---------- avaliar(): cruza a leitura com o DEC ----------
def test_avaliar_dec1_aceita_improcedente_ou_procedente():
    regra = R.REGRAS["DEC1"]
    assert avaliar(regra, s("Ante o exposto, julgo improcedentes os pedidos.")) == (R.IMPROCEDENTE, "")
    assert avaliar(regra, s("Ante o exposto, julgo procedente o pedido.")) == (R.PROCEDENTE, "")


def test_avaliar_dec1_recusa_parcial():
    dec, motivo = avaliar(R.REGRAS["DEC1"], s("Ante o exposto, julgo parcialmente procedente o pedido."))
    assert dec == "" and "não combina com DEC1" in motivo


def test_avaliar_dec3_precisa_de_parcial():
    regra = R.REGRAS["DEC3"]
    dec, motivo = avaliar(regra, s("Ante o exposto, julgo improcedentes os pedidos."))
    assert dec == "" and "não combina" in motivo
    assert avaliar(regra, s("Ante o exposto, julgo parcialmente procedentes os pedidos.")) == (R.PARCIAL, "")


def test_avaliar_dec13_decisao_fixa():
    regra = R.REGRAS["DEC13"]
    assert avaliar(regra, s("Ante o exposto, extingo o processo, sem resolução do mérito.")) == (R.SEM_MERITO, "")
    dec, motivo = avaliar(regra, s("Ante o exposto, julgo procedente o pedido."))
    assert dec == "" and "DEC13" in motivo


def test_avaliar_sem_sugestao_repassa_o_motivo():
    dec, motivo = avaliar(R.REGRAS["DEC2"], Sugestao("", "", "não consegui ler o texto do PDF (imagem escaneada?)"))
    assert dec == "" and "escaneada" in motivo


def test_regras_coerentes():
    assert R.PARCIAL == "Procedente em parte"            # e não a duplicidade "Procedente em Parte"
    assert {r.predominante for r in R.REGRAS.values()} <= set(R.NOME_PREDOMINANTE)
    assert len({r.evento_id for r in R.REGRAS.values()}) == len(R.REGRAS)
