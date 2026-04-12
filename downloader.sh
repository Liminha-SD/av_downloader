#!/data/data/com.termux/files/usr/bin/bash
# YouTube/TikTok/Instagram Downloader v2.0 - MELHOR QUALIDADE SEMPRE
# Detecta automaticamente o site

# Configurações
VIDEOS_DIR="$HOME/storage/downloads/videos"
MUSICAS_DIR="$HOME/storage/downloads/musicas"
PLAYLISTS_DIR="$HOME/storage/downloads/playlists"
TIKTOK_DIR="$VIDEOS_DIR/TikTok"
INSTAGRAM_DIR="$VIDEOS_DIR/Instagram"

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

# ==============================================
# FUNÇÕES DE DOWNLOAD POR SITE (MELHOR QUALIDADE)
# ==============================================

baixar_youtube() {
    local url="$1"
    aviso "Iniciando download do YouTube na melhor qualidade..."
    
    if yt-dlp -f "bestvideo+bestaudio" \
           -o "$VIDEOS_DIR/YouTube/%(title)s [%(resolution)s].%(ext)s" \
           --embed-thumbnail \
           --embed-metadata \
           --embed-chapters \
           --convert-thumbnails jpg \
           --concurrent-fragments 5 \
           "$url"; then
        log "Download do YouTube concluído com sucesso!"
        return 0
    else
        erro "Falha ao baixar vídeo do YouTube."
        return 1
    fi
}

baixar_youtube_com_opcoes() {
    local url=$(solicitar_url "URL do YouTube")
    [[ $? -ne 0 ]] && return
    
    while true; do
        mostrar_banner
        echo -e "${CYAN}OPÇÕES DE QUALIDADE - YOUTUBE${NC}"
        echo ""
        echo -e "${CYAN}[1]${NC} 360p (rápido)"
        echo -e "${CYAN}[2]${NC} 480p (padrão)"
        echo -e "${CYAN}[3]${NC} 720p (HD)"
        echo -e "${CYAN}[4]${NC} 1080p (Full HD)"
        echo -e "${CYAN}[5]${NC} MELHOR QUALIDADE DISPONÍVEL"
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
        
        aviso "Baixando com qualidade selecionada e metadados..."
        if yt-dlp -f "$qualidade" \
               -o "$VIDEOS_DIR/YouTube/%(title)s [%(resolution)s].%(ext)s" \
               --embed-thumbnail \
               --embed-metadata \
               --convert-thumbnails jpg \
               "$url"; then
            log "Download concluído com sucesso!"
        else
            erro "Erro durante o download do YouTube."
        fi
        pausar
        break
    done
}

baixar_tiktok() {
    local url="$1"
    aviso "Baixando TikTok na MELHOR qualidade..."
    
    # Tentativa 1: Método normal
    if yt-dlp -f "best" \
              -o "$TIKTOK_DIR/%(title)s [%(id)s].%(ext)s" \
              --no-warnings \
              "$url" 2>/dev/null; then
        log "TikTok baixado com sucesso!"
        return 0
    fi
    
    # Tentativa 2: Com cookies
    aviso "Método 1 falhou. Tentando com cookies..."
    if yt-dlp --cookies-from-browser chrome \
              -f "best" \
              -o "$TIKTOK_DIR/%(title)s [%(id)s].%(ext)s" \
              --no-warnings \
              "$url" 2>/dev/null; then
        log "TikTok baixado via cookies com sucesso!"
        return 0
    fi
    
    # Tentativa 3: User-agent especial
    aviso "Método 2 falhou. Tentando método alternativo..."
    if yt-dlp --referer "https://www.tiktok.com/" \
              --user-agent "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36" \
              -f "best" \
              -o "$TIKTOK_DIR/%(title)s [%(id)s].%(ext)s" \
              "$url" 2>/dev/null; then
        log "TikTok baixado com sucesso (método alternativo)!"
        return 0
    fi
    
    # Tentativa 4: Usando API (último recurso)
    aviso "Método 3 falhou. Tentando API..."
    local video_id=$(echo "$url" | grep -o '[A-Za-z0-9]\{10,\}' | head -1)
    if [ -n "$video_id" ]; then
        local api_url="https://api.tiktokv.com/aweme/v1/aweme/detail/?aweme_id=$video_id"
        local video_url=$(curl -s "$api_url" | grep -o '"play_addr":"[^"]*"' | cut -d'"' -f4 | sed 's/\\\\\//\//g')
        
        if [ -n "$video_url" ]; then
            aviso "Encontrado via API. Baixando..."
            if wget -O "$TIKTOK_DIR/tiktok_$video_id.mp4" "$video_url"; then
                log "TikTok baixado via API com sucesso!"
                return 0
            fi
        fi
    fi
    
    erro "Não foi possível baixar o TikTok após várias tentativas."
    return 1
}

