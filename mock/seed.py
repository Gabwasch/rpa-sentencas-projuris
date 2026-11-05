"""
Dados 100% FICTÍCIOS do mock (CPJ + ProJuris) e as sentenças em PDF.

Cada `Cenario` é um processo pensado para exercitar um caminho do robô (pronto, já lançado e
cada tipo de exceção). Os números de CNJ são inventados, mas têm dígito verificador correto
(ISO 7064 mod 97-10, como manda a Resolução 65/2008 do CNJ).

Determinístico: `random.Random(42)`. As DATAS são relativas a "hoje" (para a janela de 30 dias
do robô sempre funcionar); números, nomes e textos não mudam de um dia para o outro.

    python -m mock.seed            # gera mock/dados/dados.json + mock/dados/pdfs/*.pdf
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .pdfgen import gerar_pdf

PASTA_DADOS = Path(__file__).parent / "dados"

GRUPO = {"value": 31, "label": "Cível - Saneamento Consumidor"}     # o grupo do robô
OUTRO_GRUPO = {"value": 58, "label": "Cível - Varejo"}              # nunca pode entrar

# combos do ProJuris de mentira -----------------------------------------------------------
UFS = ["MG", "PR", "SC"]
COMARCAS = {
    "MG": ["Lagoa Mansa", "Pedra Clara", "Vale do Ipê"],
    "PR": ["Campo Esperança", "Serra Alta", "Rio Manso"],
    "SC": ["Porto Sereno", "Vale Dourado", "Praia Mansa"],
}
TRIBUNAL = {"MG": "TJMG", "PR": "TJPR", "SC": "TJSC"}
COD_TR = {"MG": "13", "PR": "16", "SC": "24"}
JURISDICOES = ["Juizado Especial Cível", "Vara Cível", "Vara da Fazenda Pública"]
FASES = ["Inicial", "Conhecimento", "Sentença", "Recurso Inominado", "Apelação", "Cumprimento de Sentença"]
TIPOS_RECURSO = ["Processo Origem", "Recurso", "Incidente"]
TIPOS_DOCUMENTO = ["Sentença", "Petição", "Acórdão", "Procuração", "Outros"]
# Cadastro "sujo" de propósito: existem duas opções quase iguais. O robô escolhe pelo texto
# EXATO ("Procedente em parte"); a outra é uma duplicidade antiga do cadastro.
DECISOES = [
    {"valor": 11, "texto": "Procedente"},
    {"valor": 12, "texto": "Improcedente"},
    {"valor": 13, "texto": "Procedente em parte"},
    {"valor": 14, "texto": "Procedente em Parte"},
    {"valor": 15, "texto": "Decisão Sem julgamento de Mérito"},
    {"valor": 16, "texto": "Acordo homologado"},
    {"valor": 17, "texto": "Extinção por desistência"},
]
# Tipos de evento. Também há "parecidos" (inativo, recurso): o robô escolhe pelo ID.
EVENTOS = [
    {"valor": 4101, "texto": "Sentença Favorável ao Cliente"},
    {"valor": 4102, "texto": "Sentença Desfavorável ao Cliente"},
    {"valor": 4103, "texto": "Sentença Parcialmente Favorável ao Cliente"},
    {"valor": 4113, "texto": "Sentença Sem Resolução de Mérito"},
    {"valor": 4190, "texto": "Sentença Favorável ao Cliente (inativo)"},
    {"valor": 4201, "texto": "Audiência de Conciliação"},
    {"valor": 4202, "texto": "Recurso Inominado Interposto"},
]

DESCR_DEC = {
    "DEC1": "Sentença Cível Favorável",
    "DEC2": "Sentença Cível Desfavorável",
    "DEC3": "Sentença Cível Parcialmente Favorável",
    "DEC13": "Sentença Sem Resolução do Mérito",
}

NOMES = ["Helena", "Rafael", "Patrícia", "Joaquim", "Luísa", "Otávio", "Renata", "Caio", "Sabrina",
         "Vicente", "Tereza", "Henrique", "Marina", "Gustavo", "Yara", "Leonardo", "Cecília", "Fábio"]
SOBRENOMES = ["Fontes", "Siqueira", "Prado", "Moura", "Teixeira", "Barros", "Quintana", "Rocha",
              "Vasconcelos", "Peixoto", "Albuquerque", "Nogueira", "Coutinho", "Paiva", "Freitas"]
JUIZES = ["Dra. Beatriz Lemos", "Dr. Augusto Ramalho", "Dra. Clara Bittencourt", "Dr. Sérgio Valadares"]
REU = "Companhia Estadual de Saneamento (fictícia)"


@dataclass(frozen=True)
class Cenario:
    chave: str
    dec: str
    dispositivo: str                 # parágrafo do DISPOSITIVO da sentença
    esperado: str                    # pronto | já lançado | exceção (documentação + testes)
    descricao: str
    pdf: str = "texto"               # texto | escaneado | sem_pdf
    projuris: str = "normal"         # normal | outro_cnj | sem_pasta | ja_lancado | incompleto
                                     # | sem_fase_atual | sem_comarca
    relatorio_extra: str = ""


CENARIOS: list[Cenario] = [
    Cenario("improcedente_favoravel", "DEC1",
            "Ante o exposto, com fundamento no art. 487, I, do CPC, JULGO IMPROCEDENTES os pedidos "
            "formulados na inicial. Sem custas e honorários nesta instância (art. 55 da Lei 9.099/95).",
            "pronto", "Favorável ao cliente = IMPROCEDENTE (o pedido do autor foi negado).",
            relatorio_extra="Na petição inicial, o autor cita precedente em que outro juízo julgou procedente "
                            "pedido semelhante. Em contestação, a ré arguiu ilegitimidade passiva, preliminar "
                            "que rejeito, pois a ré é a concessionária responsável pelo fornecimento."),
    Cenario("procedente_desfavoravel", "DEC2",
            "Diante do exposto, JULGO PROCEDENTE o pedido para declarar inexigível o débito discutido e "
            "condenar a ré ao pagamento de R$ 3.000,00 a título de danos morais, com correção monetária "
            "desde esta data e juros desde a citação.",
            "pronto", "Desfavorável ao cliente = PROCEDENTE (o pedido do autor foi aceito)."),
    Cenario("parcial", "DEC3",
            "Isso posto, JULGO PARCIALMENTE PROCEDENTES os pedidos para determinar a revisão das faturas "
            "dos meses de março a maio, afastando o pedido de indenização por danos morais.",
            "pronto", "Parcialmente favorável = 'Procedente em parte' (opção exata do cadastro)."),
    Cenario("sem_merito", "DEC13",
            "Ante o exposto, JULGO EXTINTO o processo, sem resolução do mérito, com fundamento no art. 485, "
            "VI, do CPC, diante da ilegitimidade ativa reconhecida.",
            "pronto", "Sem mérito: decisão fixa 'Decisão Sem julgamento de Mérito' + Favorável."),
    Cenario("reconvencao", "DEC1",
            "Ex positis, JULGO IMPROCEDENTES os pedidos da ação principal e JULGO PARCIALMENTE PROCEDENTE "
            "a reconvenção para condenar o autor-reconvindo ao pagamento das faturas em aberto.",
            "pronto", "A reconvenção parcialmente procedente é mascarada: vale o resultado da ação."),
    Cenario("ambiguo", "DEC1",
            "Ante o exposto, JULGO PROCEDENTE o pedido de refaturamento e IMPROCEDENTE o pedido de "
            "indenização por danos morais.",
            "exceção", "O texto diz procedente E improcedente sem 'parcialmente': o robô não chuta."),
    Cenario("dec_contradiz", "DEC3",
            "Pelo exposto, JULGO IMPROCEDENTES os pedidos iniciais, revogando a tutela de urgência.",
            "exceção", "A equipe marcou DEC3 (parcial), mas o texto é improcedente: conferir."),
    Cenario("escaneado", "DEC2", "", "exceção", "PDF escaneado, sem texto extraível.", pdf="escaneado"),
    Cenario("outro_cnj", "DEC1",
            "Ante o exposto, JULGO IMPROCEDENTE o pedido inicial.",
            "exceção", "A pasta, no ProJuris, pertence a outro CNJ.", projuris="outro_cnj"),
    Cenario("pasta_inexistente", "DEC2",
            "Diante do exposto, JULGO PROCEDENTE o pedido.",
            "exceção", "A pasta do CPJ não existe no ProJuris.", projuris="sem_pasta"),
    Cenario("ja_lancado", "DEC1",
            "Ante o exposto, JULGO IMPROCEDENTES os pedidos.",
            "já lançado", "O mesmo evento já existe no ProJuris (dentro de 30 dias).", projuris="ja_lancado"),
    Cenario("incompleto", "DEC2",
            "Diante do exposto, JULGO PROCEDENTE o pedido para condenar a ré.",
            "exceção", "Lançamento anterior incompleto: fase Sentença sem o evento.", projuris="incompleto"),
    Cenario("sem_fase_atual", "DEC1",
            "Ante o exposto, JULGO IMPROCEDENTES os pedidos.",
            "exceção", "Nenhuma fase marcada como atual no ProJuris.", projuris="sem_fase_atual"),
    Cenario("sem_pdf", "DEC3", "", "exceção", "O DEC não tem PDF anexado (só um .docx).", pdf="sem_pdf"),
    Cenario("sem_comarca", "DEC2",
            "Diante do exposto, JULGO PROCEDENTE o pedido.",
            "exceção", "A fase atual está sem comarca para copiar.", projuris="sem_comarca"),
]


# ---- CNJ ---------------------------------------------------------------------------------
def digito_cnj(seq: str, ano: str, j: str, tr: str, origem: str) -> str:
    """Dígito verificador do CNJ (ISO 7064 mod 97-10)."""
    return f"{98 - int(seq + ano + j + tr + origem + '00') % 97:02d}"


def gerar_cnj(rng: random.Random, uf: str, ano: int) -> str:
    seq = f"{rng.randint(1_000_000, 4_999_999):07d}"
    origem = f"{rng.randint(1, 899):04d}"
    a, j, tr = str(ano), "8", COD_TR[uf]
    return f"{seq}-{digito_cnj(seq, a, j, tr, origem)}.{a}.{j}.{tr}.{origem}"


def _fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _iso(d: date, hora: str = "10:30:00") -> str:
    return f"{d.isoformat()}T{hora}.000-03:00"


def _nome(rng: random.Random) -> str:
    return f"{rng.choice(NOMES)} {rng.choice(SOBRENOMES)} {rng.choice(SOBRENOMES)}"


def texto_sentenca(cnj: str, comarca: str, uf: str, autor: str, juiz: str, dispositivo: str,
                   relatorio_extra: str = "") -> str:
    return "\n".join([
        "# PODER JUDICIÁRIO",
        f"# {TRIBUNAL[uf]} - Comarca de {comarca}/{uf} - Juizado Especial Cível",
        "",
        f"Processo nº {cnj}",
        f"Autor: {autor}",
        f"Ré: {REU}",
        "",
        "# SENTENÇA",
        "",
        "# I - RELATÓRIO",
        "Dispensado o relatório, nos termos do art. 38 da Lei 9.099/95. Em síntese, a parte autora "
        "alega cobrança indevida nas faturas de água e esgoto de sua unidade consumidora e pede o "
        "refaturamento das contas, a devolução dos valores pagos e indenização por danos morais. "
        "A ré sustenta a regularidade da medição e a legalidade das cobranças.",
        relatorio_extra,
        "",
        "# II - FUNDAMENTAÇÃO",
        "A relação entre as partes é de consumo, aplicando-se o Código de Defesa do Consumidor. "
        "Cabia à concessionária demonstrar a regularidade do consumo faturado, ônus do qual se "
        "desincumbe ou não conforme a prova dos autos, especialmente o histórico de consumo e o "
        "laudo de aferição do hidrômetro, que analiso a seguir. Ouvidas as partes em audiência, "
        "não houve acordo. Passo ao julgamento.",
        "",
        "# III - DISPOSITIVO",
        dispositivo,
        "",
        "Publique-se. Registre-se. Intimem-se.",
        "",
        f"{comarca}, data da assinatura eletrônica.",
        f"{juiz} - Juíza/Juiz de Direito (documento fictício)",
    ])


# ---- geração -----------------------------------------------------------------------------
def gerar(pasta: Path = PASTA_DADOS, hoje: date | None = None) -> dict:
    """Gera dados.json + PDFs em `pasta` e devolve o dicionário."""
    hoje = hoje or date.today()
    rng = random.Random(42)
    pasta = Path(pasta)
    (pasta / "pdfs").mkdir(parents=True, exist_ok=True)

    cpj_proc, tram, docs, arquivos = [], {}, {}, {}
    pj_proc: list[dict] = []
    gabarito = {}
    seq = {"pj": 30_000, "tram": 900_000, "ged": 70_000, "pjid": 81_000, "fase": 1, "ev": 1, "doc": 1}

    def novo(k: str) -> int:
        seq[k] += rng.randint(1, 9) if k in ("pj", "tram", "ged", "pjid") else 1
        return seq[k]

    def fase_inicial(uf: str, comarca: str, cnj: str, d: date, atual: bool = True) -> dict:
        return {"id": novo("fase"), "data": _fmt(d), "fase": "Conhecimento", "tipo_recurso": "Processo Origem",
                "numero": cnj, "tribunal": TRIBUNAL[uf], "jurisdicao": "Juizado Especial Cível", "uf": uf,
                "comarca": comarca, "juiz": rng.choice(JUIZES), "atual": atual, "julgado": False,
                "decisao": "", "predominante": "", "data_decisao": ""}

    def processo(c: Cenario | None, grupo: dict, com_dec: str | None, situacao_dec: str = "Pendente",
                 dias_dec: int | None = None) -> dict:
        uf = rng.choice(UFS)
        comarca = rng.choice(COMARCAS[uf])
        cnj = gerar_cnj(rng, uf, rng.choice([2025, 2026]))
        pasta_n = str(rng.randint(110_000, 199_999))
        pj = novo("pj")
        autor = _nome(rng)
        distrib = hoje - timedelta(days=rng.randint(120, 400))
        cpj_proc.append({"pj": pj, "numero_processo": cnj, "numero_processo_pesq": cnj.replace("-", "").replace(".", ""),
                         "grupo_trabalho": grupo, "arquivo": "N", "sigla_integracao": pasta_n, "incidente": 0,
                         "parte_contraria": autor, "comarca": comarca, "uf": uf})
        t = [{"id_tramitacao": novo("tram"), "id_tramitacao_pai": None, "evento": "DIS",
              "evento_desc": "Distribuição", "situacao_desc": "Concluído", "data_hora_lan": _iso(distrib), "texto": ""}]
        d = [{"id_ged": novo("ged"), "id_origem": t[0]["id_tramitacao"], "path": f"G:\\Contencioso\\Saneamento\\{pasta_n}\\peticao_inicial.pdf",
              "data_criacao": _iso(distrib)}]
        arquivos[str(d[0]["id_ged"])] = "pdfs/peticao_inicial_generica.pdf"
        info = {"pj": pj, "cnj": cnj, "pasta": pasta_n, "uf": uf, "comarca": comarca, "autor": autor}
        if com_dec:
            pub = hoje - timedelta(days=dias_dec if dias_dec is not None else rng.randint(3, 18))
            lan = pub + timedelta(days=1)
            sne = {"id_tramitacao": novo("tram"), "id_tramitacao_pai": None, "evento": "SNE",
                   "evento_desc": "Publicação de nota de expediente", "situacao_desc": "Concluído",
                   "data_hora_lan": _iso(pub, "08:15:00"),
                   "texto": f"Jornal: Diário da Justiça Eletrônico - {pub.strftime('%Y%m%d')}\nIntimação da sentença."}
            dec = {"id_tramitacao": novo("tram"), "id_tramitacao_pai": sne["id_tramitacao"], "evento": com_dec,
                   "evento_desc": DESCR_DEC[com_dec], "situacao_desc": situacao_dec,
                   "data_hora_lan": _iso(lan, "14:02:00"), "texto": ""}
            t += [sne, dec]
            info.update(pub=_fmt(pub), id_dec=dec["id_tramitacao"])
            tipo_pdf = c.pdf if c else "texto"
            if tipo_pdf == "sem_pdf":
                d.append({"id_ged": novo("ged"), "id_origem": dec["id_tramitacao"],
                          "path": f"G:\\Contencioso\\Saneamento\\{pasta_n}\\sentenca_{pasta_n}.docx",
                          "data_criacao": _iso(lan)})
            else:
                nome_pdf = f"sentenca_{pasta_n}.pdf"
                ged = novo("ged")
                d.append({"id_ged": ged, "id_origem": dec["id_tramitacao"],
                          "path": f"G:\\Contencioso\\Saneamento\\{pasta_n}\\{nome_pdf}", "data_criacao": _iso(lan)})
                arq = pasta / "pdfs" / nome_pdf
                if tipo_pdf == "escaneado":
                    gerar_pdf(arq, escaneado=True, seed=ged)
                else:
                    disp = c.dispositivo if c else "Ante o exposto, JULGO IMPROCEDENTES os pedidos."
                    gerar_pdf(arq, texto_sentenca(cnj, comarca, uf, autor, rng.choice(JUIZES), disp,
                                                  c.relatorio_extra if c else ""))
                arquivos[str(ged)] = f"pdfs/{nome_pdf}"
        tram[str(pj)], docs[str(pj)] = t, d
        return info

    def no_projuris(info: dict, modo: str, regra_evento: str | None = None):
        if modo == "sem_pasta":
            return
        cnj = info["cnj"]
        if modo == "outro_cnj":       # a pasta existe, mas aponta para outro processo
            cnj = gerar_cnj(rng, info["uf"], 2024)
        f0 = fase_inicial(info["uf"], info["comarca"], cnj, hoje - timedelta(days=rng.randint(90, 300)),
                          atual=modo != "sem_fase_atual")
        if modo == "sem_comarca":
            f0["comarca"] = ""
        fases, eventos = [f0], []
        pub = datetime.strptime(info["pub"], "%d/%m/%Y").date() if info.get("pub") else hoje
        if modo == "ja_lancado":
            f0["atual"] = False
            fs = dict(fase_inicial(info["uf"], info["comarca"], cnj, pub), id=novo("fase"), fase="Sentença",
                      julgado=True, decisao="Improcedente", predominante="F", data_decisao=_fmt(pub))
            fases.append(fs)
            eventos.append({"id": novo("ev"), "data": _fmt(pub + timedelta(days=1)), "evento": regra_evento,
                            "evento_id": next(e["valor"] for e in EVENTOS if e["texto"] == regra_evento),
                            "fase_id": fs["id"], "requisicao": rng.randint(40_000, 49_999)})
        if modo == "incompleto":
            fases.append(dict(fase_inicial(info["uf"], info["comarca"], cnj, pub), id=novo("fase"),
                              fase="Sentença", atual=False))
        pj_proc.append({"id": novo("pjid"), "pasta": info["pasta"], "cnj": cnj, "cliente": REU,
                        "parte_contraria": info["autor"], "status": "Ativo", "fases": fases,
                        "eventos": eventos, "documentos": []})

    evento_de = {"DEC1": "Sentença Favorável ao Cliente", "DEC2": "Sentença Desfavorável ao Cliente",
                 "DEC3": "Sentença Parcialmente Favorável ao Cliente", "DEC13": "Sentença Sem Resolução de Mérito"}
    for c in CENARIOS:
        info = processo(c, GRUPO, c.dec)
        no_projuris(info, c.projuris, evento_de[c.dec])
        gabarito[c.chave] = {"cnj": info["cnj"], "pasta": info["pasta"], "dec": c.dec,
                             "esperado": c.esperado, "descricao": c.descricao}
    # processos do grupo sem nada a lançar (varredura passa por eles e não acha DEC pendente)
    for _ in range(4):
        no_projuris(processo(None, GRUPO, None), "normal")
    no_projuris(processo(None, GRUPO, "DEC1", situacao_dec="Concluído"), "normal")   # DEC já tratado
    no_projuris(processo(None, GRUPO, "DEC2", dias_dec=75), "normal")                # fora da janela
    # outro grupo de trabalho com DEC pendente: o robô NUNCA pode ver
    for _ in range(2):
        no_projuris(processo(None, OUTRO_GRUPO, "DEC1"), "normal")

    gerar_pdf(pasta / "pdfs" / "peticao_inicial_generica.pdf",
              "# PETIÇÃO INICIAL (fictícia)\nExcelentíssimo(a) Senhor(a) Juiz(a) de Direito. "
              "Documento de exemplo, sem relação com nenhum caso real.")

    dados = {
        "gerado_em": hoje.isoformat(),
        "aviso": "DADOS 100% FICTÍCIOS - gerados por mock/seed.py (random.Random(42))",
        "cpj": {"processos": cpj_proc, "tramitacoes": tram, "documentos": docs, "arquivos": arquivos,
                "usuarios": {"robo.demo": "senha-demo"}},
        "projuris": {"processos": pj_proc, "usuarios": {"operador": "demo123"},
                     "proximos": {"fase": seq["fase"] + 1, "ev": seq["ev"] + 1, "doc": seq["doc"] + 1,
                                  "requisicao": 48_210}},
        "gabarito": gabarito,
    }
    (pasta / "dados.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    return dados


def cnj_do_cenario(chave: str) -> str:
    """CNJ de um cenário sem gravar nada em disco (os números não dependem da data)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        return gerar(Path(tmp))["gabarito"][chave]["cnj"]


if __name__ == "__main__":
    d = gerar()
    print(f"{len(d['cpj']['processos'])} processos no CPJ, {len(d['projuris']['processos'])} no ProJuris "
          f"-> {PASTA_DADOS}")
    for k, v in d["gabarito"].items():
        print(f"  {k:24} {v['cnj']}  pasta {v['pasta']}  {v['dec']:5}  -> {v['esperado']}")
