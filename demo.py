"""
Demonstração ponta a ponta, com um comando só:

    python demo.py              # abre o Chrome para você acompanhar
    python demo.py --headless   # sem janela

1. sobe o mock (CPJ + ProJuris, dados fictícios) em http://127.0.0.1:8702
2. abre um Chrome SÓ da demo (perfil temporário, porta de depuração 9323)
3. faz o login no ProJuris no papel do OPERADOR humano — o robô nunca digita senha
4. roda o robô: simular (planilha) -> ensaiar (preenche e fecha sem salvar) -> gravar (mock)
5. confere o resultado no mock, mostra o resumo e fecha só o Chrome que ela abriu
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ROBO = RAIZ / "robo"
PORTA_MOCK, PORTA_CDP = 8702, 9323          # nunca 9222/9223 (portas de robôs reais do autor)
URL_MOCK = f"http://127.0.0.1:{PORTA_MOCK}"
CENARIO_ENSAIO = "improcedente_favoravel"

if platform.system() == "Windows":
    os.system("")                            # liga as cores ANSI no console do Windows
VERDE, AZUL, AMARELO, VERMELHO, CINZA, NEGRITO, FIM = (
    "\033[92m", "\033[96m", "\033[93m", "\033[91m", "\033[90m", "\033[1m", "\033[0m")


def titulo(txt: str):
    print(f"\n{NEGRITO}{AZUL}{'=' * 78}\n {txt}\n{'=' * 78}{FIM}", flush=True)


def info(txt: str, cor: str = CINZA):
    print(f"{cor}{txt}{FIM}", flush=True)


def porta_livre(porta: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", porta)) != 0


def esperar_url(url: str, seg: float = 20) -> bool:
    fim = time.time() + seg
    while time.time() < fim:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


# ---------- mock ----------
def subir_mock():
    import uvicorn
    sys.path.insert(0, str(RAIZ))
    from mock.app import app
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORTA_MOCK, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    if not esperar_url(f"{URL_MOCK}/saude"):
        raise SystemExit(f"{VERMELHO}O mock não subiu na porta {PORTA_MOCK}.{FIM}")
    return srv, app


# ---------- Chrome ----------
def achar_chrome() -> str | None:
    sistema = platform.system()
    candidatos: list[str] = []
    if sistema == "Windows":
        for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            if os.environ.get(var):
                candidatos.append(os.path.join(os.environ[var], "Google", "Chrome", "Application", "chrome.exe"))
    elif sistema == "Darwin":
        candidatos.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    else:
        for nome in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            if shutil.which(nome):
                candidatos.append(shutil.which(nome))
    for c in candidatos:
        if c and os.path.exists(c):
            return c
    try:                                     # plano B: o Chromium que vem com o Playwright
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            c = p.chromium.executable_path
        if c and os.path.exists(c):
            return c
    except Exception:
        pass
    return None


def preparar_perfil(perfil: str):
    """Perfil temporário sem gerenciador de senhas. A senha da demo é fraca de propósito e o
    Chrome abriria o aviso "senha encontrada em vazamento" — uma janela MODAL do navegador
    que bloqueia os cliques do robô (lição aprendida: aviso inesperado = robô para)."""
    os.makedirs(os.path.join(perfil, "Default"), exist_ok=True)
    prefs = {"credentials_enable_service": False,
             "profile": {"password_manager_enabled": False, "password_manager_leak_detection": False}}
    with open(os.path.join(perfil, "Default", "Preferences"), "w", encoding="utf-8") as f:
        json.dump(prefs, f)


def abrir_chrome(exe: str, perfil: str, headless: bool) -> subprocess.Popen:
    preparar_perfil(perfil)
    args = [exe, f"--remote-debugging-port={PORTA_CDP}", f"--user-data-dir={perfil}", "--no-first-run",
            "--no-default-browser-check", "--disable-sync", "--window-size=1366,900",
            "--disable-features=PasswordLeakDetection,TranslateUI", f"{URL_MOCK}/projuris/login"]
    if headless:
        args.insert(1, "--headless=new")
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def fechar_chrome(proc: subprocess.Popen):
    """Fecha SÓ o Chrome que a demo abriu (e os processos-filho dele)."""
    if proc.poll() is not None:
        return
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


def login_humano():
    """Faz o papel do OPERADOR: digita usuário e senha no Chrome do robô."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORTA_CDP}")
        pg, fim = None, time.time() + 15
        while not pg and time.time() < fim:      # a aba pode ainda estar em about:blank
            paginas = [x for c in b.contexts for x in c.pages]
            pg = next((x for x in paginas if "/projuris/login" in x.url), None)
            if not pg:
                time.sleep(0.3)
        if not pg:
            pg = paginas[0] if paginas else b.contexts[0].new_page()
            pg.goto(f"{URL_MOCK}/projuris/login")
        pg.wait_for_selector("input[name=usuario]")
        pg.fill("input[name=usuario]", "operador")
        pg.fill("input[name=senha]", "demo123")
        pg.click("button[type=submit]")
        pg.wait_for_url(f"{URL_MOCK}/projuris/", timeout=10_000)
    info("[humano] login feito pelo operador — o robô nunca digita senha", AMARELO)


