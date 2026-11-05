"""
Regras de tradução CPJ -> ProJuris (V1: só sentenças), combinadas com a equipe jurídica.

- O evento DEC do CPJ já diz se a decisão foi favorável / desfavorável / parcial PARA O
  CLIENTE -> define o EVENTO do ProJuris e a DECISÃO PREDOMINANTE (F / D / P).
- Procedente / Improcedente NÃO sai do DEC: "favorável ao cliente" pode ser IMPROCEDENTE
  (o cliente é réu e o pedido do autor foi negado) ou PROCEDENTE (o cliente é autor). Por isso
  o robô LÊ o dispositivo da sentença, SUGERE e uma pessoa confirma (ver decisao.py).
- DEC13 (sem resolução do mérito) -> decisão fixa "Decisão Sem julgamento de Mérito" + Favorável.
- O cadastro de decisões tem duas opções quase iguais; usar SÓ "Procedente em parte"
  (texto exato). "Procedente em Parte" é uma duplicidade antiga.
- Datas (início da fase, decisão, evento, documento) = data da publicação (SNE no CPJ).
- Acórdãos e embargos de declaração ficam para a próxima etapa.

IDs abaixo são do ambiente de demonstração (mock) — fictícios.
"""
from __future__ import annotations

from dataclasses import dataclass

GRUPO_TRABALHO = 31        # CPJ "Cível - Saneamento Consumidor" — NUNCA ler processos de outro grupo

# decisões do campo "Decisão" do ProJuris (texto EXATO do cadastro)
PROCEDENTE = "Procedente"
IMPROCEDENTE = "Improcedente"
PARCIAL = "Procedente em parte"            # NÃO usar "Procedente em Parte" (duplicidade)
SEM_MERITO = "Decisão Sem julgamento de Mérito"

# decisão predominante (radio DECISAO_OBJETO do ProJuris)
FAVORAVEL, DESFAVORAVEL, FAV_PARTE = "F", "D", "P"
NOME_PREDOMINANTE = {FAVORAVEL: "Favorável", DESFAVORAVEL: "Desfavorável", FAV_PARTE: "Favorável em parte"}


@dataclass(frozen=True)
class Regra:
    dec: str
    descricao_cpj: str
    evento_id: int             # ID do tipo de evento no ProJuris (mais seguro que o nome)
    evento: str                # nome no ProJuris (exibir / conferir)
    predominante: str          # F | D | P
    decisoes_aceitas: tuple    # o que a leitura da sentença pode dar sem virar exceção
    decisao_fixa: str = ""     # quando não depende da leitura (DEC13)


REGRAS: dict[str, Regra] = {r.dec: r for r in [
    Regra("DEC1", "Sentença Cível Favorável", 4101, "Sentença Favorável ao Cliente",
          FAVORAVEL, (IMPROCEDENTE, PROCEDENTE)),
    Regra("DEC2", "Sentença Cível Desfavorável", 4102, "Sentença Desfavorável ao Cliente",
          DESFAVORAVEL, (PROCEDENTE, IMPROCEDENTE)),
    Regra("DEC3", "Sentença Cível Parcialmente Favorável", 4103, "Sentença Parcialmente Favorável ao Cliente",
          FAV_PARTE, (PARCIAL,)),
    Regra("DEC13", "Sentença Sem Resolução do Mérito", 4113, "Sentença Sem Resolução de Mérito",
          FAVORAVEL, (SEM_MERITO,), decisao_fixa=SEM_MERITO),
]}

# fase criada para a sentença (tribunal / jurisdição / UF / comarca copiados da fase atual)
FASE_TIPO_RECURSO = "Processo Origem"
FASE_NOME = "Sentença"
TIPO_DOCUMENTO = "Sentença"
JANELA_JA_LANCADO_DIAS = 30    # mesmo evento até N dias da publicação = já lançado
