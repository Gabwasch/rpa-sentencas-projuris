"""
Sugestão do campo "Decisão" do ProJuris a partir do DISPOSITIVO da sentença (PDF do CPJ).

Combinado com a equipe jurídica: o robô SUGERE, mostra o trecho e uma pessoa confirma.
Se não achar o dispositivo, achar resultados conflitantes ou o resultado não combinar com o
evento DEC do CPJ -> exceção (não lança). O robô nunca chuta.

Como funciona:
1. Extrai o texto do PDF (pypdf). O pypdf às vezes junta termos ("parcialmenteprocedente",
   "dospedidos"), por isso os padrões aceitam espaço opcional (\\s*).
2. Procura, do FIM para o começo, os marcadores do dispositivo ("DISPOSITIVO", "Ante o exposto",
   "Diante do exposto", "Isso posto", "Ex positis"...). Usa o último marcador cuja janela tenha
   um resultado. Ler só o dispositivo evita pegar a preliminar rejeitada ou decisões citadas
   no relatório.
3. Na janela, apaga (mantendo as posições) o que fala de pedido contraposto / reconvenção —
   isso não define o resultado da ação.
4. Classifica: parcial > (procedente x improcedente; os dois sem "parcial" = conflito)
   > sem resolução do mérito.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import regras as R

JANELA = 1500          # caracteres lidos depois do marcador
CONTEXTO = 220         # caracteres de cada lado no trecho mostrado à pessoa
MINIMO_TEXTO = 200     # menos que isso = PDF sem texto (escaneado)

_MARCADORES = re.compile(
    r"dispositivo|ante\s*a?o\s*exposto|diante\s*d?o\s*exposto|isso\s*posto|isto\s*posto|posto\s*isso|"
    r"pelo\s*exposto|em\s*face\s*do\s*exposto|face\s*ao\s*exposto|por\s*todo\s*o\s*exposto|"
    r"ex\s*positis|do\s*exposto")
_PARCIAL = re.compile(
    r"parcial\s*mente\s*procedentes?|procedencia\s*parcial|parcial\s*procedencia|procedentes?\s*em\s*parte|"
    r"procedencia\s*em\s*parte|acolhimento\s*parcial|acolho\s*parcial\s*mente|parcial\s*acolhimento|"
    r"concedo\s*parcial\s*mente\s*a\s*seguranca|concessao\s*parcial\s*da\s*seguranca")
_IMPROC = re.compile(
    r"improcedentes?|improcedencia|rejeito\s*os?\s*pedidos?|denego\s*a\s*seguranca|"
    r"denegacao\s*da\s*seguranca|nao\s*acolhimento\s*dos?\s*pedidos?")
_PROC = re.compile(
    r"(?<!im)procedentes?|(?<!im)procedencia|(?<!nao )acolho\s*os?\s*pedidos?|"
    r"concedo\s*a\s*seguranca|concessao\s*da\s*seguranca")
# pedido contraposto / reconvenção: não definem o resultado da ação -> mascarados.
# O intervalo não pode conter outro "proceden...": sem isso, em "procedente a ação e improcedente
# a reconvenção" o casamento mais à esquerda engolia também o resultado da AÇÃO.
_ACESSORIO = re.compile(
    r"(parcial\s*(mente\s*)?)?(im)?proceden\w*(\s*em\s*parte)?(?:(?!proceden)[^.;:]){0,30}?"
    r"(pedido\s*|pleito\s*)?(contraposto|reconven\w*)")
_SEM_MERITO = re.compile(
    r"sem\s*(resolucao|julgamento|exame|apreciacao)\s*d[oe]\s*merito|"
    r"extingo\s*o\s*(processo|feito)\s*,?\s*sem")


@dataclass
class Sugestao:
    decisao: str            # "" = não conseguiu sugerir
    trecho: str             # trecho do dispositivo usado (para a pessoa conferir)
    motivo: str = ""        # por que não sugeriu / observação


def normalizar(t: str) -> str:
    """Minúsculas e sem acento, MANTENDO o tamanho (para recortar o trecho no texto original)."""
    out = []
    for c in t:
        base = unicodedata.normalize("NFKD", c)
        out.append((base[0] if base else c).lower())
    return "".join(out)


def texto_pdf(arq: Path) -> str:
    from pypdf import PdfReader
    txt = " ".join((p.extract_text() or "") for p in PdfReader(str(arq)).pages)
    return re.sub(r"\s+", " ", txt).strip()


def _mascarar(janela: str) -> str:
    return _ACESSORIO.sub(lambda m: " " * len(m.group(0)), janela)


def classificar(janela: str) -> tuple[str, re.Match | None, str]:
    """-> (decisão, achado, motivo). Achado None = a janela não tem resultado."""
    janela = _mascarar(janela)
    p = _PARCIAL.search(janela)
    if p:
        return R.PARCIAL, p, ""
    sem_parcial = _PARCIAL.sub(lambda m: " " * len(m.group(0)), janela)
    i = _IMPROC.search(sem_parcial)
    pr = _PROC.search(_IMPROC.sub(lambda m: " " * len(m.group(0)), sem_parcial))
    if i and pr:
        return "", i, "o dispositivo fala em procedente E improcedente (sem 'parcialmente')"
    if i:
        return R.IMPROCEDENTE, i, ""
    if pr:
        return R.PROCEDENTE, pr, ""
    s = _SEM_MERITO.search(janela)
    if s:
        return R.SEM_MERITO, s, ""
    return "", None, ""


def sugerir(texto: str) -> Sugestao:
    if not texto or len(texto.strip()) < MINIMO_TEXTO:
        return Sugestao("", "", "não consegui ler o texto do PDF (imagem escaneada?)")
    norm = normalizar(texto)
    for m in reversed(list(_MARCADORES.finditer(norm))):
        janela = norm[m.start(): m.start() + JANELA]
        dec, achado, motivo = classificar(janela)
        if achado is None:
            continue
        ini = m.start() + max(0, achado.start() - CONTEXTO)
        fim = m.start() + min(len(janela), achado.end() + CONTEXTO)
        trecho = ("…" if ini > 0 else "") + texto[ini:fim].strip() + ("…" if fim < len(texto) else "")
        return Sugestao(dec, trecho, motivo)
    return Sugestao("", "", "não encontrei o dispositivo (procedente/improcedente) na sentença")


def avaliar(regra: R.Regra, sug: Sugestao) -> tuple[str, str]:
    """Cruza a leitura com o DEC. -> (decisão final, motivo de exceção). Motivo vazio = segue."""
    if regra.decisao_fixa:                                # DEC13: decisão definida pela regra
        if sug.decisao in (R.PROCEDENTE, R.IMPROCEDENTE, R.PARCIAL):
            return "", (f"{regra.dec} (sem mérito), mas a sentença parece '{sug.decisao}' — "
                        "conferir o evento no CPJ")
        return regra.decisao_fixa, ""
    if not sug.decisao:
        return "", sug.motivo or "não consegui sugerir a decisão"
    if sug.decisao not in regra.decisoes_aceitas:
        return "", (f"a sentença indica '{sug.decisao}', que não combina com {regra.dec} "
                    f"({regra.descricao_cpj}) — conferir")
    return sug.decisao, ""