# ---------- robô ----------
def robo(*args: str) -> tuple[int, str]:
    """Roda o CLI do robô num processo separado (como o operador faria) e mostra a saída."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
               CPJ_BASE_URL=f"{URL_MOCK}/cpj", CPJ_LOGIN="robo.demo", CPJ_SENHA="senha-demo")
    cmd = [sys.executable, str(ROBO / "rpa_sentencas.py"), *args]
    info("$ python robo/rpa_sentencas.py " + " ".join(args), AZUL)
    p = subprocess.Popen(cmd, cwd=ROBO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    saida = []
    for linha in p.stdout:
        saida.append(linha)
        cor = (VERDE if "pronto" in linha and "—" in linha else AZUL if "já lançado" in linha
               else AMARELO if "exceção" in linha else VERMELHO if "PAREI" in linha else "")
        print(f"{cor}  {linha.rstrip()}{FIM if cor else ''}", flush=True)
    return p.wait(), "".join(saida)


def ultima(padrao: str) -> Path | None:
    pastas = sorted((ROBO / "execucoes").glob(padrao))
    return pastas[-1] if pastas else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Demonstração ponta a ponta (mock local)")
    ap.add_argument("--headless", action="store_true", help="Chrome sem janela")
    a = ap.parse_args()
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass

    for porta in (PORTA_MOCK, PORTA_CDP):
        if not porta_livre(porta):
            print(f"{VERMELHO}A porta {porta} já está em uso. Feche o que estiver nela e rode de novo "
                  f"(a demo não mexe em processos que não abriu).{FIM}")
            return 1
    exe = achar_chrome()
    if not exe:
        print(f"{VERMELHO}Não achei o Google Chrome nem o Chromium do Playwright "
              f"(instale com: python -m playwright install chromium).{FIM}")
        return 1

    cfg = tomllib.loads((ROBO / "config.toml").read_text(encoding="utf-8"))
    liberado = cfg["gravacao"]["liberados"][0]
    perfil = tempfile.mkdtemp(prefix="rpa-sentencas-demo-")
    chrome = None
    resultados: dict[str, int] = {}
    try:
        titulo("1/5  Subindo o mock (CPJ + ProJuris, dados 100% fictícios)")
        _, app = subir_mock()
        gab = app.state.estado.dados["gabarito"]
        ensaio_cnj = gab[CENARIO_ENSAIO]["cnj"]
        info(f"mock no ar: {URL_MOCK}/projuris  ·  API: {URL_MOCK}/cpj/api/v3  ·  docs: {URL_MOCK}/docs", VERDE)

        titulo("2/5  Abrindo um Chrome só da demo (perfil temporário, porta 9323)")
        chrome = abrir_chrome(exe, perfil, a.headless)
        if not esperar_url(f"http://127.0.0.1:{PORTA_CDP}/json/version", 30):
            print(f"{VERMELHO}O Chrome não abriu a porta de depuração {PORTA_CDP}.{FIM}")
            return 1
        info(f"Chrome: {exe}{' (headless)' if a.headless else ''}")
        login_humano()

        titulo("3/5  SIMULAR — varre o CPJ, lê as sentenças e monta o plano (não grava nada)")
        resultados["simular"], _ = robo("simular")

        titulo(f"4/5  ENSAIAR — preenche as 4 telas em {ensaio_cnj} e FECHA SEM SALVAR")
        resultados["ensaiar"], _ = robo("ensaiar", "--numero", ensaio_cnj)

        titulo(f"5/5  GRAVAR — processo liberado {liberado} (mock: S/N respondidos pela demo)")
        resultados["gravar"], _ = robo("gravar", "--numero", liberado, "--confirmar-tudo")

        # conferência independente, direto no "banco" do mock
        proc = next(p for p in app.state.estado.dados["projuris"]["processos"] if p["cnj"] == liberado)
        fase = [f for f in proc["fases"] if f["fase"] == "Sentença"]
        doc_ev = [d for d in proc["documentos"] if d.get("evento_id")]
        conferido = bool(fase and fase[-1]["atual"] and fase[-1]["julgado"] and proc["eventos"] and doc_ev)
    finally:
        if chrome:
            fechar_chrome(chrome)
        shutil.rmtree(perfil, ignore_errors=True)

    titulo("Resumo da demonstração")
    rot = {0: f"{VERDE}ok{FIM}", 1: f"{AMARELO}nada feito{FIM}", 2: f"{VERMELHO}sem sessão{FIM}",
           3: f"{VERMELHO}CPJ indisponível{FIM}", 4: f"{VERMELHO}parado{FIM}"}
    for etapa, cod in resultados.items():
        print(f"  {etapa:<8} -> código {cod} ({rot.get(cod, cod)})")
    if fase:
        f = fase[-1]
        print(f"  mock    -> fase Sentença {f['data']} atual={f['atual']} decisão='{f['decisao']}' "
              f"predominante={f['predominante']} · eventos={len(proc['eventos'])} · PDFs no evento={len(doc_ev)}")
    sim, ens, grav = ultima("*[0-9]"), ultima("*_ensaio"), ultima("*_gravacao")
    print(f"\n  Planilha do plano : {sim / 'simulacao.xlsx' if sim else '-'}")
    print(f"  Prints do ensaio  : {ens or '-'}")
    print(f"  Gravação (prints + auditoria.jsonl): {grav or '-'}")
    tudo_ok = all(c == 0 for c in resultados.values()) and len(resultados) == 3 and conferido
    print(f"\n{NEGRITO}{VERDE if tudo_ok else VERMELHO}"
          f"{'DEMO OK — ponta a ponta conferida no mock.' if tudo_ok else 'DEMO COM FALHA — veja a saída acima.'}{FIM}")
    print(f"{CINZA}Chrome da demo fechado; nenhum outro navegador foi tocado.{FIM}")
    return 0 if tudo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
