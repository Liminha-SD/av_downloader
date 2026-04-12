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
log() { echo -e "${GREEN}[+]${NC} $1"; }
erro() { echo -e "${RED}[!]${NC} $1"; }
aviso() { echo -e "${YELLOW}[i]${NC} $1"; }

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
    
    echo -e "${YELLOW}Tip: Digite '0' ou deixe vazio para voltar${NC}"
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
    log "Baixando YouTube na MELHOR qualidade + Metadados completos..."
    
    yt-dlp -f "bestvideo+bestaudio" \
           -o "$VIDEOS_DIR/YouTube/%(title)s [%(resolution)s].%(ext)s" \
           --embed-thumbnail \
           --embed-metadata \
           --embed-chapters \
           --convert-thumbnails jpg \
           --concurrent-fragments 5 \
           "$url"
}

baixar_youtube_com_opcoes() {
    local url=$(solicitar_url "URL do YouTube")
    [[ $? -ne 0 ]] && return
    
    while true; do
        mostrar_banner
        echo -e "${CYAN}📺 OPÇÕES DE QUALIDADE - YOUTUBE${NC}"
        echo ""
        echo "1) 360p (rápido)"
        echo "2) 480p (padrão)"
        echo "3) 720p (HD)"
        echo "4) 1080p (Full HD)"
        echo "5) 🔥 MELHOR QUALIDADE DISPONÍVEL"
        echo "0) Voltar"
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
        
        log "Baixando do YouTube com metadados..."
        yt-dlp -f "$qualidade" \
               -o "$VIDEOS_DIR/YouTube/%(title)s [%(resolution)s].%(ext)s" \
               --embed-thumbnail \
               --embed-metadata \
               --convert-thumbnails jpg \
               "$url"
        pausar
        break
    done
}

baixar_tiktok() {
    local url="$1"
    log "Baixando TikTok na MELHOR qualidade..."
    
    # Tentativa 1: Método normal - MELHOR QUALIDADE
    if yt-dlp -f "best" \
              -o "$TIKTOK_DIR/%(title)s [%(id)s].%(ext)s" \
              --no-warnings \
              "$url" 2>/dev/null; then
        log "✅ TikTok baixado na melhor qualidade!"
        return 0
    fi
    
    # Tentativa 2: Com cookies - MELHOR QUALIDADE
    aviso "Método 1 falhou. Tentando com cookies..."
    if yt-dlp --cookies-from-browser chrome \
              -f "best" \
              -o "$TIKTOK_DIR/%(title)s [%(id)s].%(ext)s" \
              --no-warnings \
              "$url" 2>/dev/null; then
        log "✅ TikTok baixado via cookies na melhor qualidade!"
        return 0
    fi
    
    # Tentativa 3: User-agent especial - MELHOR QUALIDADE
    aviso "Método 2 falhou. Tentando método alternativo..."
    if yt-dlp --referer "https://www.tiktok.com/" \
              --user-agent "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36" \
              -f "best" \
              -o "$TIKTOK_DIR/%(title)s [%(id)s].%(ext)s" \
              "$url" 2>/dev/null; then
        log "✅ TikTok baixado na melhor qualidade (método alternativo)!"
        return 0
    fi
    
    # Tentativa 4: Usando API (último recurso)
    aviso "Método 3 falhou. Tentando API..."
    local video_id=$(echo "$url" | grep -o '[A-Za-z0-9]\{10,\}' | head -1)
    if [ -n "$video_id" ]; then
        local api_url="https://api.tiktokv.com/aweme/v1/aweme/detail/?aweme_id=$video_id"
        local video_url=$(curl -s "$api_url" | grep -o '"play_addr":"[^"]*"' | cut -d'"' -f4 | sed 's/\\\\\//\//g')
        
        if [ -n "$video_url" ]; then
            log "Encontrado via API. Baixando na melhor qualidade..."
            wget -O "$TIKTOK_DIR/tiktok_$video_id.mp4" "$video_url"
            return $?
        fi
    fi
    
    erro "Não foi possível baixar o TikTok"
    return 1
}

baixar_instagram() {
    local url="$1"
    log "Baixando Instagram na MELHOR qualidade..."
    
    yt-dlp -f "best" \
           -o "$INSTAGRAM_DIR/%(title)s.%(ext)s" \
           --add-metadata \
           "$url"
}