baixar_instagram() {
    local url="$1"
    aviso "Baixando Instagram na MELHOR qualidade..."
    
    if yt-dlp -f "best" \
           -o "$INSTAGRAM_DIR/%(title)s.%(ext)s" \
           --embed-metadata \
           "$url"; then
        log "Download do Instagram concluído com sucesso!"
        return 0
    else
        erro "Falha ao baixar do Instagram."
        return 1
    fi
}

baixar_universal() {
    local url="$1"
    local site="$2"
    aviso "Baixando $site na MELHOR qualidade disponível..."
    
    if yt-dlp -f "best" \
           -o "$VIDEOS_DIR/$site/%(title)s.%(ext)s" \
           --embed-metadata \
           "$url"; then
        log "Download de $site concluído com sucesso!"
        return 0
    else
        erro "Falha ao baixar de $site."
        return 1
    fi
}

# ==============================================
# FUNÇÃO PRINCIPAL INTELIGENTE (MELHOR QUALIDADE)
# ==============================================

baixar_inteligente() {
    mostrar_banner
    echo ""
    aviso "Cole a URL do vídeo (qualquer site):"
    echo "Ex: YouTube, TikTok, Instagram, Twitter, etc."
    echo ""
    echo -e "${GREEN}DOWNLOAD NA MELHOR QUALIDADE DISPONÍVEL${NC}"
    echo ""
    
    local url=$(solicitar_url "URL")
    [[ $? -ne 0 ]] && return
    
    # Detectar site
    local site=$(detectar_site "$url")
    aviso "Site detectado: $site"
    
    # Criar pastas específicas
    mkdir -p "$VIDEOS_DIR/$site"
    
    # Baixar conforme o site
    case "$site" in
        YouTube)
            baixar_youtube "$url"
            ;;
        TikTok)
            baixar_tiktok "$url"
            ;;
        Instagram)
            baixar_instagram "$url"
            ;;
        *)
            baixar_universal "$url" "$site"
            ;;
    esac
    
    pausar
}

# ==============================================
# FUNÇÕES ESPECÍFICAS (para o menu)
# ==============================================

baixar_mp3_universal() {
    mostrar_banner
    echo ""
    echo -e "${GREEN}CONVERTER PARA MP3 - MELHOR QUALIDADE${NC}"
    echo ""
    
    local url=$(solicitar_url "Cole a URL para converter em MP3")
    [[ $? -ne 0 ]] && return
    
    # SEMPRE usa 320k (melhor qualidade para MP3)
    local bitrate="320K"
    
    aviso "Convertendo para MP3 (320k) e embutindo metadados..."
    if yt-dlp -x --audio-format mp3 \
           --audio-quality "$bitrate" \
           -o "$MUSICAS_DIR/%(title)s.%(ext)s" \
           --embed-thumbnail \
           --embed-metadata \
           --convert-thumbnails jpg \
           --parse-metadata "uploader:%(artist)s" \
           --parse-metadata "uploader:%(album)s" \
           --parse-metadata "title:%(title)s" \
           "$url"; then
        log "Conversão para MP3 concluída com sucesso!"
    else
        erro "Falha na conversão para MP3."
    fi
    
    pausar
}

