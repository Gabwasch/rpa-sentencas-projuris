import random

import pytest

from mock import seed
from sentencas import cnj


def test_digito_e_validacao_batem():
    rng = random.Random(1)
    for _ in range(200):
        n = seed.gerar_cnj(rng, rng.choice(seed.UFS), 2026)
        assert cnj.valido(n), n


@pytest.mark.parametrize("ruim", ["", "123", "0000001-00.2026.8.24.0001", "abc1234-56.2026.8.24.0001"])
def test_invalidos(ruim):
    assert not cnj.valido(ruim)


def test_digito_errado_eh_invalido():
    n = seed.gerar_cnj(random.Random(3), "SC", 2025)
    dv = int(n[8:10])
    trocado = n[:8] + f"{(dv + 1) % 100:02d}" + n[10:]
    assert cnj.valido(n) and not cnj.valido(trocado)


def test_aceita_sem_pontuacao_e_formata():
    n = seed.gerar_cnj(random.Random(5), "PR", 2026)
    d = cnj.so_digitos(n)
    assert len(d) == 20 and cnj.valido(d) and cnj.formatar(d) == n


def test_mesmo():
    n = seed.gerar_cnj(random.Random(7), "MG", 2026)
    assert cnj.mesmo(n, cnj.so_digitos(n))
    assert not cnj.mesmo("", "")


def test_modulo_do_robo_e_do_mock_concordam():
    assert cnj.digito("1234567", "2026", "8", "24", "0001") == seed.digito_cnj("1234567", "2026", "8", "24", "0001")
