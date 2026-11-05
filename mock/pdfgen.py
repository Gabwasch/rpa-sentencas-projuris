"""
Gerador de PDF minúsculo e sem dependências (só para os dados fictícios do mock).

- Fonte Helvetica (uma das 14 fontes padrão do PDF, não precisa embutir) com
  /Encoding /WinAnsiEncoding: o texto vai em cp1252, então "ç", "ã", "É"... saem certos
  quando o robô extrai o texto com o pypdf.
- `escaneado=True` gera páginas só com desenhos (faixas cinzas imitando linhas de texto),
  sem nenhum operador de texto — é o caso "PDF escaneado / sem texto" que o robô precisa
  detectar e mandar para exceção.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

LARGURA, ALTURA = 595, 842          # A4 em pontos
MARGEM = 56
CORPO, ENTRELINHA = 10.5, 14.5
COLUNAS = 92                         # caracteres por linha (aprox. para Helvetica 10,5)


def _escapar(texto: str) -> bytes:
    """Texto -> string literal do PDF em cp1252, com escapes octais fora do ASCII."""
    out = bytearray()
    for b in texto.encode("cp1252", errors="replace"):
        if b in (0x28, 0x29, 0x5C):              # ( ) \
            out += b"\\" + bytes([b])
        elif 32 <= b < 127:
            out.append(b)
        else:
            out += f"\\{b:03o}".encode("ascii")
    return bytes(out)


def _linhas(texto: str) -> list[tuple[str, str]]:
    """Quebra o texto em linhas. Parágrafo iniciado por '# ' sai em negrito."""
    out: list[tuple[str, str]] = []
    for par in texto.split("\n"):
        par = par.rstrip()
        if not par:
            out.append(("F1", ""))
            continue
        fonte = "F2" if par.startswith("# ") else "F1"
        par = par[2:] if fonte == "F2" else par
        for linha in textwrap.wrap(par, COLUNAS) or [""]:
            out.append((fonte, linha))
    return out


def _paginas_texto(texto: str) -> list[bytes]:
    por_pagina = int((ALTURA - 2 * MARGEM) // ENTRELINHA)
    linhas = _linhas(texto)
    paginas = []
    for i in range(0, max(len(linhas), 1), por_pagina):
        y = ALTURA - MARGEM
        ops = [b"BT"]
        for fonte, linha in linhas[i:i + por_pagina]:
            ops.append(f"/{fonte} {CORPO} Tf 1 0 0 1 {MARGEM} {y:.1f} Tm".encode())
            ops.append(b"(" + _escapar(linha) + b") Tj")
            y -= ENTRELINHA
        ops.append(b"ET")
        paginas.append(b"\n".join(ops))
    return paginas


def _pagina_escaneada(seed: int) -> bytes:
    """Faixas cinzas com larguras variadas: parece texto, mas é só desenho."""
    ops = [b"0.55 g"]
    y, n = ALTURA - MARGEM, seed
    while y > MARGEM:
        n = (n * 1103515245 + 12345) & 0x7FFFFFFF
        largura = 300 + n % (LARGURA - 2 * MARGEM - 300)
        if n % 9:
            ops.append(f"{MARGEM} {y:.1f} {largura} 6 re f".encode())
        y -= ENTRELINHA
    return b"\n".join(ops)


def gerar_pdf(destino: Path, texto: str = "", escaneado: bool = False, seed: int = 7) -> Path:
    """Grava um PDF válido em `destino` e devolve o caminho."""
    conteudos = [_pagina_escaneada(seed + i) for i in range(2)] if escaneado else _paginas_texto(texto)
    objs: list[bytes] = []
    # 1 catálogo, 2 páginas, 3/4 fontes; depois (página, conteúdo) para cada página
    kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(len(conteudos)))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(conteudos)} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    for i, c in enumerate(conteudos):
        objs.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {LARGURA} {ALTURA}] "
                     f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {6 + 2 * i} 0 R >>").encode())
        objs.append(f"<< /Length {len(c)} >>\nstream\n".encode() + c + b"\nendstream")

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, corpo in enumerate(objs, 1):
        offsets.append(len(pdf))
        pdf += f"{n} 0 obj\n".encode() + corpo + b"\nendobj\n"
    xref = len(pdf)
    pdf += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(bytes(pdf))
    return destino
