"""
Robô de lançamento de SENTENÇAS no ProJuris a partir das decisões já classificadas no CPJ.

  python rpa_sentencas.py simular                     # varre o CPJ e monta o plano (.xlsx)
  python rpa_sentencas.py simular --numero <CNJ>      # um processo só
  python rpa_sentencas.py simular --sem-projuris      # só CPJ + leitura da sentença
  python rpa_sentencas.py ensaiar --numero <CNJ>      # preenche as 4 telas e FECHA SEM SALVAR
  python rpa_sentencas.py gravar  --numero <CNJ>      # GRAVA (só liberados; S/N antes de cada Salvar)
  python rpa_sentencas.py anexar  --numero <CNJ>      # só a etapa 4 (PDF dentro do evento já salvo)

Códigos de saída: 0 ok · 1 nada feito / recusado · 2 sem sessão no ProJuris ·
                  3 CPJ indisponível · 4 gravação interrompida no meio (ver auditoria.jsonl)
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from sentencas import regras as R                                                    # noqa: E402
from sentencas.cnj import so_digitos                                                 # noqa: E402
from sentencas.cpj import (CPJ, CPJIndisponivel, carregar_env, decs_do_processo,     # noqa: E402
                           decs_pendentes, processo_por_cnj)
from sentencas.projuris import ProJuris, SemSessao, eh_local                         # noqa: E402
from sentencas.simulacao import EXCECAO, JA_LANCADO, PRONTO, planejar, resumo, salvar_xlsx  # noqa: E402

OK, NADA, SEM_SESSAO, CPJ_FORA, PARADO = 0, 1, 2, 3, 4


def _pasta_execucao(sufixo: str = "") -> Path:
    p = BASE / "execucoes" / (datetime.now().strftime("%Y-%m-%d_%H%M%S") + sufixo)
    (p / "pdfs").mkdir(parents=True, exist_ok=True)
    return p


def _cpj(cfg) -> CPJ:
    env = carregar_env(BASE / cfg["cpj"].get("env", ".env"))
    return CPJ(env, grupo_trabalho=R.GRUPO_TRABALHO)


def _projuris(cfg) -> ProJuris:
    return ProJuris(cfg["projuris"]["url"], cfg["projuris"]["cdp"])


def _dec_do_processo(cpj: CPJ, numero: str):
    """O DEC pendente mais recente (com PDF) de um processo — ou (None, mensagem)."""
    proc = processo_por_cnj(cpj, numero)
    if not proc:
        return None, f"Processo {numero} não encontrado no CPJ no grupo de trabalho {R.GRUPO_TRABALHO}."
    decs = [d for d in decs_do_processo(cpj, proc, set(R.REGRAS), None) if d.pdf]
    if not decs:
        return None, f"O processo não tem sentença pendente ({'/'.join(R.REGRAS)}) com PDF no CPJ."
    return sorted(decs, key=lambda x: x.id_tramitacao)[-1], ""


def _dados_lancamento(d, it) -> dict:
    regra = R.REGRAS[d.dec]
    return {"data": d.data_publicacao, "cnj": d.cnj, "decisao": it.decisao, "predominante": regra.predominante,
            "evento_id": regra.evento_id, "evento": regra.evento}


# =========================================================================================
def simular(a, cfg) -> int:
    cpj = _cpj(cfg)
    eventos = set(R.REGRAS)
    if a.numero:
        proc = processo_por_cnj(cpj, a.numero)
        if not proc:
            print(f"Processo {a.numero} não encontrado no CPJ no grupo de trabalho {R.GRUPO_TRABALHO}.")
            return NADA
        decs = decs_do_processo(cpj, proc, eventos, None)
    else:
        dias = cfg["cpj"].get("janela_dias", 30)
        print(f"Varrendo o CPJ (grupo {R.GRUPO_TRABALHO}, DECs pendentes dos últimos {dias} dias)...")
        decs = decs_pendentes(cpj, eventos, dias=dias, paralelo=cfg["cpj"].get("paralelo", 4),
                              progresso=lambda f, t, n: print(f"  {f}/{t} processos lidos · {n} DECs", flush=True))
    print(f"{len(decs)} decisão(ões) pendente(s) no CPJ.")
    if not decs:
        return OK

    pj = None
    if not a.sem_projuris:
        try:
            pj = _projuris(cfg)
        except SemSessao as e:
            print(f"\nPAREI: {e}")
            return SEM_SESSAO

    pasta = _pasta_execucao()
    itens, codigo = [], OK
    try:
        for i, d in enumerate(sorted(decs, key=lambda x: (x.dec, x.cnj)), 1):
            print(f"[{i:>2}/{len(decs)}] {d.cnj} · {d.dec:<5} ... ", end="", flush=True)
            it = planejar(d, cpj, pj, pasta / "pdfs")
            itens.append(it)
            print(it.situacao + (f" — {it.motivo}" if it.motivo else f" — {it.decisao} · {it.predominante}"))
    except SemSessao as e:
        print(f"\nPAREI: {e}")
        codigo = SEM_SESSAO
    finally:
        if pj:
            pj.fechar()
    arq = salvar_xlsx(itens, pasta / "simulacao.xlsx")
    r = resumo(itens)
    print(f"\nResumo: {r[PRONTO]} pronto(s) · {r[JA_LANCADO]} já lançado(s) · {r[EXCECAO]} exceção(ões)")
    print(f"Planilha: {arq}")
    print("SIMULAÇÃO: nada foi gravado no ProJuris.")
    return codigo


def ensaiar(a, cfg) -> int:
    """Preenche as 4 telas num processo e FECHA SEM SALVAR. Só para conferir os campos."""
    from sentencas.lancar import Formularios
    cpj = _cpj(cfg)
    d, msg = _dec_do_processo(cpj, a.numero)
    if not d:
        print(msg)
        return NADA
    try:
        pj = _projuris(cfg)
    except SemSessao as e:
        print(f"PAREI: {e}")
        return SEM_SESSAO
    pasta = _pasta_execucao("_ensaio")
    try:
        it = planejar(d, cpj, pj, pasta / "pdfs")
        print(f"Plano: {it.situacao} — {it.motivo or it.decisao}")
        if it.situacao != PRONTO:
            print("Ensaio só roda em item 'pronto'.")
            return NADA
        procpj = pj.ler_processo(it.id_projuris)
        print(f"Ensaio no processo {d.cnj} (pasta {d.pasta}) — preenche e FECHA SEM SALVAR:")
        falhas = 0
        for e in Formularios(pj, pasta).ensaiar(procpj, _dados_lancamento(d, it), Path(it.pdf_local)):
            falhas += bool(e.erro or e.invalidos)
            print(f"\n[{e.etapa}] {'ERRO: ' + e.erro if e.erro else 'ok'}")
            for k, v in e.preenchido.items():
                print(f"   {k}: {v}")
            if e.invalidos:
                print(f"   CAMPOS INVÁLIDOS: {', '.join(e.invalidos)}")
            print(f"   print: {e.print_}")
    except SemSessao as e:
        print(f"PAREI: {e}")
        return SEM_SESSAO
    finally:
        pj.fechar()
    print(f"\nENSAIO: nada foi salvo no ProJuris. Prints em {pasta}")
    return OK if not falhas else NADA


def gravar(a, cfg, so_anexar: bool = False) -> int:
    """Grava UM processo liberado no config.toml, perguntando S/N antes de cada Salvar."""
    from sentencas.gravar import Gravacao, Parado, fechar_janela_aberta
    liberados = {so_digitos(n) for n in cfg.get("gravacao", {}).get("liberados", [])}
    if so_digitos(a.numero) not in liberados:
        print(f"PAREI: {a.numero} não está em [gravacao] liberados do config.toml.")
        return NADA
    env = carregar_env(BASE / cfg["cpj"].get("env", ".env"))
    if a.confirmar_tudo:
        if not (eh_local(cfg["projuris"]["url"]) and eh_local(env["CPJ_BASE_URL"])):
            print("PAREI: --confirmar-tudo só é aceito contra o mock local (127.0.0.1/localhost).")
            return NADA
        print("[demo] --confirmar-tudo: as perguntas S/N serão respondidas 'S' automaticamente (mock local).")

        def perguntar(txt):
            print("      " + txt + "S  [demo]")
            return True
    else:
        if not sys.stdin.isatty():
            print("PAREI: a gravação pergunta S/N antes de cada Salvar — rode num terminal interativo.")
            return NADA

        def perguntar(txt):
            try:
                return input("      " + txt).strip().lower() in ("s", "sim")
            except (EOFError, KeyboardInterrupt, OSError):      # sem resposta de verdade = NÃO
                print(" (sem resposta -> N)")
                return False

    cpj = CPJ(env, grupo_trabalho=R.GRUPO_TRABALHO)
    d, msg = _dec_do_processo(cpj, a.numero)
    if not d:
        print(msg)
        return NADA
    try:
        pj = _projuris(cfg)
    except SemSessao as e:
        print(f"PAREI: {e}")
        return SEM_SESSAO
    pasta = _pasta_execucao("_anexar" if so_anexar else "_gravacao")
    try:
        it = planejar(d, cpj, pj, pasta / "pdfs")
        print(f"\nProcesso {d.cnj} (pasta {d.pasta}) · {d.dec} · publicação {d.data_publicacao}")
        print(f"Plano: {it.situacao} — {it.motivo or it.decisao}")
        if so_anexar:
            if not it.pdf_local or not it.id_projuris:
                print("Não consegui o PDF do CPJ ou o processo no ProJuris. Nada foi feito.")
                return NADA
        elif it.situacao != PRONTO:
            print("Só grava item 'pronto'. Nada foi feito.")
            return NADA
        print(f"  Fase:      {it.fase}")
        print(f"  Decisão:   {it.decisao} · {it.predominante}")
        print(f"  Evento:    {it.evento}")
        print(f"  Documento: {it.documento}")
        print(f"  Trecho:    {it.trecho[:300]}")
        pergunta = ("Anexar o PDF no evento já salvo deste processo? [S/N]: " if so_anexar
                    else "Começar a gravação deste processo? [S/N]: ")
        if not perguntar(pergunta):
            print("Nada foi feito.")
            return NADA
        dados = _dados_lancamento(d, it)
        if so_anexar and not dados["decisao"]:
            dados["decisao"] = it.decisao_sugerida
        procpj = pj.ler_processo(it.id_projuris)
        try:
            g = Gravacao(pj, pasta, perguntar)
            final = (g.anexar if so_anexar else g.gravar)(procpj, dados, Path(it.pdf_local))
        except SemSessao:
            raise
        except Exception as e:          # Parado, ProJurisErro ou erro inesperado: para e mostra
            print(f"\nPAREI: {e}")
            if fechar_janela_aberta(pj):
                print("(a janela que estava aberta foi fechada sem salvar)")
            print(f"Veja o que já foi salvo em {pasta / 'auditoria.jsonl'} antes de rodar de novo "
                  "(não repetir etapas; se parou depois do evento, use 'anexar').")
            return PARADO
        print("\nCONFERÊNCIA FINAL no ProJuris:")
        print("  evento:   ", "; ".join(final["evento"]) or "NÃO ENCONTRADO")
        print("  documento:", "; ".join(final["documento"]) or "NÃO ENCONTRADO")
        print("  PDF dentro do evento:", "sim" if final["documento_no_evento"] else "NÃO")
        ok = bool(final["evento"] and final["documento"] and final["documento_no_evento"])
    except SemSessao as e:
        print(f"PAREI: {e}")
        return SEM_SESSAO
    finally:
        pj.fechar()
    print(f"\nRegistro: {pasta / 'auditoria.jsonl'}")
    return OK if ok else PARADO


# =========================================================================================
def main(argv=None) -> int:
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Robô de sentenças CPJ -> ProJuris")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("simular", help="monta o plano sem gravar nada")
    s.add_argument("--numero", help="só este processo (CNJ)")
    s.add_argument("--sem-projuris", action="store_true", help="não consulta o ProJuris")
    e = sub.add_parser("ensaiar", help="preenche as telas num processo e fecha SEM salvar")
    e.add_argument("--numero", required=True, help="processo (CNJ)")
    for nome, ajuda in (("gravar", "GRAVA um processo liberado (S/N antes de cada Salvar)"),
                        ("anexar", "anexa o PDF no evento JÁ salvo (gravação que parou no evento)")):
        g = sub.add_parser(nome, help=ajuda)
        g.add_argument("--numero", required=True, help="processo (CNJ) listado em [gravacao] liberados")
        g.add_argument("--confirmar-tudo", action="store_true",
                       help="DEMO: responde S a todas as perguntas — só aceito contra o mock local")
    a = ap.parse_args(argv)
    cfg = tomllib.loads((BASE / "config.toml").read_text(encoding="utf-8"))
    acoes = {"simular": simular, "ensaiar": ensaiar, "gravar": gravar,
             "anexar": lambda a_, c_: gravar(a_, c_, so_anexar=True)}
    try:
        return acoes[a.cmd](a, cfg)
    except CPJIndisponivel as e:
        print(f"\nPAREI: {e}")
        return CPJ_FORA


if __name__ == "__main__":
    sys.exit(main())
