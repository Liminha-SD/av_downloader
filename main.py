#!/usr/bin/env python3
"""AV Downloader — TUI elegante para baixar vídeos e músicas na melhor qualidade.

Sucessor do downloader.sh: fila com downloads paralelos, progresso em tempo
real, histórico e configurações persistentes. Funciona no Termux e no desktop.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


def _ensure_venv() -> None:
    """Se não estivermos no python da venv, re-executa com ele."""
    here = Path(__file__).resolve().parent
    venv_dir = here / "venv"
    venv_py = venv_dir / "bin" / "python"
    if venv_py.is_file() and Path(sys.prefix).resolve() != venv_dir.resolve():
        os.execv(str(venv_py), [str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]])


_ensure_venv()

try:
    import yt_dlp
    from yt_dlp.utils import sanitize_filename
    from rich.text import Text
    from textual import on
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Horizontal, Vertical, VerticalScroll
    from textual.coordinate import Coordinate
    from textual.screen import ModalScreen
    from textual.theme import Theme
    from textual.worker import get_current_worker
    from textual.widgets import (
        Button,
        DataTable,
        Footer,
        Header,
        Input,
        Label,
        LoadingIndicator,
        Select,
        Static,
        Switch,
    )
except ModuleNotFoundError as exc:
    print(f"[!] Dependência ausente: {exc.name}")
    print("    Instale com:  pip install -U yt-dlp textual")
    print("    (No Termux, antes rode:  pkg install python ffmpeg)")
    sys.exit(1)

APP_NAME = "AV Downloader"
VERSION = "3.0"

IS_TERMUX = "com.termux" in os.environ.get("PREFIX", "") or Path("/data/data/com.termux").exists()

CONFIG_DIR = Path.home() / ".config" / "av-downloader"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "historico.json"
COOKIES_BACKUP = CONFIG_DIR / "cookies-backup.txt"

# Cookies de login do YouTube/Google (aparecem no cookies.txt exportado)
COOKIES_LOGIN = {
    "SID", "HSID", "SSID", "APISID", "SAPISID",
    "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO",
}

THEMES = [
    "luna",
    "tokyo-night",
    "catppuccin-mocha",
    "dracula",
    "nord",
    "gruvbox",
    "monokai",
    "flexoki",
    "textual-dark",
]

# Tema padrão: paleta do BRIEFING.md (identidade visual dos programas)
LUNA_THEME = Theme(
    name="luna",
    primary="#019DEA",
    secondary="#007ACC",
    accent="#00B4FF",
    foreground="#FFFFFF",
    background="#0F0F0F",
    surface="#121212",
    panel="#202020",
    error="#FF6666",
    dark=True,
)

MAX_PLAYLIST_ITEMS = 500

# Shorts têm no máximo 3 minutos: acima disso não há o que checar.
SHORTS_MAX_DURACAO = 180
SHORTS_CHECK_WORKERS = 8

# Registro do que já foi baixado, guardado dentro da própria pasta de destino
REGISTRO_ARQUIVO = ".avd-baixados.json"
EXTS_AUDIO = {".mp3", ".m4a", ".opus", ".ogg", ".oga", ".flac", ".wav", ".aac"}
EXTS_VIDEO = {".mkv", ".mp4", ".webm", ".mov", ".avi", ".flv", ".ts", ".m4v"}

BANNER = "▄▀█ █░█ · █▀▄ █░░\n█▀█ ░▀░ · █▄▀ █▄▄"
TAGLINE = "vídeos & músicas · melhor qualidade sempre"

_SITE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("YouTube", ("youtube.com", "youtu.be", "music.youtube")),
    ("TikTok", ("tiktok.com",)),
    ("Instagram", ("instagram.com", "instagr.am")),
    ("Twitter", ("twitter.com", "x.com", "t.co")),
    ("Facebook", ("facebook.com", "fb.watch")),
    ("Twitch", ("twitch.tv",)),
    ("Pinterest", ("pinterest.", "pin.it")),
    ("Reddit", ("reddit.com", "redd.it")),
    ("Vimeo", ("vimeo.com",)),
    ("SoundCloud", ("soundcloud.com",)),
]


# ══════════════════════════════════════════════════════════════════
# Utilitários
# ══════════════════════════════════════════════════════════════════

def default_base_dir() -> str:
    if IS_TERMUX:
        return "/sdcard/Download/av-downloader"
    return str(Path.home() / "Downloads" / "av-downloader")


def detect_site(url: str) -> str:
    low = url.lower()
    for nome, dominios in _SITE_PATTERNS:
        if any(d in low for d in dominios):
            return nome
    return "Outros"


def sanitize_name(nome: str) -> str:
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", nome)
    nome = re.sub(r"\s+", " ", nome).strip()
    return nome[:80] or "Sem nome"


def human_size(num: float | None) -> str:
    if not num:
        return "—"
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.1f} {unidade}"
        num /= 1024
    return f"{num:.1f} PB"


def human_speed(bps: float | None) -> str:
    return f"{human_size(bps)}/s" if bps else "—"


def fmt_eta(segundos: float | None) -> str:
    if segundos is None or segundos < 0:
        return "—"
    s = int(segundos)
    if s >= 3600:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    if s >= 60:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s}s"


def fmt_duration(segundos) -> str:
    try:
        s = int(segundos)
    except (TypeError, ValueError):
        return "—"
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


# ── Identificação de Shorts do YouTube ────────────────────────────
#
# Na aba /shorts as URLs já vêm marcadas, mas em playlists (inclusive a de
# uploads do canal) os Shorts aparecem como "watch?v=" normais. A duração
# também não basta: desde 2024 um Short pode ter até 3 minutos. A fonte
# confiável é a própria URL de Short: youtube.com/shorts/<id> responde 200
# quando é Short e redireciona (303) quando é vídeo comum.


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def url_de_short(url: str) -> bool:
    return "/shorts/" in (url or "")


def _consultar_short(video_id: str) -> bool:
    opener = build_opener(_SemRedirect)
    opener.addheaders = [("User-Agent", "Mozilla/5.0")]
    req = Request(f"https://www.youtube.com/shorts/{video_id}", method="HEAD")
    try:
        return opener.open(req, timeout=8).status == 200
    except HTTPError as exc:
        return exc.code == 200
    except Exception:
        return False  # na dúvida, trata como vídeo comum (não descarta nada)


def separar_shorts(entries: list[dict], progresso=None) -> tuple[list[dict], list[dict]]:
    """Divide as entradas em (vídeos, shorts).

    Resolve o que dá de graça (URL de Short, duração acima do limite) e só
    consulta a rede para os casos ambíguos, em paralelo.
    """
    videos: list[dict] = []
    shorts: list[dict] = []
    duvidosos: list[dict] = []

    for item in entries:
        duracao = item.get("duration")
        if url_de_short(item.get("url", "")):
            shorts.append(item)
        elif duracao is not None and duracao > SHORTS_MAX_DURACAO:
            videos.append(item)
        elif item.get("id"):
            duvidosos.append(item)
        else:
            videos.append(item)

    if duvidosos:
        if progresso:
            progresso(len(duvidosos))
        with ThreadPoolExecutor(max_workers=SHORTS_CHECK_WORKERS) as pool:
            resultados = list(pool.map(lambda i: _consultar_short(i["id"]), duvidosos))
        for item, e_short in zip(duvidosos, resultados):
            (shorts if e_short else videos).append(item)

    # Preserva a ordem original da playlist
    ordem = {id(item): pos for pos, item in enumerate(entries)}
    videos.sort(key=lambda i: ordem[id(i)])
    shorts.sort(key=lambda i: ordem[id(i)])
    return videos, shorts


# ── Identificação de lives ────────────────────────────────────────
#
# Aqui o yt-dlp entrega tudo de graça na listagem: "is_live" (no ar),
# "is_upcoming" (agendada) e "was_live" (gravação de uma live encerrada).
# Nos canais, as lives ficam numa aba própria, separada da aba Videos.

LIVE_STATUS = {"is_live", "is_upcoming", "was_live", "post_live"}


def entrada_e_live(item: dict) -> bool:
    return str(item.get("live_status") or "") in LIVE_STATUS


def filtro_sem_live(info: dict, *, incomplete: bool = False) -> str | None:
    """Rede de segurança do yt-dlp: recusa lives já na extração completa.

    Protege do caso em que a listagem não marcou o item (uma transmissão que
    começou depois) — sem isso, o download de uma live só terminaria quando a
    transmissão acabasse, travando a vaga na fila.
    """
    if str(info.get("live_status") or "") in LIVE_STATUS or info.get("is_live"):
        return "live ignorada"
    return None


def separar_lives(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """Divide as entradas em (vídeos normais, lives)."""
    normais, lives = [], []
    for item in entries:
        (lives if entrada_e_live(item) else normais).append(item)
    return normais, lives


def versao_tupla(versao: str) -> tuple[int, ...]:
    """Compara versões numericamente: "2026.07.04" == "2026.7.4" (PEP 440)."""
    return tuple(int(p) for p in re.findall(r"\d+", versao))


def cookies_validos(caminho: str) -> bool:
    try:
        p = Path(caminho).expanduser()
        if not p.is_file():
            return False
        inicio = p.read_text(errors="ignore")[:2048]
        return "Netscape" in inicio or "cookiestxt" in inicio or "\t" in inicio
    except OSError:
        return False


def resumo_cookies(caminho: str) -> tuple[str, str]:
    """(mensagem, estilo) sobre o estado do arquivo de cookies."""
    arquivo = Path(caminho).expanduser()
    if not arquivo.is_file():
        return "Cookies inativos (arquivo não encontrado)", "dim"
    try:
        linhas = arquivo.read_text(errors="ignore").splitlines()
    except PermissionError:
        if IS_TERMUX:
            return "Sem permissão — rode: termux-setup-storage", "red"
        return "Sem permissão para ler o arquivo", "red"
    except OSError as exc:
        return f"Erro ao ler o arquivo: {exc.strerror or exc}", "red"

    total = 0
    validades: list[float] = []
    for linha in linhas:
        if linha.startswith("#") or not linha.strip():
            continue
        partes = linha.split("\t")
        if len(partes) < 7:
            continue
        dominio, expira, nome = partes[0], partes[4], partes[5]
        if "youtube" not in dominio and "google" not in dominio:
            continue
        total += 1
        if nome in COOKIES_LOGIN:
            try:
                validades.append(float(expira))
            except ValueError:
                pass

    if not total:
        return "Arquivo sem cookies do YouTube — exporte de novo", "yellow"
    if not validades:
        return f"{total} cookies do YouTube, mas sem login", "yellow"

    futuras = [v for v in validades if v > 0]
    if futuras and min(futuras) < time.time():
        return "Login expirado — exporte os cookies de novo", "red"
    if futuras:
        dias = int((min(futuras) - time.time()) // 86400)
        return f"Login ativo · {total} cookies · expira em {dias} dias", "green"
    return f"Login ativo · {total} cookies (sessão)", "green"


def abrir_no_sistema(caminho: str) -> bool:
    for opener in (["termux-open"], ["xdg-open"], ["open"]):
        if shutil.which(opener[0]):
            subprocess.Popen(
                opener + [caminho],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
    return False


def ler_clipboard() -> str | None:
    comandos = (
        ["termux-clipboard-get"],
        ["wl-paste", "-n"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "-b"],
    )
    for cmd in comandos:
        if shutil.which(cmd[0]):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                if out.returncode == 0 and out.stdout.strip():
                    return out.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                continue
    return None


# ══════════════════════════════════════════════════════════════════
# Configuração e histórico
# ══════════════════════════════════════════════════════════════════

@dataclass
class Config:
    base_dir: str = field(default_factory=default_base_dir)
    cookies_file: str = str(
        Path("~/storage/downloads/cookies.txt" if IS_TERMUX else "~/cookies.txt").expanduser()
    )
    cookies_modo: str = "arquivo"  # "arquivo" | "firefox"
    max_concurrent: int = 2
    audio_quality: str = "320"
    embed_thumbnail: bool = True
    embed_metadata: bool = True
    ignorar_shorts: bool = True
    ignorar_lives: bool = True
    auto_update: bool = True
    theme: str = THEMES[0]

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        try:
            dados = json.loads(CONFIG_FILE.read_text())
            for chave, valor in dados.items():
                if hasattr(cfg, chave):
                    setattr(cfg, chave, valor)
        except (OSError, json.JSONDecodeError):
            pass
        return cfg

    def save(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(self.__dict__, indent=2, ensure_ascii=False))
        except OSError:
            pass

    # Subpastas de destino
    @property
    def dir_videos(self) -> Path:
        return Path(self.base_dir) / "videos"

    @property
    def dir_musicas(self) -> Path:
        return Path(self.base_dir) / "musicas"

    @property
    def dir_playlists(self) -> Path:
        return Path(self.base_dir) / "playlists"


_history_lock = threading.Lock()


def load_history() -> list[dict]:
    try:
        return json.loads(HISTORY_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return []


def append_history(entrada: dict) -> None:
    with _history_lock:
        historico = load_history()
        historico.insert(0, entrada)
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            HISTORY_FILE.write_text(json.dumps(historico[:1000], indent=2, ensure_ascii=False))
        except OSError:
            pass


def clear_history() -> None:
    with _history_lock:
        try:
            HISTORY_FILE.write_text("[]")
        except OSError:
            pass


# ══════════════════════════════════════════════════════════════════
# Registro de downloads já feitos
# ══════════════════════════════════════════════════════════════════
#
# O registro fica dentro da pasta de destino: acompanha os arquivos se a
# pasta for movida e some junto se ela for apagada. Um item só conta como
# baixado se o arquivo ainda estiver lá — apagou, baixa de novo. Arquivos
# antigos (sem registro) são reconhecidos pelo nome.

_registro_lock = threading.Lock()


def tipo_do_formato(fmt: str) -> str:
    return "audio" if fmt == "audio" else "video"


def chave_registro(video_id: str, fmt: str) -> str:
    return f"{video_id}:{tipo_do_formato(fmt)}"


def carregar_registro(pasta: Path | str) -> dict:
    try:
        dados = json.loads((Path(pasta) / REGISTRO_ARQUIVO).read_text())
        itens = dados.get("itens")
        return itens if isinstance(itens, dict) else {}
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}


def registrar_baixado(pasta: Path | str, video_id: str, fmt: str, arquivo: str, titulo: str) -> None:
    if not video_id or not arquivo:
        return
    pasta = Path(pasta)
    with _registro_lock:
        itens = carregar_registro(pasta)
        itens[chave_registro(video_id, fmt)] = {
            "arquivo": Path(arquivo).name,
            "titulo": titulo,
            "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        }
        try:
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / REGISTRO_ARQUIVO).write_text(
                json.dumps({"versao": 1, "itens": itens}, indent=2, ensure_ascii=False)
            )
        except OSError:
            pass


def _estado_da_pasta(pasta: Path | str, fmt: str) -> tuple[set[str], set[str]]:
    """Lê a pasta e devolve (chaves já baixadas, nomes de arquivo existentes)."""
    tipo = tipo_do_formato(fmt)
    extensoes = EXTS_AUDIO if tipo == "audio" else EXTS_VIDEO

    arquivos: set[str] = set()
    try:
        for item in Path(pasta).iterdir():
            if item.is_file() and item.suffix.lower() in extensoes:
                arquivos.add(item.name)
    except OSError:
        return set(), set()  # pasta ainda não existe

    nomes: set[str] = set()
    for arquivo in arquivos:
        stem = Path(arquivo).stem
        nomes.add(stem)
        # "Título [1920x1080]" -> "Título" (sufixo do modelo de nome)
        nomes.add(re.sub(r"\s*\[[^\[\]]*\]$", "", stem))

    registro = carregar_registro(pasta)
    chaves = {
        chave
        for chave, dado in registro.items()
        if chave.endswith(f":{tipo}") and isinstance(dado, dict) and dado.get("arquivo") in arquivos
    }
    return chaves, nomes


def separar_baixados(entries: list[dict], pasta: Path | str, fmt: str) -> tuple[list[dict], list[dict]]:
    """Divide as entradas em (ainda não baixadas, já baixadas)."""
    chaves, nomes = _estado_da_pasta(pasta, fmt)
    if not chaves and not nomes:
        return list(entries), []

    novos: list[dict] = []
    baixados: list[dict] = []
    for item in entries:
        video_id = item.get("id") or ""
        titulo = sanitize_filename(item.get("title") or "")
        if (video_id and chave_registro(video_id, fmt) in chaves) or (titulo and titulo in nomes):
            baixados.append(item)
        else:
            novos.append(item)
    return novos, baixados


# ══════════════════════════════════════════════════════════════════
# Modelo de download
# ══════════════════════════════════════════════════════════════════

class JobCancelled(Exception):
    pass


# ── Classificação de erros ────────────────────────────────────────
#
# Boa parte das falhas é passageira (rede, limite momentâneo, fragmento
# perdido) e some ao tentar de novo — é o que acontece quando se cola o link
# manualmente outra vez. Outras não adiantam repetir: vídeo de membros,
# privado, removido ou bloqueado no país. Só as primeiras são reagendadas.

MAX_TENTATIVAS = 3
ESPERA_TENTATIVA = (5, 20, 60)  # segundos entre tentativas

_ERROS_DEFINITIVOS: list[tuple[str, str]] = [
    ("join this channel", "Só p/ membros"),
    ("members-only", "Só p/ membros"),
    ("members only", "Só p/ membros"),
    ("private video", "Privado"),
    ("this video is private", "Privado"),
    ("video unavailable", "Indisponível"),
    ("has been removed", "Removido"),
    ("removed by the uploader", "Removido"),
    ("account associated with this video has been terminated", "Canal encerrado"),
    ("not made this video available in your country", "Bloqueado no país"),
    ("blocked it on copyright grounds", "Direitos autorais"),
    ("who has blocked it", "Direitos autorais"),
    ("this video may be inappropriate", "Restrito por idade"),
    ("confirm your age", "Restrito por idade"),
    ("sign in to confirm your age", "Restrito por idade"),
    ("is not available in your country", "Bloqueado no país"),
    ("premium", "Só p/ assinantes"),
    ("purchase", "Precisa comprar"),
    ("drm", "Protegido (DRM)"),
]

# Vale repetir, mas não agora: o próprio YouTube diz para esperar
_ERROS_ESPERAR: list[tuple[str, str]] = [
    ("rate-limited", "Limite do YouTube"),
    ("try again later", "Limite do YouTube"),
    ("too many requests", "Limite do YouTube"),
    ("not a bot", "Bloqueio antirrobô"),
    ("captcha", "Bloqueio antirrobô"),
]


def classificar_erro(mensagem: str) -> tuple[bool, str]:
    """(vale repetir?, motivo curto) a partir da mensagem do yt-dlp."""
    texto = (mensagem or "").lower()
    for marca, rotulo in _ERROS_DEFINITIVOS:
        if marca in texto:
            return False, rotulo
    for marca, rotulo in _ERROS_ESPERAR:
        if marca in texto:
            return False, rotulo
    if "no address associated" in texto or "unable to download webpage" in texto:
        return True, "Sem conexão"
    if "timed out" in texto or "timeout" in texto:
        return True, "Tempo esgotado"
    if "connection" in texto or "network" in texto or "temporary failure" in texto:
        return True, "Falha de rede"
    if "http error 5" in texto or "server" in texto:
        return True, "Erro do servidor"
    if "fragment" in texto:
        return True, "Fragmento perdido"
    return True, "Falhou"  # desconhecido: vale a pena repetir


class Status:
    QUEUED = ("○", "Na fila", "dim")
    DOWNLOADING = ("↓", "Baixando", "bold #019DEA")
    COOKIES = ("↻", "Com cookies", "bold yellow")
    CONVERTING = ("~", "Processando", "bold yellow")
    DONE = ("✓", "Concluído", "bold green")
    WARN = ("✓", "Concluído*", "yellow")
    RETRY = ("↻", "Nova tentativa", "yellow")
    ERROR = ("✗", "Erro", "bold red")
    CANCELLED = ("⊘", "Cancelado", "dim")
    IGNORED = ("⊘", "Live ignorada", "dim")

    FINAIS = (DONE, WARN, ERROR, CANCELLED, IGNORED)
    ATIVOS = (QUEUED, DOWNLOADING, COOKIES, CONVERTING, RETRY)


_job_ids = itertools.count(1)


@dataclass
class Job:
    url: str
    title: str
    site: str
    fmt: str  # "video:best" | "video:1080" | ... | "audio"
    dest_dir: str
    video_id: str = ""
    bloquear_live: bool = False
    usar_cookies: bool = False
    tentou_cookies: bool = False
    tentativas: int = 0
    motivo: str = ""
    id: int = field(default_factory=lambda: next(_job_ids))
    status: tuple = Status.QUEUED
    progress: float = 0.0
    speed: float | None = None
    eta: float | None = None
    total_bytes: float | None = None
    filepath: str | None = None
    error: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)
    _last_ui: float = 0.0

    @property
    def fmt_label(self) -> str:
        if self.fmt == "audio":
            return "MP3"
        qualidade = self.fmt.split(":")[1]
        return "Melhor" if qualidade == "best" else f"{qualidade}p"


def build_ydl_opts(job: Job, cfg: Config, hook, pp_hook, cookies: dict | None = None) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,
        "socket_timeout": 20,
        "progress_hooks": [hook],
        "postprocessor_hooks": [pp_hook],
        **({"match_filter": filtro_sem_live} if job.bloquear_live else {}),
        **(cookies or {}),
    }

    pps: list[dict] = []
    if job.fmt == "audio":
        opts["format"] = "bestaudio/best"
        opts["outtmpl"] = str(Path(job.dest_dir) / "%(title)s.%(ext)s")
        pps.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": cfg.audio_quality,
        })
    else:
        qualidade = job.fmt.split(":")[1]
        if qualidade == "best":
            opts["format"] = "bestvideo+bestaudio/best"
        else:
            opts["format"] = f"bestvideo[height<={qualidade}]+bestaudio/best[height<={qualidade}]"
        opts["merge_output_format"] = "mkv"
        opts["outtmpl"] = str(Path(job.dest_dir) / "%(title)s [%(resolution)s].%(ext)s")

    if cfg.embed_thumbnail:
        opts["writethumbnail"] = True
        pps.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
        pps.append({"key": "EmbedThumbnail"})
    if cfg.embed_metadata:
        pps.append({"key": "FFmpegMetadata"})

    opts["postprocessors"] = pps
    return opts


# ══════════════════════════════════════════════════════════════════
# Cookies
# ══════════════════════════════════════════════════════════════════
#
# O yt-dlp regrava o arquivo de cookies ao terminar (guardando os que o
# servidor renovou) — é isso que faz o arquivo durar mais sem reexportar.
# Mas ele grava truncando o arquivo, sem ser atômico: dois downloads
# simultâneos apontando para o mesmo cookies.txt podem destruí-lo. Por isso
# o uso de cookies é serializado — só um download por vez os utiliza.

_cookies_slot = threading.Lock()


def cookies_no_navegador_disponivel() -> bool:
    """Ler direto do Firefox só funciona no desktop (no Android é sandbox)."""
    return not IS_TERMUX


def cookies_disponiveis(cfg: Config) -> bool:
    if cfg.cookies_modo == "firefox":
        return cookies_no_navegador_disponivel()
    return cookies_validos(cfg.cookies_file)


def _proteger_cookies(cfg: Config) -> None:
    """Guarda uma cópia antes de deixar o yt-dlp reescrever o arquivo."""
    origem = Path(cfg.cookies_file).expanduser()
    try:
        if cookies_validos(str(origem)):
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origem, COOKIES_BACKUP)
    except OSError:
        pass


def _restaurar_cookies(cfg: Config) -> bool:
    """Se a regravação deixou o arquivo inválido (app morto no meio), volta."""
    origem = Path(cfg.cookies_file).expanduser()
    try:
        if origem.exists() and not cookies_validos(str(origem)) and cookies_validos(str(COOKIES_BACKUP)):
            shutil.copyfile(COOKIES_BACKUP, origem)
            return True
    except OSError:
        pass
    return False


@contextlib.contextmanager
def sessao_cookies(cfg: Config):
    """Empresta os cookies para um único yt-dlp por vez."""
    if not cookies_disponiveis(cfg):
        yield {}
        return
    if cfg.cookies_modo == "firefox":
        # Leitura do perfil do navegador: não escreve nada, mas serializa
        # junto para manter um caminho só.
        with _cookies_slot:
            yield {"cookiesfrombrowser": ("firefox", None, None, None)}
        return
    with _cookies_slot:
        _proteger_cookies(cfg)
        try:
            yield {"cookiefile": str(Path(cfg.cookies_file).expanduser())}
        finally:
            _restaurar_cookies(cfg)


def fetch_info(url: str, cfg: Config, usar_cookies: bool = False) -> dict:
    """Extrai metadados sem baixar (playlists de forma achatada)."""
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "playlist_items": f"1-{MAX_PLAYLIST_ITEMS}",
        "socket_timeout": 20,
    }
    if not usar_cookies:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False) or {}
    with sessao_cookies(cfg) as cookies:
        with yt_dlp.YoutubeDL({**opts, **cookies}) as ydl:
            return ydl.extract_info(url, download=False) or {}


def resumir_info(url: str, info: dict) -> dict:
    """Reduz o resultado do yt-dlp ao que a interface precisa."""
    site = detect_site(url)
    if site == "Outros":
        site = sanitize_name(str(info.get("extractor_key") or "Outros"))

    entries = [e for e in (info.get("entries") or []) if e]
    if info.get("_type") == "playlist" and entries:
        titulo = info.get("title") or info.get("channel") or info.get("uploader") or "Playlist"
        uploader = info.get("channel") or info.get("uploader") or "—"

        # URL de canal raiz devolve as abas (Videos, Shorts, Live), não vídeos
        abas = [e for e in entries if e.get("_type") == "playlist" and e.get("webpage_url")]
        if len(abas) == len(entries):
            return {
                "kind": "canal",
                "url": url,
                "site": site,
                "title": titulo,
                "uploader": uploader,
                "tabs": [{"title": a.get("title") or "", "url": a["webpage_url"]} for a in abas],
            }

        return {
            "kind": "playlist",
            "url": url,
            "site": site,
            "title": titulo,
            "uploader": uploader,
            "entries": [
                {
                    "id": e.get("id") or "",
                    "url": e.get("url") or e.get("webpage_url"),
                    "title": e.get("title") or f"Item {i + 1}",
                    "duration": e.get("duration"),
                    "live_status": e.get("live_status"),
                }
                for i, e in enumerate(entries)
                if e.get("url") or e.get("webpage_url")
            ],
        }
    return {
        "kind": "single",
        "url": url,
        "site": site,
        "id": info.get("id") or "",
        "title": info.get("title") or "Sem título",
        "uploader": info.get("uploader") or info.get("channel") or "—",
        "duration": info.get("duration"),
        "live_status": info.get("live_status"),
    }


def pasta_destino(summary: dict, fmt: str, cfg: Config) -> Path:
    """Onde os arquivos deste download vão parar."""
    if summary["kind"] == "playlist":
        return cfg.dir_playlists / sanitize_name(summary["title"])
    if fmt == "audio":
        return cfg.dir_musicas
    return cfg.dir_videos / sanitize_name(summary["site"])


def fonte_de_shorts(url: str) -> bool:
    """URL que pede Shorts explicitamente: link de Short ou aba /shorts."""
    return url_de_short(url) or url.rstrip("/").lower().endswith("/shorts")


def fonte_de_lives(url: str) -> bool:
    """URL que pede lives explicitamente: aba /streams (ou /live) do canal."""
    fim = url.rstrip("/").lower()
    return fim.endswith("/streams") or fim.endswith("/live")


def expandir_canal(summary: dict, cfg: Config, ignorar_shorts: bool,
                   ignorar_lives: bool = False) -> dict:
    """Converte um canal (lista de abas) na lista de vídeos das suas abas."""
    entries: list[dict] = []
    lives_ignoradas = False
    for aba in summary["tabs"]:
        titulo_aba = aba["title"].rstrip().lower()
        if ignorar_shorts and titulo_aba.endswith("shorts"):
            continue
        # A aba "Live" reúne transmissões e suas gravações; a aba "Videos"
        # já não traz nada disso.
        if ignorar_lives and (titulo_aba.endswith("live") or titulo_aba.endswith("streams")):
            lives_ignoradas = True
            continue
        try:
            resumo_aba = resumir_info(aba["url"], fetch_info(aba["url"], cfg))
        except Exception:
            try:  # pode ser aba que exige login
                resumo_aba = resumir_info(aba["url"], fetch_info(aba["url"], cfg, usar_cookies=True))
            except Exception:
                continue  # aba indisponível não invalida o resto do canal
        if resumo_aba["kind"] == "playlist":
            entries.extend(resumo_aba["entries"])

    return {
        "kind": "playlist",
        "url": summary["url"],
        "site": summary["site"],
        "title": summary["title"],
        "uploader": summary["uploader"],
        "entries": entries,
        "shorts_ignorados": 0,
        "aba_shorts_ignorada": ignorar_shorts,
        "lives_ignoradas": 0,
        "aba_lives_ignorada": lives_ignoradas,
    }


# ══════════════════════════════════════════════════════════════════
# Telas modais
# ══════════════════════════════════════════════════════════════════

class ConfirmScreen(ModalScreen[bool]):
    """Pergunta sim/não."""

    BINDINGS = [Binding("escape", "dismiss_no", "Fechar", show=False)]

    def __init__(self, mensagem: str, botao_sim: str = "Sim", botao_nao: str = "Não") -> None:
        super().__init__()
        self._mensagem = mensagem
        self._sim = botao_sim
        self._nao = botao_nao

    def compose(self) -> ComposeResult:
        with Container(classes="modal caixa-confirm"):
            yield Label("Confirmação", classes="modal-titulo")
            yield Static(self._mensagem, classes="confirm-msg")
            with Horizontal(classes="botoes"):
                yield Button(self._sim, variant="error", id="btn-sim")
                yield Button(self._nao, variant="primary", id="btn-nao")

    @on(Button.Pressed, "#btn-sim")
    def _sim_pressed(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#btn-nao")
    def _nao_pressed(self) -> None:
        self.dismiss(False)

    def action_dismiss_no(self) -> None:
        self.dismiss(False)


class AddDownloadScreen(ModalScreen[dict | None]):
    """Analisa a URL e deixa escolher formato/qualidade antes de enfileirar."""

    BINDINGS = [Binding("escape", "fechar", "Fechar", show=False)]

    def __init__(self, url: str, cfg: Config) -> None:
        super().__init__()
        self._url = url
        self._cfg = cfg
        self._summary: dict | None = None
        self._novos: list[dict] = []
        self._ja_baixado = False

    def compose(self) -> ComposeResult:
        with Container(classes="modal caixa-add"):
            yield Label("Novo download", classes="modal-titulo")
            with VerticalScroll(classes="modal-corpo"):
                yield Static(self._url, id="add-url")
                with Horizontal(id="add-loading"):
                    yield LoadingIndicator()
                    yield Static("Analisando link…", id="add-loading-texto")
                yield Static("", id="add-info")
                # Lado a lado: economiza altura em telas de celular
                with Horizontal(id="add-selects"):
                    with Vertical(id="add-fmt-box"):
                        yield Label("Formato", classes="campo-label", id="add-fmt-label")
                        yield Select(
                            [
                                ("Vídeo — Melhor qualidade", "video:best"),
                                ("Vídeo — até 1080p", "video:1080"),
                                ("Vídeo — até 720p", "video:720"),
                                ("Vídeo — até 480p", "video:480"),
                                ("Vídeo — até 360p", "video:360"),
                                (f"Áudio — MP3 {self._cfg.audio_quality}k", "audio"),
                            ],
                            allow_blank=False,
                            value="video:best",
                            id="add-fmt",
                        )
                    with Vertical(id="add-escopo-box"):
                        yield Label("Escopo", classes="campo-label", id="add-escopo-label")
                        yield Select(
                            [("Playlist completa", "playlist"), ("Somente este vídeo", "single")],
                            allow_blank=False,
                            value="playlist",
                            id="add-escopo",
                        )
            with Horizontal(classes="botoes"):
                yield Button("Adicionar à fila", variant="success", id="btn-ok", disabled=True)
                yield Button("Cancelar", id="btn-cancelar")

    def on_mount(self) -> None:
        self.query_one("#add-info").display = False
        self.query_one("#add-selects").display = False
        self.query_one("#add-escopo-box").display = False
        self.run_worker(self._fetch, thread=True, exclusive=True)

    def _analisar(self) -> dict:
        """Sem cookies primeiro; só usa a conta se o link exigir login."""
        try:
            return resumir_info(self._url, fetch_info(self._url, self._cfg))
        except Exception:
            if not cookies_disponiveis(self._cfg):
                raise
            self.app.call_from_thread(self._status_analise, "Tentando com cookies…")
            return resumir_info(self._url, fetch_info(self._url, self._cfg, usar_cookies=True))

    def _fetch(self) -> None:
        try:
            summary = self._analisar()

            # Shorts só entram quando pedidos explicitamente (link de Short
            # ou aba /shorts) — nunca junto de uma playlist ou canal.
            ignorar = self._cfg.ignorar_shorts and not fonte_de_shorts(self._url)

            ignorar_lives = self._cfg.ignorar_lives and not fonte_de_lives(self._url)

            if summary["kind"] == "canal":
                self.app.call_from_thread(self._status_analise, "Listando vídeos do canal…")
                summary = expandir_canal(summary, self._cfg, ignorar, ignorar_lives)

            if ignorar_lives and summary["kind"] == "playlist" and not summary.get("aba_lives_ignorada"):
                videos, lives = separar_lives(summary["entries"])
                summary["entries"] = videos
                summary["lives_ignoradas"] = len(lives)

            if ignorar and summary["kind"] == "playlist" and not summary.get("aba_shorts_ignorada"):
                def aviso(quantos: int) -> None:
                    self.app.call_from_thread(
                        self._status_analise, f"Identificando Shorts ({quantos} a checar)…"
                    )

                videos, shorts = separar_shorts(summary["entries"], progresso=aviso)
                summary["entries"] = videos
                summary["shorts_ignorados"] = len(shorts)
        except Exception as exc:  # rede, URL inválida, bloqueio do site…
            msg = str(exc)
            self.app.call_from_thread(self._mostrar_erro, msg)
            return
        self.app.call_from_thread(self._mostrar_info, summary)

    def _status_analise(self, texto: str) -> None:
        try:
            self.query_one("#add-loading-texto", Static).update(texto)
        except Exception:
            pass

    def _mostrar_erro(self, msg: str) -> None:
        try:
            self.query_one("#add-loading").display = False
            alvo = self.query_one("#add-info", Static)
            alvo.display = True
            alvo.update(
                Text.assemble(("✗ Não foi possível analisar o link.\n", "bold red"), (msg[:300], "dim"))
            )
            self.query_one("#btn-cancelar", Button).label = "Fechar"
        except Exception:
            pass

    def _mostrar_info(self, summary: dict) -> None:
        try:
            self._summary = summary
            self.query_one("#add-loading").display = False
            self.query_one("#add-info").display = True
            self.query_one("#add-url").display = False  # o título já identifica
            self.query_one("#add-selects").display = True
            if summary["kind"] == "playlist" and self._tem_video_unico():
                self.query_one("#add-escopo-box").display = True
            self._render_info()
            botao = self.query_one("#btn-ok", Button)
            botao.disabled = False
            botao.focus()
        except Exception:
            pass

    @on(Select.Changed, "#add-fmt")
    def _formato_mudou(self) -> None:
        if self._summary is not None:
            self._render_info()

    def _render_info(self) -> None:
        """Monta o painel — o que já foi baixado depende do formato escolhido."""
        summary = self._summary
        if summary is None:
            return
        fmt = str(self.query_one("#add-fmt", Select).value)
        pasta = pasta_destino(summary, fmt, self._cfg)

        texto = Text()
        texto.append("Título   ", "bold")
        texto.append(f"{summary['title']}\n")
        texto.append("Canal    ", "bold")
        texto.append(f"{summary['uploader']}\n")
        texto.append("Site     ", "bold")
        texto.append(f"{summary['site']}\n")

        if summary["kind"] == "playlist":
            self._novos, ja_baixados = separar_baixados(summary["entries"], pasta, fmt)
            total = len(summary["entries"])
            texto.append("Itens    ", "bold")
            texto.append(f"{len(self._novos)}", "bold magenta")
            texto.append(" novos", "bold magenta")
            texto.append(f" de {total}")
            if total >= MAX_PLAYLIST_ITEMS:
                texto.append(f" (limitado a {MAX_PLAYLIST_ITEMS})", "dim")
            if ja_baixados:
                texto.append("\nJá tenho ", "bold")
                texto.append(f"{len(ja_baixados)} — serão pulados", "green")
            ignorados = summary.get("shorts_ignorados") or 0
            if ignorados or summary.get("aba_shorts_ignorada"):
                texto.append("\nShorts   ", "bold")
                texto.append(f"{ignorados} ignorados" if ignorados else "ignorados", "yellow")
            lives = summary.get("lives_ignoradas") or 0
            if lives or summary.get("aba_lives_ignorada"):
                texto.append("\nLives    ", "bold")
                texto.append(f"{lives} ignoradas" if lives else "ignoradas", "yellow")
        else:
            self._novos = []
            texto.append("Duração  ", "bold")
            texto.append(fmt_duration(summary.get("duration")))
            _, ja = separar_baixados(
                [{"id": summary.get("id", ""), "title": summary["title"]}], pasta, fmt
            )
            self._ja_baixado = bool(ja)
            if ja:
                texto.append("\nJá tenho ", "bold")
                texto.append("este arquivo na pasta", "green")
            if str(summary.get("live_status") or "") in LIVE_STATUS:
                texto.append("\nAviso    ", "bold")
                texto.append("é uma live — o download vai até ela terminar", "yellow")

        try:
            self.query_one("#add-info", Static).update(texto)
            botao = self.query_one("#btn-ok", Button)
            if summary["kind"] == "playlist":
                botao.label = "Adicionar à fila" if self._novos else "Nada novo para baixar"
                botao.disabled = not self._novos
            else:
                botao.label = "Baixar de novo" if self._ja_baixado else "Adicionar à fila"
                botao.disabled = False
        except Exception:
            pass

    def _tem_video_unico(self) -> bool:
        return "v=" in self._url or "/watch" in self._url

    def _video_unico(self) -> dict:
        """Converte o resumo de playlist em item único (URL com v= e list=)."""
        assert self._summary is not None
        video_id = ""
        match = re.search(r"[?&]v=([\w-]+)", self._url)
        if match:
            video_id = match.group(1)
        titulo = "Vídeo"
        for e in self._summary["entries"]:
            if video_id and e.get("id") == video_id:
                titulo = e["title"]
                break
        return {
            "kind": "single",
            "url": self._url,
            "site": self._summary["site"],
            "id": video_id,
            "title": titulo,
            "uploader": self._summary["uploader"],
            "duration": None,
        }

    @on(Button.Pressed, "#btn-ok")
    def _confirmar(self) -> None:
        if self._summary is None:
            return
        summary = self._summary
        escopo = self.query_one("#add-escopo", Select)
        escopo_visivel = self.query_one("#add-escopo-box").display
        if summary["kind"] == "playlist" and escopo_visivel and escopo.value == "single":
            summary = self._video_unico()
        elif summary["kind"] == "playlist":
            # Só o que ainda não está na pasta de destino
            summary = {**summary, "entries": self._novos}
        self.dismiss({"summary": summary, "fmt": self.query_one("#add-fmt", Select).value})

    @on(Button.Pressed, "#btn-cancelar")
    def _cancelar(self) -> None:
        self.dismiss(None)

    def action_fechar(self) -> None:
        self.dismiss(None)


class SettingsScreen(ModalScreen[bool]):
    """Edita e persiste a configuração."""

    BINDINGS = [Binding("escape", "fechar", "Fechar", show=False)]

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self._cfg = cfg

    def compose(self) -> ComposeResult:
        cfg = self._cfg
        with Container(classes="modal caixa-config"):
            yield Label("Configurações", classes="modal-titulo")
            # Rolável: em telas baixas (Termux) os botões continuam alcançáveis
            with VerticalScroll(classes="modal-corpo"):
                yield Label("Pasta base de downloads", classes="campo-label")
                yield Input(value=cfg.base_dir, id="cfg-dir")
                yield Label("Cookies (para conteúdo com login)", classes="campo-label")
                opcoes_ck = [("Arquivo cookies.txt", "arquivo")]
                if cookies_no_navegador_disponivel():
                    opcoes_ck.append(("Ler direto do Firefox do sistema", "firefox"))
                validos = {valor for _, valor in opcoes_ck}
                yield Select(
                    opcoes_ck,
                    allow_blank=False,
                    value=cfg.cookies_modo if cfg.cookies_modo in validos else "arquivo",
                    id="cfg-cookies-modo",
                )
                yield Input(value=cfg.cookies_file, id="cfg-cookies")
                yield Static("", id="cfg-cookies-status")
                with Horizontal(id="cfg-selects"):
                    with Vertical():
                        yield Label("Downloads simultâneos", classes="campo-label")
                        yield Select(
                            [(str(n), n) for n in range(1, 6)],
                            allow_blank=False,
                            value=min(max(cfg.max_concurrent, 1), 5),
                            id="cfg-simultaneos",
                        )
                    with Vertical():
                        yield Label("Qualidade do MP3", classes="campo-label")
                        yield Select(
                            [(f"{k} kbps", k) for k in ("128", "192", "256", "320")],
                            allow_blank=False,
                            value=cfg.audio_quality if cfg.audio_quality in ("128", "192", "256", "320") else "320",
                            id="cfg-audio",
                        )
                with Horizontal(classes="linha-switch"):
                    yield Switch(value=cfg.embed_thumbnail, id="cfg-thumb")
                    yield Label("Incorporar thumbnail nos arquivos")
                with Horizontal(classes="linha-switch"):
                    yield Switch(value=cfg.embed_metadata, id="cfg-meta")
                    yield Label("Incorporar metadados (título, artista…)")
                with Horizontal(classes="linha-switch"):
                    yield Switch(value=cfg.ignorar_shorts, id="cfg-shorts")
                    yield Label("Ignorar Shorts em playlists e canais")
                with Horizontal(classes="linha-switch"):
                    yield Switch(value=cfg.ignorar_lives, id="cfg-lives")
                    yield Label("Ignorar lives (e suas gravações)")
                with Horizontal(classes="linha-switch"):
                    yield Switch(value=cfg.auto_update, id="cfg-autoupdate")
                    yield Label("Atualizar o yt-dlp ao iniciar o app")
            with Horizontal(classes="botoes"):
                yield Button("Salvar", variant="success", id="btn-salvar")
                yield Button("Cancelar", id="btn-cancelar")

    def on_mount(self) -> None:
        self._atualizar_status_cookies()

    def _atualizar_status_cookies(self) -> None:
        modo = str(self.query_one("#cfg-cookies-modo", Select).value)
        campo = self.query_one("#cfg-cookies", Input)
        alvo = self.query_one("#cfg-cookies-status", Static)
        campo.display = modo == "arquivo"

        if modo == "firefox":
            alvo.update(Text("Usa a sessão do Firefox — nada para exportar", style="green"))
            return
        mensagem, estilo = resumo_cookies(campo.value.strip())
        alvo.update(Text(mensagem, style=estilo))

    @on(Input.Changed, "#cfg-cookies")
    @on(Select.Changed, "#cfg-cookies-modo")
    def _cookies_mudou(self) -> None:
        self._atualizar_status_cookies()

    @on(Button.Pressed, "#btn-salvar")
    def _salvar(self) -> None:
        cfg = self._cfg
        pasta = self.query_one("#cfg-dir", Input).value.strip()
        if pasta:
            cfg.base_dir = pasta
        cfg.cookies_file = self.query_one("#cfg-cookies", Input).value.strip()
        cfg.cookies_modo = str(self.query_one("#cfg-cookies-modo", Select).value)
        cfg.max_concurrent = int(self.query_one("#cfg-simultaneos", Select).value)
        cfg.audio_quality = str(self.query_one("#cfg-audio", Select).value)
        cfg.embed_thumbnail = self.query_one("#cfg-thumb", Switch).value
        cfg.embed_metadata = self.query_one("#cfg-meta", Switch).value
        cfg.ignorar_shorts = self.query_one("#cfg-shorts", Switch).value
        cfg.ignorar_lives = self.query_one("#cfg-lives", Switch).value
        cfg.auto_update = self.query_one("#cfg-autoupdate", Switch).value
        cfg.save()
        self.dismiss(True)

    @on(Button.Pressed, "#btn-cancelar")
    def _cancelar(self) -> None:
        self.dismiss(False)

    def action_fechar(self) -> None:
        self.dismiss(False)


class HistoryScreen(ModalScreen[None]):
    """Lista os downloads concluídos."""

    BINDINGS = [Binding("escape", "fechar", "Fechar", show=False)]

    def compose(self) -> ComposeResult:
        with Container(classes="modal caixa-historico"):
            yield Label("Histórico de downloads", classes="modal-titulo")
            yield Static("", id="hist-resumo")
            yield DataTable(id="hist-tabela")
            with Horizontal(classes="botoes"):
                yield Button("Limpar histórico", variant="error", id="btn-limpar")
                yield Button("Fechar", variant="primary", id="btn-fechar")

    def on_mount(self) -> None:
        tabela = self.query_one("#hist-tabela", DataTable)
        tabela.cursor_type = "row"
        tabela.zebra_stripes = True
        tabela.add_column("Data", key="data", width=16)
        tabela.add_column("Título", key="titulo", width=42)
        tabela.add_column("Site", key="site", width=10)
        tabela.add_column("Formato", key="formato", width=9)
        tabela.add_column("Tamanho", key="tamanho", width=9)
        self._recarregar()

    def _recarregar(self) -> None:
        tabela = self.query_one("#hist-tabela", DataTable)
        tabela.clear()
        historico = load_history()
        total_bytes = sum(e.get("bytes") or 0 for e in historico)
        resumo = self.query_one("#hist-resumo", Static)
        if historico:
            resumo.update(
                Text(f"{len(historico)} downloads · {human_size(total_bytes)} no total", style="dim")
            )
            for e in historico:
                tabela.add_row(
                    e.get("data", "—"),
                    e.get("titulo", "—"),
                    e.get("site", "—"),
                    e.get("formato", "—"),
                    e.get("tamanho", "—"),
                )
        else:
            resumo.update(Text("Nada por aqui ainda — baixe algo primeiro.", style="dim"))

    @on(Button.Pressed, "#btn-limpar")
    def _limpar(self) -> None:
        def _cb(ok: bool | None) -> None:
            if ok:
                clear_history()
                self._recarregar()

        self.app.push_screen(ConfirmScreen("Apagar todo o histórico de downloads?"), _cb)

    @on(Button.Pressed, "#btn-fechar")
    def _fechar(self) -> None:
        self.dismiss(None)

    def action_fechar(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "fechar", "Fechar", show=False)]

    ATALHOS = [
        ("Enter", "Analisar a URL digitada"),
        ("a", "Nova URL (focar o campo de digitação)"),
        ("Esc", "Ir para a fila (ativa os atalhos de letra)"),
        ("v", "Colar URL da área de transferência"),
        ("x", "Cancelar o item selecionado na fila"),
        ("r", "Repetir item com erro ou cancelado"),
        ("R", "Repetir todos os erros que valem a pena"),
        ("l", "Limpar itens concluídos da fila"),
        ("o", "Abrir a pasta de downloads"),
        ("h", "Histórico de downloads"),
        ("s", "Configurações"),
        ("t", "Alternar tema visual"),
        ("q", "Sair"),
    ]

    def compose(self) -> ComposeResult:
        with Container(classes="modal caixa-ajuda"):
            yield Label("Atalhos de teclado", classes="modal-titulo")
            texto = Text()
            for tecla, descricao in self.ATALHOS:
                texto.append(f"  {tecla:<7}", "bold #019DEA")
                texto.append(f"{descricao}\n")
            with VerticalScroll(classes="modal-corpo"):
                yield Static(texto)
            with Horizontal(classes="botoes"):
                yield Button("Fechar", variant="primary", id="btn-fechar")

    @on(Button.Pressed, "#btn-fechar")
    def _fechar(self) -> None:
        self.dismiss(None)

    def action_fechar(self) -> None:
        self.dismiss(None)


# ══════════════════════════════════════════════════════════════════
# Aplicação principal
# ══════════════════════════════════════════════════════════════════

class AVDownloaderApp(App):
    TITLE = APP_NAME
    SUB_TITLE = f"v{VERSION}"

    BINDINGS = [
        Binding("a", "nova_url", "Nova URL"),
        Binding("v", "colar", "Colar URL"),
        Binding("x", "cancelar_item", "Cancelar item"),
        Binding("h", "historico", "Histórico"),
        Binding("s", "configuracoes", "Config"),
        Binding("question_mark", "ajuda", "Ajuda"),
        Binding("q", "quit", "Sair"),
        # Esc e F1 funcionam mesmo com o campo de URL focado (teclas não
        # imprimíveis): são a porta de entrada para os demais atalhos.
        Binding("escape", "focar_fila", "Atalhos"),
        Binding("f1", "ajuda", "Ajuda", show=False),
        Binding("r", "repetir_item", "Repetir item", show=False),
        Binding("R", "repetir_erros", "Repetir todos os erros", show=False),
        Binding("l", "limpar_concluidos", "Limpar concluídos", show=False),
        Binding("o", "abrir_pasta", "Abrir pasta", show=False),
        Binding("t", "alternar_tema", "Tema", show=False),
    ]

    CSS = """
    #banner {
        height: 4;
        content-align: center middle;
        text-align: center;
        color: $primary;
        text-style: bold;
        margin: 1 0 0 0;
    }
    #tagline {
        height: 1;
        content-align: center middle;
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }
    #url-bar {
        height: 3;
        margin: 0 2;
    }
    #url-input {
        width: 1fr;
    }
    #btn-add {
        margin-left: 1;
        min-width: 12;
    }
    #stats {
        height: 1;
        margin: 0 3;
        color: $text-muted;
    }
    #queue {
        margin: 1 2;
        border: round $primary 60%;
        border-title-color: $primary;
        border-title-style: bold;
    }

    .modal {
        background: $surface;
        border: round $primary;
        padding: 1 2;
        width: 72;
        max-width: 96%;
        height: auto;
        max-height: 90%;
    }
    ConfirmScreen, AddDownloadScreen, SettingsScreen, HistoryScreen, HelpScreen {
        align: center middle;
    }
    .modal-titulo {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
        height: 1;
    }
    /* O corpo cresce com o conteúdo até um teto proporcional à tela: o modal
       fica compacto quando há pouca coisa e, quando há muita, rola por dentro
       em vez de empurrar os botões para fora (telas baixas, Termux). */
    /* Com os botões ancorados no rodapé, o corpo pode ocupar o que sobra:
       a caixa encolhe quando há pouco conteúdo e rola quando há muito. */
    .modal-corpo {
        height: auto;
        max-height: 100%;
        scrollbar-size-vertical: 1;
    }
    .campo-label {
        color: $text-muted;
        margin-top: 1;
    }
    .botoes {
        dock: bottom;
        height: 3;
        margin-top: 1;
        align-horizontal: right;
    }
    .botoes Button {
        margin-left: 2;
    }
    .confirm-msg {
        margin: 1 0;
    }
    #add-url {
        color: $text-muted;
        text-style: italic;
        height: auto;
    }
    #add-loading {
        height: 3;
    }
    #add-loading LoadingIndicator {
        width: 8;
    }
    #add-loading-texto {
        content-align: left middle;
        height: 3;
        width: 1fr;
    }
    #add-info {
        margin-top: 1;
        height: auto;
    }
    #add-selects {
        height: auto;
    }
    #add-selects Vertical {
        width: 1fr;
        height: auto;
    }
    #add-fmt-box {
        margin-right: 2;
    }
    .caixa-config Input {
        margin-top: 0;
    }
    #cfg-selects {
        height: auto;
    }
    #cfg-selects Vertical {
        width: 1fr;
        height: auto;
    }
    #cfg-selects Vertical:first-of-type {
        margin-right: 2;
    }
    #cfg-cookies-status {
        height: 1;
        margin-top: 0;
    }
    .linha-switch {
        height: auto;
        margin-top: 1;
    }
    .linha-switch Label {
        content-align: left middle;
        height: 3;
        margin-left: 1;
    }
    .caixa-historico {
        width: 100;
    }
    #hist-tabela {
        height: 40vh;
        margin-top: 1;
    }
    #hist-resumo {
        height: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.config = Config.load()
        self.jobs: dict[int, Job] = {}
        self._ativos = 0
        self._ativos_lock = threading.Lock()
        self._status_updater = ""

    # ── Interface ─────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(BANNER, id="banner")
        yield Static(TAGLINE, id="tagline")
        with Horizontal(id="url-bar"):
            yield Input(
                placeholder="Cole a URL do vídeo, música ou playlist e aperte Enter…",
                id="url-input",
            )
            yield Button("Baixar", variant="primary", id="btn-add")
        yield Static("", id="stats")
        yield DataTable(id="queue")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(LUNA_THEME)
        if self.config.theme in getattr(self, "available_themes", {self.config.theme: None}):
            self.theme = self.config.theme

        tabela = self.query_one("#queue", DataTable)
        tabela.cursor_type = "row"
        tabela.zebra_stripes = True
        tabela.border_title = "Fila de downloads"
        # Colunas em ordem de importância: em telas estreitas (Termux), o que
        # some primeiro na rolagem horizontal é o menos essencial.
        largura = self.size.width if self.size.width > 0 else 100
        self._largura_titulo = max(18, min(60, largura - 88))
        tabela.add_column("Título", key="titulo", width=self._largura_titulo)
        tabela.add_column("Progresso", key="progresso", width=19)
        tabela.add_column("Status", key="status", width=13)
        tabela.add_column("Veloc.", key="veloc", width=9)
        tabela.add_column("ETA", key="eta", width=6)
        tabela.add_column("Formato", key="formato", width=9)
        tabela.add_column("Site", key="site", width=10)

        if not shutil.which("ffmpeg"):
            self.notify(
                "ffmpeg não encontrado — conversão para MP3 e merge de vídeo não vão funcionar. "
                + ("Instale com: pkg install ffmpeg" if IS_TERMUX else "Instale o pacote ffmpeg."),
                severity="warning",
                timeout=12,
            )
        self._atualizar_stats()
        self.set_interval(1.0, self._atualizar_stats)
        self.query_one("#url-input", Input).focus()

        # Atualiza o yt-dlp em segundo plano — apenas dentro da venv (ou no
        # Termux), para nunca instalar nada no python do sistema.
        if self.config.auto_update and (IS_TERMUX or sys.prefix != sys.base_prefix):
            self.run_worker(self._atualizar_ytdlp, thread=True, group="updater")

    def _atualizar_stats(self) -> None:
        jobs = list(self.jobs.values())
        fila = sum(1 for j in jobs if j.status is Status.QUEUED)
        baixando = sum(1 for j in jobs if j.status in (Status.DOWNLOADING, Status.CONVERTING))
        ok = sum(1 for j in jobs if j.status in (Status.DONE, Status.WARN))
        erros = sum(1 for j in jobs if j.status is Status.ERROR)
        veloc_total = sum(j.speed or 0 for j in jobs if j.status is Status.DOWNLOADING)

        if self.config.cookies_modo == "firefox" and cookies_no_navegador_disponivel():
            cookies = "cookies: Firefox"
        elif cookies_validos(self.config.cookies_file):
            cookies = "cookies ativos"
        else:
            cookies = "cookies inativos"
        partes = [cookies, f"○ {fila}", f"↓ {baixando}", f"✓ {ok}", f"✗ {erros}"]
        if veloc_total:
            partes.append(human_speed(veloc_total))
        if self._status_updater:
            partes.append(self._status_updater)
        partes.append(str(self.config.base_dir))
        self.query_one("#stats", Static).update(" · ".join(partes))

    # ── Atualização do yt-dlp (roda em thread) ────────────────────

    def _atualizar_ytdlp(self) -> None:
        worker = get_current_worker()
        atual = yt_dlp.version.__version__
        self._status_updater = f"atualizando yt-dlp {atual}…"
        try:
            self.call_from_thread(self._atualizar_stats)
        except Exception:
            pass

        proc = None
        erro = ""
        try:
            proc = subprocess.Popen(
                [
                    sys.executable, "-m", "pip", "install",
                    "--upgrade", "--quiet", "--disable-pip-version-check", "yt-dlp",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            inicio = time.monotonic()
            while proc.poll() is None:
                # Se o app fechar (worker cancelado), não deixa o pip para trás
                if worker.is_cancelled or time.monotonic() - inicio > 300:
                    proc.terminate()
                    self._status_updater = ""
                    return
                time.sleep(0.3)
            if proc.stderr:
                erro = (proc.stderr.read() or "").strip()
        except OSError as exc:
            erro = str(exc)

        self._status_updater = ""
        try:
            if proc is not None and proc.returncode == 0:
                try:
                    nova = metadata.version("yt-dlp")
                except metadata.PackageNotFoundError:
                    nova = atual
                if versao_tupla(nova) != versao_tupla(atual):
                    self.call_from_thread(
                        self.notify,
                        f"yt-dlp atualizado: {atual} → {nova}. "
                        "Reinicie o app para usar a nova versão.",
                        timeout=12,
                    )
                else:
                    self.call_from_thread(
                        self.notify,
                        f"yt-dlp já está na última versão ({atual}).",
                        timeout=4,
                    )
            else:
                self.call_from_thread(
                    self.notify,
                    "Não foi possível atualizar o yt-dlp (sem internet?). "
                    "O app segue com a versão atual. " + erro[:120],
                    severity="warning",
                    timeout=8,
                )
            self.call_from_thread(self._atualizar_stats)
        except Exception:
            pass  # app encerrando

    # ── Adição de downloads ───────────────────────────────────────

    @on(Input.Submitted, "#url-input")
    @on(Button.Pressed, "#btn-add")
    def _url_enviada(self) -> None:
        campo = self.query_one("#url-input", Input)
        url = campo.value.strip().split()[0] if campo.value.strip() else ""
        if not url:
            self.notify("Cole uma URL primeiro.", severity="warning")
            return
        if "." not in url:
            self.notify("Isso não parece uma URL válida.", severity="error")
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        campo.value = ""
        self.push_screen(AddDownloadScreen(url, self.config), self._resultado_add)

    def _resultado_add(self, resultado: dict | None) -> None:
        if not resultado:
            self.query_one("#url-input", Input).focus()
            return
        summary, fmt = resultado["summary"], str(resultado["fmt"])
        novos: list[Job] = []

        pasta = pasta_destino(summary, fmt, self.config)
        if summary["kind"] == "playlist":
            for item in summary["entries"]:
                novos.append(
                    Job(
                        url=item["url"],
                        title=item["title"],
                        site=summary["site"],
                        fmt=fmt,
                        dest_dir=str(pasta),
                        video_id=item.get("id") or "",
                        bloquear_live=self.config.ignorar_lives,
                    )
                )
        else:
            novos.append(
                Job(
                    url=summary["url"],
                    title=summary["title"],
                    site=summary["site"],
                    fmt=fmt,
                    dest_dir=str(pasta),
                    video_id=summary.get("id") or "",
                )
            )

        if not novos:
            self.notify("Tudo dessa lista já está na pasta — nada a baixar.", timeout=6)
            self.query_one("#url-input", Input).focus()
            return

        tabela = self.query_one("#queue", DataTable)
        for job in novos:
            self.jobs[job.id] = job
            tabela.add_row(
                self._celula_titulo(job),
                self._celula_progresso(job),
                self._celula_status(job),
                "—",
                "—",
                job.fmt_label,
                job.site,
                key=str(job.id),
            )
            self.run_worker(
                lambda j=job: self._download_worker(j),
                thread=True,
                group="downloads",
                exclusive=False,
            )

        plural = "itens adicionados" if len(novos) > 1 else "item adicionado"
        self.notify(f"{len(novos)} {plural} à fila.", severity="information")
        self._atualizar_stats()
        # Foco na fila: assim os atalhos de letra (x, r, l…) funcionam direto
        self.query_one("#queue", DataTable).focus()

    # ── Células da tabela ─────────────────────────────────────────

    def _celula_titulo(self, job: Job) -> str:
        titulo = job.title
        limite = getattr(self, "_largura_titulo", 40)
        return titulo if len(titulo) <= limite else titulo[: limite - 1] + "…"

    @staticmethod
    def _celula_progresso(job: Job) -> Text:
        largura = 12
        if job.status is Status.QUEUED:
            return Text("╺" * largura + "   0%", style="grey37")
        if job.status in (Status.DONE, Status.WARN):
            return Text("━" * largura + " 100%", style="green")
        if job.status is Status.CANCELLED:
            return Text("╌" * largura + "   —", style="grey37")
        if job.status is Status.ERROR:
            return Text("╌" * largura + "   ✗", style="red")
        pct = max(0.0, min(job.progress, 1.0))
        cheio = int(pct * largura)
        barra = Text()
        barra.append("━" * cheio, style="bold #019DEA")
        barra.append("╺" * (largura - cheio), style="grey37")
        barra.append(f" {int(pct * 100):3d}%", style="bold")
        return barra

    @staticmethod
    def _celula_status(job: Job) -> Text:
        icone, rotulo, estilo = job.status
        if job.status is Status.ERROR and job.motivo:
            rotulo = job.motivo  # diz por que falhou, não só "Erro"
        elif job.status is Status.RETRY and job.tentativas:
            rotulo = f"{rotulo} {job.tentativas}/{MAX_TENTATIVAS}"
        return Text(f"{icone} {rotulo}", style=estilo)

    def _refresh_row(self, job: Job) -> None:
        try:
            tabela = self.query_one("#queue", DataTable)
            chave = str(job.id)
            tabela.update_cell(chave, "titulo", self._celula_titulo(job))
            tabela.update_cell(chave, "progresso", self._celula_progresso(job))
            tabela.update_cell(chave, "veloc", human_speed(job.speed))
            tabela.update_cell(chave, "eta", fmt_eta(job.eta))
            tabela.update_cell(chave, "status", self._celula_status(job))
        except Exception:
            pass  # linha removida da fila

    # ── Download (roda em thread) ─────────────────────────────────

    def _set_status(self, job: Job, status: tuple) -> None:
        job.status = status
        if status in Status.FINAIS:
            job.speed = None
            job.eta = None
        try:
            self.call_from_thread(self._refresh_row, job)
            self.call_from_thread(self._atualizar_stats)
        except Exception:
            pass  # app encerrando

    def _download_worker(self, job: Job) -> None:
        # 2ª tentativa (com cookies): serializada, um vídeo por vez — é o que
        # permite ao yt-dlp regravar o cookies.txt em segurança. Não ocupa
        # vaga na fila normal, então os demais downloads seguem em paralelo.
        if job.usar_cookies:
            self._set_status(job, Status.COOKIES)
            with sessao_cookies(self.config) as cookies:
                self._executar_download(job, cookies)
            return

        # Espera por uma vaga (respeita mudanças de max_concurrent ao vivo)
        while True:
            if job.cancel.is_set():
                self._set_status(job, Status.CANCELLED)
                return
            with self._ativos_lock:
                if self._ativos < self.config.max_concurrent:
                    self._ativos += 1
                    break
            time.sleep(0.3)
        try:
            self._executar_download(job, {})
        finally:
            with self._ativos_lock:
                self._ativos -= 1

    def _reenfileirar_com_cookies(self, job: Job) -> None:
        job.usar_cookies = True
        job.tentou_cookies = True
        job.progress = 0.0
        job.status = Status.COOKIES
        self._refresh_row(job)
        self.run_worker(
            lambda j=job: self._download_worker(j),
            thread=True,
            group="downloads",
            exclusive=False,
        )

    def _executar_download(self, job: Job, cookies: dict) -> None:
        try:
            if job.cancel.is_set():
                self._set_status(job, Status.CANCELLED)
                return
            Path(job.dest_dir).mkdir(parents=True, exist_ok=True)
            self._set_status(job, Status.COOKIES if cookies else Status.DOWNLOADING)

            def hook(d: dict) -> None:
                if job.cancel.is_set():
                    raise JobCancelled()
                status = d.get("status")
                if status == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate")
                    baixado = d.get("downloaded_bytes") or 0
                    if total:
                        job.total_bytes = total
                        job.progress = baixado / total
                    job.speed = d.get("speed")
                    job.eta = d.get("eta")
                    info = d.get("info_dict") or {}
                    if info.get("title"):
                        job.title = info["title"]
                    agora = time.monotonic()
                    if agora - job._last_ui > 0.2:
                        job._last_ui = agora
                        try:
                            self.call_from_thread(self._refresh_row, job)
                        except Exception:
                            pass
                elif status == "finished":
                    job.progress = 1.0
                    job.filepath = d.get("filename") or job.filepath
                    self._set_status(job, Status.CONVERTING)

            def pp_hook(d: dict) -> None:
                if job.cancel.is_set():
                    raise JobCancelled()
                info = d.get("info_dict") or {}
                if d.get("status") == "finished" and info.get("filepath"):
                    job.filepath = info["filepath"]

            opts = build_ydl_opts(job, self.config, hook, pp_hook, cookies)
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([job.url])

            if job.bloquear_live and not job.filepath:
                # O yt-dlp recusou pelo filtro: era uma live não detectada na
                # listagem. Não é erro — é o comportamento pedido.
                self._set_status(job, Status.IGNORED)
                return

            self._registrar_historico(job)
            self._set_status(job, Status.DONE)
        except JobCancelled:
            self._set_status(job, Status.CANCELLED)
        except Exception as exc:
            if job.cancel.is_set():
                self._set_status(job, Status.CANCELLED)
            elif (
                not cookies
                and not job.tentou_cookies
                and not (job.filepath and Path(job.filepath).exists())
                and cookies_disponiveis(self.config)
            ):
                # Falhou sem cookies: pode ser conteúdo com login. Tenta de
                # novo com cookies, na fila serializada.
                job.error = str(exc)
                try:
                    self.call_from_thread(self._reenfileirar_com_cookies, job)
                except Exception:
                    self._set_status(job, Status.ERROR)
            elif job.filepath and Path(job.filepath).exists():
                # Baixou, mas falhou em thumbnail/metadados
                job.error = str(exc)
                self._registrar_historico(job)
                self._set_status(job, Status.WARN)
                try:
                    self.call_from_thread(
                        self.notify,
                        "Download concluído, mas o pós-processamento falhou (thumbnail/metadados).",
                        severity="warning",
                    )
                except Exception:
                    pass
            else:
                job.error = str(exc)
                vale_repetir, motivo = classificar_erro(job.error)
                job.motivo = motivo
                if vale_repetir and job.tentativas < MAX_TENTATIVAS:
                    # Recoloca o link na fila — muitas falhas somem sozinhas
                    espera = ESPERA_TENTATIVA[min(job.tentativas, len(ESPERA_TENTATIVA) - 1)]
                    job.tentativas += 1
                    try:
                        self.call_from_thread(self._reagendar, job, espera)
                        return
                    except Exception:
                        pass
                self._set_status(job, Status.ERROR)

    def _reagendar(self, job: Job, espera: float) -> None:
        """Devolve o item à fila depois de uma pausa."""
        job.status = Status.RETRY
        job.progress = 0.0
        job.speed = None
        job.eta = None
        self._refresh_row(job)
        self._atualizar_stats()

        def voltar() -> None:
            if job.cancel.is_set() or job.status is not Status.RETRY:
                return
            job.usar_cookies = False  # recomeça pelo caminho rápido
            self.run_worker(
                lambda j=job: self._download_worker(j),
                thread=True,
                group="downloads",
                exclusive=False,
            )

        self.set_timer(espera, voltar)

    def _registrar_historico(self, job: Job) -> None:
        tamanho = None
        if job.filepath:
            try:
                tamanho = os.path.getsize(job.filepath)
            except OSError:
                pass
            registrar_baixado(job.dest_dir, job.video_id, job.fmt, job.filepath, job.title)
        append_history(
            {
                "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "titulo": job.title,
                "site": job.site,
                "formato": job.fmt_label,
                "arquivo": job.filepath,
                "bytes": tamanho,
                "tamanho": human_size(tamanho),
            }
        )

    # ── Ações ─────────────────────────────────────────────────────

    def _job_selecionado(self) -> Job | None:
        tabela = self.query_one("#queue", DataTable)
        if not tabela.row_count:
            return None
        try:
            chave = tabela.coordinate_to_cell_key(Coordinate(tabela.cursor_row, 0)).row_key
            return self.jobs.get(int(str(chave.value)))
        except Exception:
            return None

    def action_nova_url(self) -> None:
        self.query_one("#url-input", Input).focus()

    def action_focar_fila(self) -> None:
        self.query_one("#queue", DataTable).focus()

    def action_colar(self) -> None:
        texto = ler_clipboard()
        if texto:
            campo = self.query_one("#url-input", Input)
            campo.value = texto.splitlines()[0].strip()
            campo.focus()
            self.notify("URL colada. Aperte Enter para analisar.", timeout=4)
        else:
            self.notify(
                "Não consegui ler a área de transferência "
                + ("(instale termux-api)." if IS_TERMUX else "(instale wl-clipboard ou xclip)."),
                severity="warning",
            )

    def action_cancelar_item(self) -> None:
        job = self._job_selecionado()
        if job is None:
            self.notify("Nenhum item selecionado na fila.", severity="warning")
            return
        if job.status in Status.FINAIS:
            self.notify("Esse item já terminou.", severity="warning")
            return
        job.cancel.set()
        if job.status is Status.QUEUED:
            job.status = Status.CANCELLED
            self._refresh_row(job)
        self.notify(f"Cancelando: {self._celula_titulo(job)}")
        self._atualizar_stats()

    def action_repetir_item(self) -> None:
        job = self._job_selecionado()
        if job is None:
            self.notify("Nenhum item selecionado na fila.", severity="warning")
            return
        if job.status not in (Status.ERROR, Status.CANCELLED, Status.IGNORED):
            self.notify("Só é possível repetir itens com erro ou cancelados.", severity="warning")
            return
        self._recolocar(job)
        self.notify("Item recolocado na fila.")

    def _recolocar(self, job: Job) -> None:
        """Zera o item e o devolve à fila (tentativas incluídas)."""
        job.cancel = threading.Event()
        job.status = Status.QUEUED
        job.progress = 0.0
        job.speed = None
        job.eta = None
        job.error = ""
        job.motivo = ""
        job.tentativas = 0
        job.usar_cookies = False
        job.tentou_cookies = False
        self._refresh_row(job)
        self.run_worker(
            lambda j=job: self._download_worker(j),
            thread=True,
            group="downloads",
            exclusive=False,
        )

    def action_repetir_erros(self) -> None:
        """Recoloca de uma vez tudo que falhou — menos o que não adianta."""
        repetiveis = [
            j for j in self.jobs.values()
            if j.status is Status.ERROR and classificar_erro(j.error)[0]
        ]
        sem_jeito = sum(
            1 for j in self.jobs.values()
            if j.status is Status.ERROR and not classificar_erro(j.error)[0]
        )
        if not repetiveis:
            if sem_jeito:
                self.notify(
                    f"Os {sem_jeito} erros restantes não adiantam repetir "
                    "(membros, privado, removido…).",
                    severity="warning",
                )
            else:
                self.notify("Nenhum erro na fila.")
            return
        for job in repetiveis:
            self._recolocar(job)
        recado = f"{len(repetiveis)} itens de volta à fila."
        if sem_jeito:
            recado += f" {sem_jeito} sem jeito ficaram de fora."
        self.notify(recado)

    def action_limpar_concluidos(self) -> None:
        tabela = self.query_one("#queue", DataTable)
        removidos = 0
        for job_id, job in list(self.jobs.items()):
            if job.status in Status.FINAIS:
                try:
                    tabela.remove_row(str(job_id))
                except Exception:
                    pass
                del self.jobs[job_id]
                removidos += 1
        if removidos:
            self.notify(f"{removidos} itens removidos da fila.")
        self._atualizar_stats()

    def action_abrir_pasta(self) -> None:
        pasta = Path(self.config.base_dir)
        pasta.mkdir(parents=True, exist_ok=True)
        if not abrir_no_sistema(str(pasta)):
            self.notify(f"Pasta: {pasta}", timeout=8)

    def action_historico(self) -> None:
        self.push_screen(HistoryScreen())

    def action_configuracoes(self) -> None:
        def _cb(salvou: bool | None) -> None:
            if salvou:
                self.notify("Configurações salvas.")
                self._atualizar_stats()

        self.push_screen(SettingsScreen(self.config), _cb)

    def action_ajuda(self) -> None:
        self.push_screen(HelpScreen())

    def action_alternar_tema(self) -> None:
        try:
            atual = THEMES.index(self.theme)
        except ValueError:
            atual = -1
        novo = THEMES[(atual + 1) % len(THEMES)]
        self.theme = novo
        self.config.theme = novo
        self.config.save()
        self.notify(f"Tema: {novo}", timeout=3)

    def action_quit(self) -> None:
        ativos = any(j.status in Status.ATIVOS for j in self.jobs.values())
        if not ativos:
            self.exit()
            return

        def _cb(ok: bool | None) -> None:
            if ok:
                for job in self.jobs.values():
                    job.cancel.set()
                self.exit()

        self.push_screen(
            ConfirmScreen("Há downloads em andamento.\nSair mesmo assim?", botao_sim="Sair"), _cb
        )


def main() -> None:
    AVDownloaderApp().run()


if __name__ == "__main__":
    main()
