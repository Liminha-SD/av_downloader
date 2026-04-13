#!/data/data/com.termux/files/usr/bin/bash
# YouTube/TikTok/Instagram Downloader v2.0 - MELHOR QUALIDADE SEMPRE
# Detecta automaticamente o site

# Configurações iniciais
VIDEOS_DIR="$HOME/storage/downloads/videos"
MUSICAS_DIR="$HOME/storage/downloads/musicas"
PLAYLISTS_DIR="$HOME/storage/downloads/playlists"
TIKTOK_DIR="$VIDEOS_DIR/TikTok"
INSTAGRAM_DIR="$VIDEOS_DIR/Instagram"
COOKIES_FILE="$HOME/storage/downloads/cookies.txt"
MAX_SIMULTANEOS=2
YT_DLP_OPTS=""

# Cores
RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
PURPLE='\033[1;35m'
CYAN='\033[1;36m'
NC='\033[0m'

# Funções de utilidade
limpar() { clear; }
pausar() { read -p "Pressione ENTER para continuar..."; }
log() { echo -e "${GREEN}[+] $1${NC}"; }
erro() { echo -e "${RED}[!] $1${NC}"; }
aviso() { echo -e "${YELLOW}[i] $1${NC}"; }

verificar_cookies() {
    if [[ -f "$COOKIES_FILE" ]]; then
        # Proteção: Ajusta permissões para que apenas o dono do arquivo possa ler/escrever
        chmod 600 "$COOKIES_FILE" 2>/dev/null
        
        # Validação básica: Verifica se o arquivo parece ser um formato de cookies válido para o yt-dlp
        if grep -qE "Netscape|cookiestxt" "$COOKIES_FILE"; then
            YT_DLP_OPTS="--cookies $COOKIES_FILE"
            log "Cookies ativos e protegidos: $COOKIES_FILE"
        else
            YT_DLP_OPTS=""
            erro "Arquivo de cookies em: $COOKIES_FILE parece inválido!"
            aviso "Dica: Exportar do navegador no formato Netscape/cookies.txt"
        fi
    else
        YT_DLP_OPTS=""
        aviso "Cookies inativos (arquivo não encontrado em: $COOKIES_FILE)"
    fi
}

# Banner
mostrar_banner() {
    limpar
    echo -e "${CYAN}"
    echo "╔══════════════════════════════════════════════╗"
    echo "║            DOWNLOADER UNIVERSAL              ║"
    echo "║           MELHOR QUALIDADE SEMPRE!           ║"
    echo "╚══════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# ==============================================
# FUNÇÕES DE DETECÇÃO E UTILITÁRIOS
# ==============================================

detectar_site() {
    local url="$1"
    case "$url" in
        *youtube.com*|*youtu.be*) echo "YouTube" ;;
        *tiktok.com*|*vt.tiktok.com*) echo "TikTok" ;;
        *instagram.com*|*instagr.am*) echo "Instagram" ;;
        *twitter.com*|*x.com*|*t.co*) echo "Twitter" ;;
        *facebook.com*|*fb.watch*) echo "Facebook" ;;
        *twitch.tv*) echo "Twitch" ;;
        *pinterest.com*|*pin.it*) echo "Pinterest" ;;
        *) echo "Outros" ;;
    esac
}

solicitar_url() {
    local prompt_msg="$1"
    local url
    echo -e "${YELLOW}Dica: Digite '0' ou deixe vazio para voltar${NC}" >&2
    read -p "$prompt_msg: " url
    if [[ -z "$url" || "$url" == "0" ]]; then
        return 1
    fi
    echo "$url"
    return 0
}

solicitar_formato() {
    while true; do
        echo "" >&2
        echo -e "${CYAN}Escolha o formato do download:${NC}" >&2
        echo -e "${CYAN}[1]${NC} Video" >&2
        echo -e "${CYAN}[2]${NC} Audio (MP3)" >&2
        echo -e "${RED}[0]${NC} Voltar" >&2
        echo "" >&2
        read -p "Opção: " fmt
        case $fmt in
            1) echo "video"; return 0 ;;
            2) echo "audio"; return 0 ;;
            0) return 1 ;;
            *) erro "Opção inválida!"; sleep 1 ;;
        esac
    done
}

# ==============================================
# FUNÇÕES DE DOWNLOAD POR SITE (MELHOR QUALIDADE)
# ==============================================

baixar_youtube() {
    local url="$1"
    aviso "Iniciando download na melhor qualidade..."
    if yt-dlp $YT_DLP_OPTS -f "bestvideo+bestaudio/best" \
           -o "$VIDEOS_DIR/YouTube/%(title)s [%(resolution)s].%(ext)s" \
           --embed-thumbnail --embed-metadata --embed-chapters \
           --convert-thumbnails jpg --concurrent-fragments 5 --no-playlist "$url"; then
        log "Download concluído!"
        return 0
    else
        erro "Falha no download."
        return 1
    fi
}

