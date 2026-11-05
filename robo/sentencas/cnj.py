"""Número único de processo (CNJ, Resolução 65/2008): NNNNNNN-DD.AAAA.J.TR.OOOO."""
from __future__ import annotations

import re

_FORMATO = re.compile(r"^(\d{7})-?(\d{2})\.?(\d{4})\.?(\d)\.?(\d{2})\.?(\d{4})$")


def so_digitos(t) -> str:
    return re.sub(r"\D", "", str(t or ""))


def digito(seq: str, ano: str, j: str, tr: str, origem: str) -> str:
    """Dígito verificador (ISO 7064 mod 97-10)."""
    return f"{98 - int(seq + ano + j + tr + origem + '00') % 97:02d}"


def valido(cnj: str) -> bool:
    m = _FORMATO.match(str(cnj or "").strip())
    if not m:
        return False
    seq, dv, ano, j, tr, origem = m.groups()
    return int(seq + ano + j + tr + origem + dv) % 97 == 1


def formatar(cnj: str) -> str:
    d = so_digitos(cnj)
    if len(d) != 20:
        return str(cnj or "")
    return f"{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:]}"


def mesmo(a: str, b: str) -> bool:
    return so_digitos(a) == so_digitos(b) != ""