baixar_universal() {
    local url="$1"
    local site="$2"
    log "Baixando $site na MELHOR qualidade disponível..."
    
    yt-dlp -f "best" \
           -o "$VIDEOS_DIR/$site/%(title)s.%(ext)s" \
           --add-metadata \
           "$url"
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
    echo -e "${GREEN}🚀 SERÁ BAIXADO NA MELHOR QUALIDADE DISPONÍVEL${NC}"
    echo ""
    
    local url=$(solicitar_url "URL")
    [[ $? -ne 0 ]] && return
    
    # Detectar site
    local site=$(detectar_site "$url")
    log "Site detectado: $site"
    
    # Criar pastas específicas
    mkdir -p "$VIDEOS_DIR/$site"
    
    # Baixar conforme o site - SEMPRE MELHOR QUALIDADE
    local status=0
    case "$site" in
        YouTube)
            baixar_youtube "$url"
            status=$?
            ;;
        TikTok)
            baixar_tiktok "$url"
            status=$?
            ;;
        Instagram)
            baixar_instagram "$url"
            status=$?
            ;;
        *)
            baixar_universal "$url" "$site"
            status=$?
            ;;
    esac
    
    if [ $status -eq 0 ]; then
        log "✅ Download concluído na MELHOR qualidade!"
    else
        erro "❌ Falha no download. Tente outro método."
    fi
    
    pausar
}

# ==============================================
# FUNÇÕES ESPECÍFICAS (para o menu)
# ==============================================

baixar_mp3_universal() {
    mostrar_banner
    echo ""
    echo -e "${GREEN}🎵 CONVERTER PARA MP3 - MELHOR QUALIDADE${NC}"
    echo ""
    
    local url=$(solicitar_url "Cole a URL para converter em MP3")
    [[ $? -ne 0 ]] && return
    
    # SEMPRE usa 320k (melhor qualidade para MP3)
    local bitrate="320K"
    
    log "Convertendo para MP3 na melhor qualidade (320k)..."
    yt-dlp -x --audio-format mp3 \
           --audio-quality "$bitrate" \
           -o "$MUSICAS_DIR/%(title)s.%(ext)s" \
           --embed-thumbnail \
           --add-metadata \
           --parse-metadata "title:%(title)s" \
           --parse-metadata "artist:%(uploader)s" \
           "$url"
    
    pausar
}

ver_downloads() {
    mostrar_banner
    echo ""
    echo -e "${CYAN}📁 CONTEÚDO BAIXADO (MELHOR QUALIDADE)${NC}"
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
    echo -e "${CYAN}💾 ESPAÇO DISPONÍVEL:${NC}"
    df -h | grep -E "Use%|/storage"
    
    pausar
}

menu_config() {
    while true; do
        mostrar_banner
        echo ""
        echo -e "${CYAN}⚙️  CONFIGURAÇÕES - MELHOR QUALIDADE${NC}"
        echo ""
        echo "1) Atualizar yt-dlp (para suporte máximo)"
        echo "2) Instalar dependências extras"
        echo "3) Informações de qualidade"
        echo "4) Limpar cache"
        echo "5) Testar velocidade de download"
        echo "0) Voltar"
        
        read -p "Opção: " opcao
        
        case $opcao in
            1)
                log "Atualizando yt-dlp para versão mais recente..."
                pip install --upgrade yt-dlp
                log "✅ Versão atual: $(yt-dlp --version)"
                pausar
                ;;
            2)
                log "Instalando dependências para melhor qualidade..."
                pkg install python ffmpeg curl wget -y
                pip install yt-dlp[default]
                log "✅ Dependências instaladas!"
                pausar
                ;;
            3)
                echo ""
                echo -e "${GREEN}Configurar Qualidade Padrão:${NC}"
                echo "Atualmente: MELHOR QUALIDADE SEMPRE"
                echo ""
                echo "O sistema está configurado para sempre usar:"
                echo "- YouTube: bestvideo+bestaudio"
                echo "- TikTok/Instagram: best"
                echo "- MP3: 320k"
                pausar
                ;;
            4)
                log "Limpando cache..."
                yt-dlp --rm-cache-dir
                rm -rf ~/.cache/yt-dlp/*
                log "✅ Cache limpo!"
                pausar
                ;;
            5)
                log "Testando velocidade..."
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
        aviso "Instalando..."
        pkg install python ffmpeg -y
        pip install yt-dlp[default]
    fi
    
    while true; do
        mostrar_banner
        
        echo -e "${GREEN}🚀 DOWNLOAD NA MELHOR QUALIDADE${NC}"
        echo ""
        echo -e "🎯 ${CYAN}[1]${NC} Baixar QUALQUER vídeo (MELHOR qualidade)"
        echo -e "📥 ${CYAN}[2]${NC} Baixar YouTube (com opções)"
        echo -e "🎵 ${CYAN}[3]${NC} Converter para MP3 (320k - MELHOR)"
        echo -e "📊 ${CYAN}[4]${NC} Ver downloads"
        echo -e "⚙️  ${CYAN}[5]${NC} Configurações"
        echo -e "🚪 ${RED}[0]${NC} Sair"
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
                log "Até logo! 👋"
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