baixar_playlist_youtube() {
    mostrar_banner
    echo -e "${GREEN}BAIXAR PLAYLIST OU CANAL COMPLETO${NC}"
    echo ""
    local url=$(solicitar_url "Cole a URL da Playlist ou Canal")
    [[ $? -ne 0 ]] && return

    local formato=$(solicitar_formato)
    [[ $? -ne 0 ]] && return

    aviso "Obtendo informações da fonte... Aguarde."
    # Obtém o nome da playlist ou canal
    local playlist_name=$(yt-dlp $YT_DLP_OPTS --print "%(playlist_title,uploader,channel)s" --no-warnings --playlist-items 1 "$url" | head -1)
    [[ -z "$playlist_name" || "$playlist_name" == "NA" ]] && playlist_name="Download_Playlist"
    
    # Limpa caracteres inválidos para nomes de pasta e remove sufixos indesejados
    playlist_name=$(echo "$playlist_name" | sed -E 's/ - ([Vv]ide[oó]s?|[Vv]ídeos)//g' | sed 's/[<>:"/\\|?*]//g')

    aviso "Coletando links de '$playlist_name'..."
    local lista_urls=$(yt-dlp $YT_DLP_OPTS --flat-playlist --get-url --no-warnings "$url")
    local total=$(echo "$lista_urls" | wc -l)
    
    log "Encontrados $total vídeos. Baixando $MAX_SIMULTANEOS por vez..."
    mkdir -p "$PLAYLISTS_DIR/$playlist_name"
    
    local count=0
    for vid_url in $lista_urls; do
        ((count++))
        (
            local output_template="$PLAYLISTS_DIR/$playlist_name/%(title)s.%(ext)s"
            if [[ "$formato" == "audio" ]]; then
                yt-dlp $YT_DLP_OPTS -x --audio-format mp3 --audio-quality 320K -o "$output_template" \
                       --embed-thumbnail --embed-metadata --convert-thumbnails jpg \
                       --parse-metadata "uploader:%(artist)s" --parse-metadata "uploader:%(album)s" \
                       --no-warnings --quiet "$vid_url"
            else
                yt-dlp $YT_DLP_OPTS -f "bestvideo+bestaudio/best" -o "$output_template" \
                       --embed-thumbnail --embed-metadata --convert-thumbnails jpg \
                       --no-warnings --quiet "$vid_url"
            fi
            echo -e "${GREEN}[OK] Item $count/$total finalizado${NC}"
        ) &

        # Controle de concorrência
        while [ $(jobs -r | wc -l) -ge "$MAX_SIMULTANEOS" ]; do
            sleep 2
        done
    done
    
    wait
    log "Playlist '$playlist_name' concluída com sucesso!"
    pausar
}

baixar_youtube_com_opcoes() {
    local url=$(solicitar_url "URL do YouTube")
    [[ $? -ne 0 ]] && return
    
    while true; do
        mostrar_banner
        echo -e "${CYAN}OPÇÕES DE QUALIDADE - YOUTUBE${NC}"
        echo ""
        echo -e "${CYAN}[1]${NC} 360p"
        echo -e "${CYAN}[2]${NC} 480p"
        echo -e "${CYAN}[3]${NC} 720p"
        echo -e "${CYAN}[4]${NC} 1080p"
        echo -e "${CYAN}[5]${NC} MELHOR"
        echo -e "${RED}[0]${NC} Voltar"
        echo ""
        read -p "Opção: " qual
        
        local qualidade
        case $qual in
            1) qualidade="best[height<=360]" ;;
            2) qualidade="best[height<=480]" ;;
            3) qualidade="best[height<=720]" ;;
            4) qualidade="best[height<=1080]" ;;
            5) qualidade="bestvideo+bestaudio" ;;
            0) return ;;
            *) erro "Opção inválida!"; sleep 1; continue ;;
        esac
        
        aviso "Baixando..."
        yt-dlp $YT_DLP_OPTS -f "$qualidade" -o "$VIDEOS_DIR/YouTube/%(title)s.%(ext)s" \
               --embed-thumbnail --embed-metadata --convert-thumbnails jpg --no-playlist "$url"
        pausar
        break
    done
}

baixar_tiktok() {
    local url="$1"
    aviso "Baixando TikTok..."
    if yt-dlp $YT_DLP_OPTS -f "best" -o "$TIKTOK_DIR/%(title)s.%(ext)s" --no-warnings "$url" 2>/dev/null; then
        log "TikTok concluído!"
    else
        erro "Falha no TikTok."
    fi
}

baixar_instagram() {
    local url="$1"
    aviso "Baixando Instagram..."
    if yt-dlp $YT_DLP_OPTS -f "best" -o "$INSTAGRAM_DIR/%(title)s.%(ext)s" --embed-metadata "$url"; then
        log "Instagram concluído!"
    else
        erro "Falha no Instagram."
    fi
}

baixar_universal() {
    local url="$1"
    local site="$2"
    aviso "Baixando $site..."
    if yt-dlp $YT_DLP_OPTS -f "best" -o "$VIDEOS_DIR/$site/%(title)s.%(ext)s" --embed-metadata "$url"; then
        log "Download concluído!"
    else
        erro "Falha no download."
    fi
}

