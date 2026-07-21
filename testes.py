#!/usr/bin/env python3
"""Testes do AV Downloader.

    venv/bin/python testes.py          # tudo (rápidos + rede)
    venv/bin/python testes.py rapidos  # só os que não usam internet

Os testes de rede consultam o YouTube de verdade (nada é baixado, exceto um
vídeo de 19s no teste de ciclo). Nenhum teste toca na sua configuração: todos
rodam com um HOME temporário.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

_TMP = Path(tempfile.mkdtemp(prefix="avd-testes-"))
os.environ["HOME"] = str(_TMP / "home")
(_TMP / "home").mkdir(parents=True, exist_ok=True)

import main as m  # noqa: E402  (precisa do HOME já ajustado)
from main import (AVDownloaderApp, Config, Job, Status)  # noqa: E402

VERDE, VERM, AMAR, FIM = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
_resultados: list[tuple[str, bool, str]] = []


def teste(nome: str, rede: bool = False):
    def decorador(func):
        func._nome, func._rede = nome, rede
        return func
    return decorador


def _cfg() -> Config:
    cfg = Config()
    cfg.cookies_file = "/nao/existe"
    cfg.auto_update = False
    cfg.base_dir = str(_TMP / "downloads")
    return cfg


# ══════════════════════════════════════════════════════════════════
# Utilitários
# ══════════════════════════════════════════════════════════════════

@teste("utilitários de formatação")
def t_utils():
    assert m.detect_site("https://youtu.be/abc") == "YouTube"
    assert m.detect_site("https://www.tiktok.com/@x/video/1") == "TikTok"
    assert m.detect_site("https://sitedesconhecido.com/v/1") == "Outros"
    assert m.sanitize_name('a<b>:c/"d"') == "abcd"
    assert m.human_size(1536) == "1.5 KB"
    assert m.human_size(None) == "—"
    assert m.fmt_eta(75) == "1m15s"
    assert m.fmt_eta(None) == "—"
    assert m.fmt_duration(3725) == "1:02:05"
    assert m.fmt_duration(None) == "—"
    assert m.versao_tupla("2026.07.04") == m.versao_tupla("2026.7.4")


# ══════════════════════════════════════════════════════════════════
# Shorts
# ══════════════════════════════════════════════════════════════════

@teste("Shorts: resolve sem rede o que dá")
def t_shorts_offline():
    entradas = [
        {"id": "a", "url": "https://www.youtube.com/shorts/a", "title": "s", "duration": None},
        {"id": "b", "url": "https://www.youtube.com/watch?v=b", "title": "v", "duration": 2000},
    ]
    videos, shorts = m.separar_shorts(entradas)
    assert [e["id"] for e in videos] == ["b"]
    assert [e["id"] for e in shorts] == ["a"]
    assert m.fonte_de_shorts("https://www.youtube.com/shorts/x")
    assert m.fonte_de_shorts("https://www.youtube.com/@canal/shorts")
    assert not m.fonte_de_shorts("https://www.youtube.com/@canal")


@teste("Shorts: canal real sem Shorts na fila", rede=True)
def t_shorts_rede():
    cfg = _cfg()
    canal = "https://www.youtube.com/@veritasium"
    resumo = m.resumir_info(canal, m.fetch_info(canal, cfg))
    assert resumo["kind"] == "canal", resumo["kind"]
    expandido = m.expandir_canal(resumo, cfg, ignorar_shorts=True, ignorar_lives=True)
    assert len(expandido["entries"]) > 50
    assert not any(m.url_de_short(e["url"]) for e in expandido["entries"])
    aba = f"{canal}/shorts"
    shorts = m.resumir_info(aba, m.fetch_info(aba, cfg))
    assert all(m.url_de_short(e["url"]) for e in shorts["entries"])
    assert not (cfg.ignorar_shorts and not m.fonte_de_shorts(aba))


# ══════════════════════════════════════════════════════════════════
# Lives
# ══════════════════════════════════════════════════════════════════

@teste("lives: separação por live_status")
def t_lives():
    entradas = [
        {"id": "a", "live_status": None}, {"id": "b", "live_status": "is_live"},
        {"id": "c", "live_status": "is_upcoming"}, {"id": "d", "live_status": "was_live"},
        {"id": "e", "live_status": "post_live"}, {"id": "f", "live_status": "not_live"},
    ]
    normais, lives = m.separar_lives(entradas)
    assert [e["id"] for e in normais] == ["a", "f"]
    assert [e["id"] for e in lives] == ["b", "c", "d", "e"]
    assert m.filtro_sem_live({"live_status": "is_live"}) == "live ignorada"
    assert m.filtro_sem_live({"is_live": True}) == "live ignorada"
    assert m.filtro_sem_live({"live_status": "not_live"}) is None
    assert m.filtro_sem_live({"live_status": "is_live"}, incomplete=True)
    assert m.fonte_de_lives("https://www.youtube.com/@c/streams")
    assert not m.fonte_de_lives("https://www.youtube.com/@c")


@teste("lives: canal de notícias sem lives na fila", rede=True)
def t_lives_rede():
    cfg = _cfg()
    canal = "https://www.youtube.com/@SkyNews"
    resumo = m.resumir_info(canal, m.fetch_info(canal, cfg))
    sem = m.expandir_canal(resumo, cfg, ignorar_shorts=True, ignorar_lives=True)
    com = m.expandir_canal(resumo, cfg, ignorar_shorts=True, ignorar_lives=False)
    assert not [e for e in sem["entries"] if e.get("live_status")]
    assert [e for e in com["entries"] if e.get("live_status")]
    assert len(com["entries"]) > len(sem["entries"])


# ══════════════════════════════════════════════════════════════════
# Já baixados
# ══════════════════════════════════════════════════════════════════

@teste("já baixados: nome, registro e casos-limite")
def t_baixados():
    from yt_dlp.utils import sanitize_filename
    pasta = _TMP / "baixados"
    shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir(parents=True)
    entradas = [
        {"id": "aaa", "title": "Primeiro vídeo"},
        {"id": "bbb", "title": "Segundo: com / caracteres | ruins?"},
        {"id": "ccc", "title": "Terceiro vídeo"},
    ]
    novos, ja = m.separar_baixados(entradas, pasta, "video:best")
    assert len(novos) == 3 and not ja
    assert m.separar_baixados(entradas, pasta / "nao_existe", "video:best")[0]

    (pasta / "Primeiro vídeo [1920x1080].mkv").write_text("x")
    (pasta / f"{sanitize_filename(entradas[1]['title'])} [1280x720].mkv").write_text("x")
    novos, ja = m.separar_baixados(entradas, pasta, "video:best")
    assert {e["id"] for e in ja} == {"aaa", "bbb"}

    # registro por ID protege de mudança de título
    arquivo = pasta / "Terceiro vídeo [1920x1080].mkv"
    arquivo.write_text("x")
    m.registrar_baixado(pasta, "ccc", "video:best", str(arquivo), "Terceiro vídeo")
    renomeado = [{"id": "ccc", "title": "Terceiro vídeo (TÍTULO NOVO)"}]
    assert not m.separar_baixados(renomeado, pasta, "video:best")[0]
    arquivo.unlink()  # apagou -> volta a ser novo
    assert m.separar_baixados(renomeado, pasta, "video:best")[0]

    # áudio e vídeo contam separado
    assert len(m.separar_baixados(entradas, pasta, "audio")[0]) == 3
    (pasta / "Primeiro vídeo.mp3").write_text("x")
    assert [e["id"] for e in m.separar_baixados(entradas, pasta, "audio")[1]] == ["aaa"]

    # thumbnails e parciais não contam
    (pasta / "Quarto.webp").write_text("x")
    (pasta / "Quarto.mkv.part").write_text("x")
    assert len(m.separar_baixados([{"id": "d", "title": "Quarto"}], pasta, "video:best")[0]) == 1

    # registro corrompido não derruba
    (pasta / m.REGISTRO_ARQUIVO).write_text("{lixo")
    assert sum(len(x) for x in m.separar_baixados(entradas, pasta, "video:best")) == 3


# ══════════════════════════════════════════════════════════════════
# Cookies
# ══════════════════════════════════════════════════════════════════

@teste("cookies: diagnóstico do arquivo")
def t_cookies_resumo():
    base = _TMP / "cookies"
    base.mkdir(exist_ok=True)
    bom = base / "bom.txt"
    bom.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t"
                   f"{int(time.time()) + 30 * 86400}\tSID\tv\n")
    msg, estilo = m.resumo_cookies(str(bom))
    assert "Login ativo" in msg and estilo == "green", msg

    velho = base / "velho.txt"
    velho.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t1000\tSID\tv\n")
    assert m.resumo_cookies(str(velho))[1] == "red"

    assert "não encontrado" in m.resumo_cookies(str(base / "nada.txt"))[0]
    assert "não encontrado" in m.resumo_cookies("")[0]
    assert "não encontrado" in m.resumo_cookies(str(base))[0]  # é uma pasta

    sem_perm = base / "semperm.txt"
    sem_perm.write_text("# Netscape HTTP Cookie File\n")
    os.chmod(sem_perm, 0o000)
    try:
        if os.geteuid() != 0:  # root lê tudo
            assert "permissão" in m.resumo_cookies(str(sem_perm))[0].lower()
    finally:
        os.chmod(sem_perm, 0o644)


@teste("cookies: um download por vez, com backup")
def t_cookies_exclusividade():
    cfg = _cfg()
    arquivo = _TMP / "cookies" / "ativo.txt"
    arquivo.parent.mkdir(exist_ok=True)
    conteudo = ("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t"
                f"{int(time.time()) + 86400}\tSID\tv\n")
    arquivo.write_text(conteudo)
    cfg.cookies_file = str(arquivo)

    simultaneos = maximo = 0
    trava = threading.Lock()

    def usar():
        nonlocal simultaneos, maximo
        with m.sessao_cookies(cfg) as ck:
            assert ck.get("cookiefile")
            with trava:
                simultaneos += 1
                maximo = max(maximo, simultaneos)
            time.sleep(0.05)
            with trava:
                simultaneos -= 1

    fios = [threading.Thread(target=usar) for _ in range(8)]
    [f.start() for f in fios]
    [f.join() for f in fios]
    assert maximo == 1, f"{maximo} usos simultâneos corromperiam o arquivo"

    # app morto no meio da regravação -> restaura do backup
    with m.sessao_cookies(cfg):
        arquivo.write_text("LIXO")
    assert arquivo.read_text() == conteudo

    vazio = _cfg()
    with m.sessao_cookies(vazio) as ck:
        assert ck == {}
    assert not m.cookies_disponiveis(vazio)


# ══════════════════════════════════════════════════════════════════
# Erros e retentativas
# ══════════════════════════════════════════════════════════════════

@teste("erros: classificação com mensagens reais do yt-dlp")
def t_classificar():
    casos = [
        ("ERROR: [youtube] BaW_jenozKc: Video unavailable", False, "Indisponível"),
        ("ERROR: [generic] video: Unable to download webpage: [Errno -5] No address "
         "associated with hostname", True, "Sem conexão"),
        ("ERROR: [youtube] a: Join this channel to get access to members-only content",
         False, "Só p/ membros"),
        ("ERROR: [youtube] a: Private video. Sign in if you've been granted access",
         False, "Privado"),
        ("ERROR: [youtube] a: Sign in to confirm you're not a bot", False, "Bloqueio antirrobô"),
        ("ERROR: [youtube] a: This content isn't available, try again later. Your account "
         "has been rate-limited", False, "Limite do YouTube"),
        ("ERROR: [youtube] a: The uploader has not made this video available in your country",
         False, "Bloqueado no país"),
        ("ERROR: [youtube] a: This video has been removed by the uploader", False, "Removido"),
        ("ERROR: [youtube] a: Sign in to confirm your age", False, "Restrito por idade"),
        ("ERROR: unable to download video data: HTTP Error 503", True, "Erro do servidor"),
        ("ERROR: The read operation timed out", True, "Tempo esgotado"),
        ("ERROR: fragment 3 not found", True, "Fragmento perdido"),
        ("ERROR: mensagem nunca vista", True, "Falhou"),
    ]
    for msg, repetir_esperado, motivo_esperado in casos:
        repetir, motivo = m.classificar_erro(msg)
        assert repetir == repetir_esperado, f"{msg[:50]}: repetir={repetir}"
        assert motivo == motivo_esperado, f"{msg[:50]}: {motivo}"


class _FalsoYDL:
    """Substitui o yt-dlp: falha N vezes e depois "baixa"."""

    controle: dict = {}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def download(self, urls):
        c = _FalsoYDL.controle
        c["n"] = c.get("n", 0) + 1
        if c["n"] <= c.get("falhas", 0):
            raise Exception(c["mensagem"])
        for hook in self.opts.get("progress_hooks", []):
            hook({"status": "finished", "filename": c["arquivo"]})


async def _rodar_job(mensagem: str, falhas: int, **kwargs) -> tuple[Job, int, AVDownloaderApp]:
    app = AVDownloaderApp()
    app.config.auto_update = False
    app.config.cookies_file = "/nao/existe"
    app.config.base_dir = str(_TMP / "downloads")
    arquivo = _TMP / "downloads" / "falso.mp3"
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text("x")
    _FalsoYDL.controle = {"n": 0, "falhas": falhas, "mensagem": mensagem,
                          "arquivo": str(arquivo)}
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.pause()
        espera_real = m.ESPERA_TENTATIVA
        real = m.yt_dlp.YoutubeDL
        m.ESPERA_TENTATIVA = (0.3, 0.3, 0.3)
        m.yt_dlp.YoutubeDL = _FalsoYDL
        try:
            job = Job(url="u", title="Item", site="YouTube", fmt="audio",
                      dest_dir=str(arquivo.parent), video_id="v1", **kwargs)
            app.jobs[job.id] = job
            app.query_one("#queue").add_row("Item", "", "", "", "", "", "", key=str(job.id))
            app.run_worker(lambda: app._download_worker(job), thread=True, group="downloads")
            inicio = time.monotonic()
            while job.status not in Status.FINAIS:
                if time.monotonic() - inicio > 40:
                    raise TimeoutError(f"travou em {job.status[1]}")
                await pilot.pause(0.2)
        finally:
            m.yt_dlp.YoutubeDL = real
            m.ESPERA_TENTATIVA = espera_real
        return job, _FalsoYDL.controle["n"], app


@teste("erros: falha passageira volta para a fila sozinha")
def t_retry_transitorio():
    job, tentativas, _ = asyncio.run(_rodar_job("Connection reset by peer", falhas=2))
    assert job.status is Status.DONE, job.status
    assert tentativas == 3, tentativas


@teste("erros: falha persistente para no limite de tentativas")
def t_retry_limite():
    job, tentativas, _ = asyncio.run(_rodar_job("Connection reset by peer", falhas=99))
    assert job.status is Status.ERROR
    assert tentativas == m.MAX_TENTATIVAS + 1, tentativas
    assert job.motivo == "Falha de rede"
    assert "Falha de rede" in str(AVDownloaderApp._celula_status(job))


@teste("erros: vídeo de membros não é repetido")
def t_retry_membros():
    job, tentativas, _ = asyncio.run(_rodar_job(
        "Join this channel to get access to members-only content", falhas=99))
    assert tentativas == 1, f"tentou {tentativas} vezes"
    assert job.motivo == "Só p/ membros"
    assert "Só p/ membros" in str(AVDownloaderApp._celula_status(job))


@teste("erros: live não detectada vira 'ignorada', não erro")
def t_live_ignorada():
    class SemDownload(_FalsoYDL):
        def download(self, urls):
            assert self.opts.get("match_filter") is m.filtro_sem_live
            return 0  # o filtro recusou: nada baixado

    async def fluxo():
        app = AVDownloaderApp()
        app.config.auto_update = False
        async with app.run_test(size=(110, 36)) as pilot:
            await pilot.pause()
            real = m.yt_dlp.YoutubeDL
            m.yt_dlp.YoutubeDL = SemDownload
            try:
                job = Job(url="u", title="Live", site="YouTube", fmt="video:best",
                          dest_dir=str(_TMP / "downloads"), bloquear_live=True)
                app.jobs[job.id] = job
                app.query_one("#queue").add_row("Live", "", "", "", "", "", "", key=str(job.id))
                app.run_worker(lambda: app._download_worker(job), thread=True, group="downloads")
                inicio = time.monotonic()
                while job.status not in Status.FINAIS:
                    if time.monotonic() - inicio > 30:
                        raise TimeoutError(job.status[1])
                    await pilot.pause(0.2)
            finally:
                m.yt_dlp.YoutubeDL = real
            assert job.status is Status.IGNORED, job.status

    asyncio.run(fluxo())


@teste("erros: tecla R repete só o que vale a pena")
def t_repetir_erros():
    async def fluxo():
        app = AVDownloaderApp()
        app.config.auto_update = False
        async with app.run_test(size=(110, 36)) as pilot:
            await pilot.pause()
            real = m.yt_dlp.YoutubeDL
            m.yt_dlp.YoutubeDL = _FalsoYDL
            _FalsoYDL.controle = {"n": 0, "falhas": 0, "mensagem": "",
                                  "arquivo": str(_TMP / "downloads" / "falso.mp3")}
            try:
                jobs = []
                for i, erro in enumerate([
                    "Connection reset by peer", "HTTP Error 503",
                    "Join this channel to get access to members-only content",
                    "Video unavailable",
                ]):
                    j = Job(url=f"u{i}", title=f"V{i}", site="YouTube", fmt="audio",
                            dest_dir=str(_TMP / "downloads"))
                    j.status, j.error = Status.ERROR, erro
                    j.motivo = m.classificar_erro(erro)[1]
                    app.jobs[j.id] = j
                    app.query_one("#queue").add_row(f"V{i}", "", "", "", "", "", "",
                                                    key=str(j.id))
                    jobs.append(j)
                await pilot.press("escape")
                await pilot.press("R")
                await pilot.pause()
                mantidos = [j for j in jobs if j.status is Status.ERROR]
                assert len(jobs) - len(mantidos) == 2, [j.status[1] for j in jobs]
                assert {j.motivo for j in mantidos} == {"Só p/ membros", "Indisponível"}
            finally:
                m.yt_dlp.YoutubeDL = real

    asyncio.run(fluxo())


# ══════════════════════════════════════════════════════════════════
# Interface
# ══════════════════════════════════════════════════════════════════

@teste("interface: telas, atalhos e configurações")
def t_ui():
    async def fluxo():
        app = AVDownloaderApp()
        app.config.auto_update = False
        async with app.run_test(size=(110, 38)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            for tecla, tela in [("question_mark", "HelpScreen"), ("h", "HistoryScreen")]:
                await pilot.press(tecla)
                await pilot.pause()
                assert tela in str(type(app.screen)), (tecla, type(app.screen))
                await pilot.press("escape")
                await pilot.pause()

            await pilot.press("s")
            await pilot.pause()
            assert "SettingsScreen" in str(type(app.screen))
            for campo in ("#cfg-shorts", "#cfg-lives", "#cfg-autoupdate",
                          "#cfg-cookies-modo", "#cfg-dir"):
                assert app.screen.query_one(campo)
            app.screen.query_one("#cfg-lives").value = False
            await pilot.click("#btn-salvar")
            await pilot.pause()
            assert app.config.ignorar_lives is False
            assert json.loads(m.CONFIG_FILE.read_text())["ignorar_lives"] is False
            # Devolve o padrão para não influenciar os testes seguintes
            await pilot.press("s")
            await pilot.pause()
            app.screen.query_one("#cfg-lives").value = True
            await pilot.click("#btn-salvar")
            await pilot.pause()

            tema = app.theme
            await pilot.press("t")
            await pilot.pause()
            assert app.theme != tema and app.theme in m.THEMES
            await pilot.press("q")
            await pilot.pause()

    asyncio.run(fluxo())


@teste("interface: nenhum modal esconde seus botões")
def t_layout():
    from main import (AddDownloadScreen, ConfirmScreen, HelpScreen,
                      HistoryScreen, SettingsScreen)

    m.HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    m.HISTORY_FILE.write_text(json.dumps([
        {"data": "20/07/2026 09:00", "titulo": f"Vídeo {n} com título longo",
         "site": "YouTube", "formato": "Melhor", "tamanho": "1.2 GB", "bytes": 1}
        for n in range(60)
    ]))
    resumo = {
        "kind": "playlist", "url": "https://www.youtube.com/watch?v=a&list=PL1",
        "site": "YouTube", "title": "Canal com nome longo para forçar quebra",
        "uploader": "Fulano", "shorts_ignorados": 37, "lives_ignoradas": 12,
        "entries": [{"id": f"i{n}", "url": "u", "title": "t", "duration": 100}
                    for n in range(500)],
    }

    def _sem_rede(*a, **k):  # o modal é preenchido à mão logo abaixo
        raise RuntimeError("teste de layout não consulta a rede")

    async def fluxo(tamanho):
        falhas = []
        app = AVDownloaderApp()
        app.config.auto_update = False
        async with app.run_test(size=tamanho) as pilot:
            await pilot.pause()
            telas = [
                ("Confirm", ConfirmScreen("Mensagem\nem duas linhas"), "#btn-sim"),
                ("Add", AddDownloadScreen(resumo["url"], app.config), "#btn-ok"),
                ("Settings", SettingsScreen(app.config), "#btn-salvar"),
                ("History", HistoryScreen(), "#btn-fechar"),
                ("Help", HelpScreen(), "#btn-fechar"),
            ]
            for nome, tela, alvo in telas:
                app.push_screen(tela)
                await pilot.pause()
                if nome == "Add":
                    tela._mostrar_info(resumo)
                    await pilot.pause()
                await pilot.pause()
                r = app.screen.query_one(alvo).region
                if r.y + r.height > tamanho[1] or r.y < 0:
                    falhas.append(f"{nome} fora da tela {tamanho}")
                try:
                    await pilot.click(alvo)
                except Exception as exc:
                    falhas.append(f"{nome} não clicável ({type(exc).__name__})")
                await pilot.pause()
                if app.screen is tela:
                    app.pop_screen()
                    await pilot.pause()
        return falhas

    fetch_real = m.fetch_info
    m.fetch_info = _sem_rede
    try:
        todas = []
        for tamanho in [(120, 45), (110, 36), (100, 30), (80, 24), (60, 24), (80, 20)]:
            todas += asyncio.run(fluxo(tamanho))
    finally:
        m.fetch_info = fetch_real
    assert not todas, todas


@teste("interface: canal real vira fila sem Shorts nem lives", rede=True)
def t_fluxo_completo():
    async def fluxo():
        app = AVDownloaderApp()
        app.config.auto_update = False
        app.config.base_dir = str(_TMP / "downloads_canal")
        # Explícito: não depende do que outro teste tenha salvo na configuração
        app.config.ignorar_lives = True
        app.config.ignorar_shorts = True
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.query_one("#url-input").value = "https://www.youtube.com/@SkyNews"
            await pilot.press("enter")
            await pilot.pause()
            botao = app.screen.query_one("#btn-ok")
            inicio = time.monotonic()
            while botao.disabled:
                if time.monotonic() - inicio > 300:
                    raise TimeoutError("análise não terminou")
                await pilot.pause(0.5)
            info = str(app.screen.query_one("#add-info").render())
            assert "Lives" in info and "ignoradas" in info, info
            assert "Shorts" in info, info
            await pilot.click("#btn-ok")
            await pilot.pause()
            assert app.jobs
            assert all(j.bloquear_live for j in app.jobs.values())
            for job in app.jobs.values():
                job.cancel.set()
            await pilot.pause()

    asyncio.run(fluxo())


@teste("ciclo real: baixa, registra e detecta na segunda vez", rede=True)
def t_ciclo():
    url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # 19 segundos
    base = _TMP / "ciclo"
    shutil.rmtree(base, ignore_errors=True)

    async def baixar():
        app = AVDownloaderApp()
        app.config.auto_update = False
        app.config.base_dir = str(base)
        async with app.run_test(size=(110, 36)) as pilot:
            await pilot.pause()
            app.query_one("#url-input").value = url
            await pilot.press("enter")
            await pilot.pause()
            botao = app.screen.query_one("#btn-ok")
            inicio = time.monotonic()
            while botao.disabled:
                if time.monotonic() - inicio > 120:
                    raise TimeoutError("análise")
                await pilot.pause(0.5)
            await pilot.click("#btn-ok")
            await pilot.pause()
            job = next(iter(app.jobs.values()))
            inicio = time.monotonic()
            while job.status not in Status.FINAIS:
                if time.monotonic() - inicio > 180:
                    raise TimeoutError("download")
                await pilot.pause(0.5)
            assert job.status in (Status.DONE, Status.WARN), job.error
            return job

    async def reabrir():
        app = AVDownloaderApp()
        app.config.auto_update = False
        app.config.base_dir = str(base)
        async with app.run_test(size=(110, 36)) as pilot:
            await pilot.pause()
            app.query_one("#url-input").value = url
            await pilot.press("enter")
            await pilot.pause()
            tela = app.screen
            inicio = time.monotonic()
            while tela.query_one("#add-info").display is False:
                if time.monotonic() - inicio > 120:
                    raise TimeoutError("análise")
                await pilot.pause(0.5)
            await pilot.pause()
            assert "Já tenho" in str(tela.query_one("#add-info").render())
            assert "de novo" in str(tela.query_one("#btn-ok").label)
            tela.query_one("#add-fmt").value = "audio"  # MP3 ainda não existe
            await pilot.pause()
            assert "Já tenho" not in str(tela.query_one("#add-info").render())

    job = asyncio.run(baixar())
    registro = m.carregar_registro(job.dest_dir)
    assert "jNQXAC9IVRw:video" in registro, registro
    asyncio.run(reabrir())
    shutil.rmtree(base, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════

def main() -> int:
    so_rapidos = "rapidos" in sys.argv or "rápidos" in sys.argv
    testes = [v for v in globals().values() if callable(v) and hasattr(v, "_nome")]
    if so_rapidos:
        testes = [t for t in testes if not t._rede]

    print(f"\n{len(testes)} testes" + (" (só os rápidos)" if so_rapidos else "") + "\n")
    falhas = 0
    for func in testes:
        etiqueta = "rede" if func._rede else "    "
        print(f"  [{etiqueta}] {func._nome:<48}", end="", flush=True)
        inicio = time.monotonic()
        try:
            func()
            print(f"{VERDE}ok{FIM} ({time.monotonic() - inicio:.1f}s)")
        except Exception as exc:
            falhas += 1
            print(f"{VERM}FALHOU{FIM} ({type(exc).__name__}: {str(exc)[:90]})")

    shutil.rmtree(_TMP, ignore_errors=True)
    if falhas:
        print(f"\n{VERM}{falhas} de {len(testes)} falharam{FIM}\n")
        return 1
    print(f"\n{VERDE}todos os {len(testes)} passaram{FIM}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