ver_downloads() {
    mostrar_banner
    echo ""
    echo -e "${CYAN}CONTEÚDO BAIXADO (MELHOR QUALIDADE)${NC}"
    echo ""
    
    # Lista organizada
    for pasta in "$VIDEOS_DIR"/* "$MUSICAS_DIR"; do
        if [ -d "$pasta" ]; then
            local nome=$(basename "$pasta")
            local quantidade=$(ls "$pasta" 2>/dev/null | wc -l)
            if [ "$quantidade" -gt 0 ]; then
                local tamanho=$(du -sh "$pasta" 2>/dev/null | cut -f1)
                echo -e "${YELLOW}$nome:${NC}"
                echo -e "  Arquivos: $quantidade | Tamanho: $tamanho"
                ls -lh "$pasta" | head -n 4 | grep -v "^total" | while read linha; do
                    echo "  • $linha"
                done
                if [ $quantidade -gt 3 ]; then
                    echo "  ... e mais $(($quantidade - 3)) arquivos"
                fi
                echo ""
            fi
        fi
    done
    
    # Espaço em disco
    echo -e "${CYAN}ESPAÇO DISPONÍVEL:${NC}"
    df -h | grep -E "Use%|/storage"
    
    pausar
}

menu_config() {
    while true; do
        mostrar_banner
        echo ""
        echo -e "${CYAN}CONFIGURAÇÕES - MELHOR QUALIDADE${NC}"
        echo ""
        echo -e "${CYAN}[1]${NC} Atualizar yt-dlp"
        echo -e "${CYAN}[2]${NC} Instalar dependências extras"
        echo -e "${CYAN}[3]${NC} Informações de qualidade"
        echo -e "${CYAN}[4]${NC} Limpar cache"
        echo -e "${CYAN}[5]${NC} Testar velocidade de download"
        echo -e "${RED}[0]${NC} Voltar"
        
        read -p "Opção: " opcao
        
        case $opcao in
            1)
                aviso "Atualizando yt-dlp..."
                if pip install --upgrade yt-dlp; then
                    log "yt-dlp atualizado. Versão atual: $(yt-dlp --version)"
                else
                    erro "Falha ao atualizar yt-dlp."
                fi
                pausar
                ;;
            2)
                aviso "Instalando dependências..."
                if pkg install python ffmpeg curl wget -y && pip install yt-dlp[default]; then
                    log "Dependências instaladas com sucesso!"
                else
                    erro "Erro ao instalar dependências."
                fi
                pausar
                ;;
            3)
                echo ""
                echo -e "${GREEN}Configuração de Qualidade:${NC}"
                echo "Atualmente: MELHOR QUALIDADE SEMPRE"
                echo ""
                echo "O sistema está configurado para sempre usar:"
                echo "- YouTube: melhor vídeo + melhor áudio disponível"
                echo "- TikTok/Instagram: melhor arquivo direto"
                echo "- MP3: taxa de bits constante de 320k"
                pausar
                ;;
            4)
                aviso "Limpando cache..."
                yt-dlp --rm-cache-dir
                rm -rf ~/.cache/yt-dlp/*
                log "Cache limpo com sucesso!"
                pausar
                ;;
            5)
                aviso "Testando velocidade..."
                curl -o /dev/null -w "Velocidade: %{speed_download} bytes/seg\n" https://speedtest.selectel.ru/10MB.bin
                pausar
                ;;
            0)
                return
                ;;
            *)
                erro "Opção inválida!"
                sleep 1
                ;;
        esac
    done
}

# ==============================================
# MENU PRINCIPAL
# ==============================================

main() {
    # Criar estrutura de pastas
    mkdir -p "$VIDEOS_DIR"/{YouTube,TikTok,Instagram,Twitter,Facebook,Twitch,Pinterest,Outros}
    mkdir -p "$MUSICAS_DIR" "$PLAYLISTS_DIR"
    
    # Verificar dependências
    if ! command -v yt-dlp &> /dev/null; then
        erro "yt-dlp não está instalado!"
        aviso "Tentando instalação automática..."
        pkg install python ffmpeg -y
        pip install yt-dlp[default]
    fi
    
    while true; do
        mostrar_banner
        
        echo -e "${GREEN}DOWNLOAD NA MELHOR QUALIDADE${NC}"
        echo ""
        echo -e "${CYAN}[1]${NC} Baixar QUALQUER vídeo (MELHOR qualidade)"
        echo -e "${CYAN}[2]${NC} Baixar YouTube (com opções)"
        echo -e "${CYAN}[3]${NC} Converter para MP3 (320k - MELHOR)"
        echo -e "${CYAN}[4]${NC} Ver downloads"
        echo -e "${CYAN}[5]${NC} Configurações"
        echo -e "${RED}[0]${NC} Sair"
        echo ""
        echo -e "${YELLOW}════════════════════════════════════════${NC}"
        echo ""
        
        read -p "Digite a opção: " opcao
        
        case $opcao in
            1) baixar_inteligente ;;
            2) baixar_youtube_com_opcoes ;;
            3) baixar_mp3_universal ;;
            4) ver_downloads ;;
            5) menu_config ;;
            0|sair|exit)
                echo ""
                log "Saindo do script. Até logo!"
                exit 0
                ;;
            *)
                erro "Opção inválida!"
                sleep 1
                ;;
        esac
    done
}

# Iniciar
main
