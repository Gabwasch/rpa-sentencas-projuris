"""
Monta o PLANO de lançamento (V1: sentenças) — SIMULAÇÃO, não grava nada no ProJuris.

Para cada DEC pendente do CPJ:
  1. confere a regra (DEC1/2/3/13) e o PDF anexado ao DEC;
  2. sugere a Decisão lendo o dispositivo (decisao.py) e cruza com o DEC;
  3. acha o processo no ProJuris pela PASTA e confere o CNJ;
  4. lê fases/eventos: evento igual perto da publicação -> JÁ LANÇADO; fase Sentença sem
     evento -> lançamento incompleto (exceção); sem UMA fase atual -> exceção;
  5. descreve o que seria lançado (fase, decisão, evento, documento).

Também gera a planilha .xlsx do plano (uma linha por DEC, colorida pela situação).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from . import regras as R
from .cnj import mesmo as mesmo_cnj
from .cpj import Dec, nome_doc
from .decisao import avaliar, sugerir, texto_pdf
from .projuris import ProJurisErro, SemSessao

PRONTO, JA_LANCADO, EXCECAO = "pronto", "já lançado", "exceção"


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _dt(s: str):
    try:
        return datetime.strptime(s, "%d/%m/%Y")
    except (TypeError, ValueError):
        return None


@dataclass
class Item:
    cnj: str
    pasta: str
    pj: int
    dec: str
    descricao_cpj: str
    data_publicacao: str
    lancado_em: str = ""
    situacao: str = EXCECAO
    motivo: str = ""
    # o que seria lançado
    id_projuris: int | None = None
    fase: str = ""
    decisao: str = ""
    decisao_sugerida: str = ""
    predominante: str = ""
    evento: str = ""
    documento: str = ""
    trecho: str = ""
    pdf_local: str = ""

    def linha(self) -> dict:
        return asdict(self)


def planejar(dec: Dec, cpj, pj, pasta_pdfs: Path, ler_texto=texto_pdf) -> Item:
    """`cpj` precisa de .baixar(); `pj` (ou None) de .buscar_pasta() e .ler_processo()."""
    regra = R.REGRAS.get(dec.dec)
    it = Item(cnj=dec.cnj, pasta=dec.pasta, pj=dec.pj, dec=dec.dec, descricao_cpj=dec.descricao,
              data_publicacao=dec.data_publicacao, lancado_em=dec.lancado_em)
    if not regra:
        it.motivo = f"{dec.dec} fora da V1 (só sentenças: {', '.join(R.REGRAS)})"
        return it
    it.predominante = R.NOME_PREDOMINANTE[regra.predominante]
    it.evento = regra.evento
    if not dec.data_publicacao:
        it.motivo = "sem data da publicação no CPJ"
        return it

    # 1) PDF + sugestão da decisão
    if not dec.pdf:
        extra = f" (anexos: {', '.join(dec.outros_docs)})" if dec.outros_docs else ""
        it.motivo = "o DEC não tem PDF anexado no CPJ" + extra
        return it
    it.documento = f"{nome_doc(dec.pdf)} (tipo {R.TIPO_DOCUMENTO}, data {dec.data_publicacao})"
    destino = Path(pasta_pdfs) / f"{dec.pj}_{dec.id_tramitacao}" / nome_doc(dec.pdf)   # nome original do CPJ
    try:
        cpj.baixar(dec.pdf["id_ged"], destino)
        it.pdf_local = str(destino)
        sug = sugerir(ler_texto(destino))
    except Exception as e:
        it.motivo = f"não consegui baixar/ler o PDF ({type(e).__name__})"
        return it
    it.decisao_sugerida, it.trecho = sug.decisao, sug.trecho
    decisao, motivo = avaliar(regra, sug)
    if motivo:
        it.motivo = motivo
        return it
    it.decisao = decisao

    # 2) ProJuris (só leitura)
    if pj is None:
        it.situacao, it.motivo = PRONTO, "ProJuris não consultado (--sem-projuris)"
        return it
    if not dec.pasta:
        it.motivo = "processo sem pasta (sigla de integração) no CPJ"
        return it
    try:
        achados = pj.buscar_pasta(dec.pasta)
        if len(achados) != 1:
            it.motivo = f"pasta {dec.pasta} {'não encontrada' if not achados else 'com mais de um processo'} no ProJuris"
            return it
        if not mesmo_cnj(achados[0]["cnj"], dec.cnj):
            it.motivo = f"pasta {dec.pasta} no ProJuris é do processo {achados[0]['cnj']} (CPJ: {dec.cnj})"
            return it
        it.id_projuris = achados[0]["id"]
        proc = pj.ler_processo(it.id_projuris)
    except SemSessao:
        raise
    except ProJurisErro as e:
        it.motivo = str(e)
        return it
    if proc.pasta and proc.pasta != dec.pasta:
        it.motivo = f"o processo aberto no ProJuris é da pasta {proc.pasta} (esperado {dec.pasta})"
        return it

    # 3) já lançado? (mesmo tipo de evento perto da data da publicação)
    dp = _dt(dec.data_publicacao)
    for ev in proc.eventos:
        de = _dt(ev.data)
        if norm(ev.evento) == norm(regra.evento) and dp and de and abs((de - dp).days) <= R.JANELA_JA_LANCADO_DIAS:
            it.situacao, it.motivo = JA_LANCADO, f"evento já existe no ProJuris ({ev.data}, fase {ev.fase})"
            return it
    for f in proc.fases:
        df = _dt(f.data)
        if norm(f.fase) == norm(R.FASE_NOME) and dp and df and abs((df - dp).days) <= R.JANELA_JA_LANCADO_DIAS:
            it.motivo = (f"já existe fase Sentença de {f.data} {'(julgada)' if f.julgado else '(sem decisão)'} "
                         "mas sem o evento — lançamento incompleto, conferir à mão")
            return it

    atual = proc.fase_atual
    if not atual:
        it.motivo = "o processo não tem UMA fase marcada como atual no ProJuris"
        return it
    if not (atual.tribunal and atual.jurisdicao and atual.uf and atual.comarca):
        it.motivo = "a fase atual está sem tribunal/jurisdição/UF/comarca para copiar"
        return it
    it.fase = (f"{R.FASE_TIPO_RECURSO} · {R.FASE_NOME} · {dec.data_publicacao} · nº {atual.numero or dec.cnj} · "
               f"{atual.tribunal} / {atual.jurisdicao} / {atual.comarca}-{atual.uf} · Atual")
    it.situacao = PRONTO
    return it


# =========================================================================================
# Planilha
# =========================================================================================
COLUNAS = [("situacao", "Situação"), ("motivo", "Motivo / observação"), ("cnj", "Processo (CNJ)"),
           ("pasta", "Pasta"), ("dec", "DEC"), ("descricao_cpj", "Evento no CPJ"),
           ("lancado_em", "DEC lançado no CPJ em"), ("data_publicacao", "Data publicação"),
           ("decisao", "Decisão (lançar)"), ("decisao_sugerida", "Decisão lida na sentença"),
           ("predominante", "Decisão predominante"), ("evento", "Evento ProJuris"), ("fase", "Fase a criar"),
           ("documento", "Documento"), ("trecho", "Trecho da sentença"), ("id_projuris", "ID ProJuris"),
           ("pj", "PJ (CPJ)")]
CORES = {PRONTO: "E2EFDA", JA_LANCADO: "DDEBF7", EXCECAO: "FCE4D6"}


def resumo(itens: list[Item]) -> dict[str, int]:
    return {s: sum(i.situacao == s for i in itens) for s in (PRONTO, JA_LANCADO, EXCECAO)}


def salvar_xlsx(itens: list[Item], arq: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Simulação"
    ws.append([t for _, t in COLUNAS])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for it in itens:
        d = it.linha()
        ws.append([d.get(k) for k, _ in COLUNAS])
        for c in ws[ws.max_row]:
            c.fill = PatternFill("solid", fgColor=CORES.get(it.situacao, "FFFFFF"))
            c.alignment = Alignment(wrap_text=True, vertical="top")
    larguras = {"Motivo / observação": 45, "Trecho da sentença": 80, "Fase a criar": 50, "Evento ProJuris": 36,
                "Documento": 38, "Evento no CPJ": 30, "Processo (CNJ)": 27}
    for i, (_, t) in enumerate(COLUNAS, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = larguras.get(t, 16)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    # aba de resumo
    r = wb.create_sheet("Resumo")
    r.append(["Situação", "Quantidade"])
    for s, n in resumo(itens).items():
        r.append([s, n])
        r.cell(r.max_row, 1).fill = PatternFill("solid", fgColor=CORES[s])
    r.append(["total", len(itens)])
    r["A1"].font = r["B1"].font = Font(bold=True)
    r.column_dimensions["A"].width = 18
    Path(arq).parent.mkdir(parents=True, exist_ok=True)
    wb.save(arq)
    return Path(arq)