baixar_inteligente() {
    mostrar_banner
    echo ""
    local url=$(solicitar_url "URL do Vídeo")
    [[ $? -ne 0 ]] && return
    
    local site=$(detectar_site "$url")
    mkdir -p "$VIDEOS_DIR/$site"
    
    case "$site" in
        YouTube) baixar_youtube "$url" ;;
        TikTok) baixar_tiktok "$url" ;;
        Instagram) baixar_instagram "$url" ;;
        *) baixar_universal "$url" "$site" ;;
    esac
    pausar
}

# ==============================================
# FUNÇÕES DE CONFIGURAÇÃO E MENU
# ==============================================

baixar_mp3_universal() {
    mostrar_banner
    echo ""
    echo -e "${GREEN}CONVERTER PARA MP3 (320K)${NC}"
    echo ""
    local url=$(solicitar_url "Cole a URL")
    [[ $? -ne 0 ]] && return
    
    aviso "Processando áudio..."
    yt-dlp $YT_DLP_OPTS -x --audio-format mp3 --audio-quality 320K -o "$MUSICAS_DIR/%(title)s.%(ext)s" \
           --embed-thumbnail --embed-metadata --convert-thumbnails jpg \
           --parse-metadata "uploader:%(artist)s" --parse-metadata "uploader:%(album)s" "$url"
    pausar
}

ver_downloads() {
    mostrar_banner
    echo -e "${CYAN}DOWNLOADS REALIZADOS${NC}\n"
    for pasta in "$VIDEOS_DIR"/* "$MUSICAS_DIR" "$PLAYLISTS_DIR"; do
        if [ -d "$pasta" ]; then
            local nome=$(basename "$pasta")
            local quantidade=$(find "$pasta" -type f 2>/dev/null | wc -l)
            if [ "$quantidade" -gt 0 ]; then
                echo -e "${YELLOW}$nome: $quantidade arquivos (${NC}$(du -sh "$pasta" | cut -f1)${YELLOW})${NC}"
            fi
        fi
    done
    echo -e "\n${CYAN}Espaço livre: $(df -h /storage/emulated 2>/dev/null | tail -1 | awk '{print $4}')${NC}"
    pausar
}

menu_config() {
    while true; do
        mostrar_banner
        echo -e "${CYAN}CONFIGURAÇÕES DO SISTEMA${NC}\n"
        echo -e "[1] Atualizar yt-dlp"
        echo -e "[2] Instalar dependências"
        echo -e "[3] Limpar cache"
        echo -e "[4] Downloads Simultâneos (Playlist): $MAX_SIMULTANEOS"
        echo -e "[5] Verificar/Ativar Cookies (Arquivo: $COOKIES_FILE)"
        echo -e "${RED}[0] Voltar${NC}"
        echo ""
        read -p "Opção: " opcao
        case $opcao in
            1) pip install --upgrade yt-dlp && log "Atualizado!" ; pausar ;;
            2) pkg install python ffmpeg curl wget -y && pip install yt-dlp[default] ; pausar ;;
            3) yt-dlp $YT_DLP_OPTS --rm-cache-dir ; rm -rf ~/.cache/yt-dlp/* ; log "Limpo!" ; pausar ;;
            4) read -p "Quantos vídeos baixar por vez? (Sugerido: 2-3): " num
               if [[ "$num" =~ ^[0-9]+$ ]]; then MAX_SIMULTANEOS=$num ; log "Alterado!" ; else erro "Incorreto!" ; fi ; sleep 1 ;;
            5) verificar_cookies ; pausar ;;
            0) return ;;
            *) erro "Opção inválida!" ; sleep 1 ;;
        esac
    done
}

main() {
    mkdir -p "$VIDEOS_DIR"/{YouTube,TikTok,Instagram,Twitter,Facebook,Twitch,Pinterest,Outros}
    mkdir -p "$MUSICAS_DIR" "$PLAYLISTS_DIR"
    verificar_cookies
    
    while true; do
        mostrar_banner
        echo -e "${GREEN}DOWNLOADER UNIVERSAL v2.0${NC}\n"
        echo -e "${CYAN}[1]${NC} Baixar vídeo individual"
        echo -e "${CYAN}[2]${NC} Baixar YouTube (Escolher qualidade)"
        echo -e "${CYAN}[3]${NC} Baixar Playlist ou Canal (Completo)"
        echo -e "${CYAN}[4]${NC} Converter link para MP3 (320k)"
        echo -e "${CYAN}[5]${NC} Ver downloads"
        echo -e "${CYAN}[6]${NC} Configurações"
        echo -e "${RED}[0]${NC} Sair"
        echo ""
        read -p "Digite a opção: " opcao
        case $opcao in
            1) baixar_inteligente ;;
            2) baixar_youtube_com_opcoes ;;
            3) baixar_playlist_youtube ;;
            4) baixar_mp3_universal ;;
            5) ver_downloads ;;
            6) menu_config ;;
            0) log "Até logo!" ; exit 0 ;;
            *) erro "Opção inválida!" ; sleep 1 ;;
        esac
    done
}

main
