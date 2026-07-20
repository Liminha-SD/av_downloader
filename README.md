# AV Downloader

TUI elegante para baixar vídeos e músicas na melhor qualidade, com fila de
downloads paralelos, progresso em tempo real, histórico e temas. Construído
com [Textual](https://textual.textualize.io/) + [yt-dlp](https://github.com/yt-dlp/yt-dlp).
Funciona no **Termux** (Android) e no **desktop** (Linux/macOS).

```
▄▀█ █░█ · █▀▄ █░░
█▀█ ░▀░ · █▄▀ █▄▄
vídeos & músicas · melhor qualidade sempre
```

## Recursos

- **Detecção automática de site** — YouTube, TikTok, Instagram, Twitter/X,
  Facebook, Twitch, Pinterest, Reddit, Vimeo, SoundCloud e qualquer outro site
  suportado pelo yt-dlp.
- **Fila com downloads paralelos** — vários downloads ao mesmo tempo, com
  barra de progresso, velocidade e ETA por item, ao vivo.
- **Playlists e canais** — cada item vira uma linha na fila, com pasta
  própria. Em links de vídeo dentro de playlist, você escolhe se quer só o
  vídeo ou a playlist inteira.
- **Sem Shorts junto** — ao baixar uma playlist ou um canal, os Shorts do
  YouTube ficam de fora (vídeo e áudio); eles só são baixados quando você
  cola o link do Short ou da aba `/shorts`. Desligável nas Configurações.
- **Não baixa o que você já tem** — antes de montar a fila, o app lê a pasta
  de destino e pula o que já está lá (mostra "440 novos de 445"). Vale para
  arquivos baixados por versões anteriores e pelo script antigo.
- **Qualidade sob controle** — melhor qualidade (vídeo+áudio mesclados) ou
  limite de 1080p/720p/480p/360p.
- **Conversão para MP3** — 128 a 320 kbps, com thumbnail e metadados
  incorporados.
- **Histórico persistente** — tudo que você já baixou, com data e tamanho.
- **Configurações persistentes** — pasta base, cookies, downloads
  simultâneos, qualidade do áudio.
- **Cookies** — suporte a `cookies.txt` (formato Netscape) para conteúdo
  que exige login, com validação do arquivo.
- **Atualização automática do yt-dlp** — ao iniciar, o app atualiza o yt-dlp
  em segundo plano (dentro da venv), mostrando o andamento na barra de
  status; desligável nas Configurações. Sites quebram extractors o tempo
  todo — manter o yt-dlp em dia é o que mais evita falha de download.
- **Temas** — o tema padrão `luna` segue a paleta dos meus programas
  (fundo `#0F0F0F` + azul `#019DEA`); alterne para tokyo-night, catppuccin,
  dracula, nord, gruvbox e outros com uma tecla.
- **Cancelar e repetir** — cancele itens da fila e repita os que falharam.

## Instalação

### Termux (Android)

```sh
pkg install python ffmpeg termux-api
termux-setup-storage
pip install -U yt-dlp textual
```

### Linux / macOS

A versão do Python do projeto está fixada em [`.python-version`](.python-version)
(3.13.14, via pyenv). Instale o ffmpeg pelo gerenciador de pacotes
(ex.: `pacman -S ffmpeg` / `apt install ffmpeg`) e depois crie a venv do
projeto (pasta `venv`, na raiz):

```sh
python -m venv venv
venv/bin/python -m pip install -r requirements.txt
```

> **Nota:** em discos NTFS/exFAT os scripts `venv/bin/pip` e `activate` não
> recebem bit de execução — por isso os comandos acima usam sempre
> `venv/bin/python -m pip`, que funciona em qualquer disco.

## Uso

```sh
python main.py
```

Não é preciso ativar a venv: o `main.py` detecta a pasta `venv/` ao lado dele
e **se re-executa sozinho com o python dela** (auto-bootstrap). Funciona
iniciado por qualquer interpretador, atalho ou `.desktop`. No Termux, sem
`venv/`, ele roda com o python do sistema normalmente.

Cole uma URL, aperte **Enter**, escolha o formato e pronto — o download entra
na fila. Downloads ficam em `~/Downloads/av-downloader` (desktop) ou
`/sdcard/Download/av-downloader` (Termux), organizados assim:

```
av-downloader/
├── videos/<Site>/     vídeos avulsos, por site
├── musicas/           MP3 avulsos
└── playlists/<Nome>/  playlists e canais completos
```

### Atalhos de teclado

| Tecla | Ação |
|-------|------|
| `Enter` | Analisar a URL digitada |
| `a` | Nova URL (focar o campo de digitação) |
| `Esc` | Ir para a fila (ativa os atalhos de letra) |
| `v` | Colar URL da área de transferência |
| `x` | Cancelar o item selecionado na fila |
| `r` | Repetir item com erro ou cancelado |
| `l` | Limpar itens concluídos da fila |
| `o` | Abrir a pasta de downloads |
| `h` | Histórico de downloads |
| `s` | Configurações |
| `t` | Alternar tema visual |
| `?` | Ajuda |
| `q` | Sair |

### Como os Shorts são identificados

Em playlists (inclusive na lista de uploads do canal) os Shorts aparecem como
vídeos comuns — a URL não os diferencia e a duração também não, já que um
Short pode ter até 3 minutos. O app resolve assim, do mais barato ao mais
caro:

1. URL contendo `/shorts/` — é Short, sem custo;
2. duração acima de 3 minutos — não é Short, sem custo (resolve a maioria);
3. só o que sobra é confirmado em `youtube.com/shorts/<id>`, que responde
   `200` para Short e redireciona para vídeo comum — em paralelo, ~0,2s por
   item.

Para URL de canal, o app usa a aba **Videos** (que já não contém Shorts),
sem custo nenhum.

### Como o app sabe o que já foi baixado

A verificação é feita **na própria pasta de destino**, combinando duas fontes:

1. **Nome do arquivo** — o título do vídeo é convertido em nome de arquivo com
   a mesma função do yt-dlp, então arquivos antigos (baixados antes desta
   funcionalidade, ou pelo `downloader.sh`) também são reconhecidos.
2. **Registro `.avd-baixados.json`** — arquivo oculto dentro da pasta, com o
   ID de cada vídeo baixado. Como acompanha a pasta, sobrevive a
   reinstalações; e como é por ID, continua valendo se o autor renomear o
   vídeo no YouTube (algo comum — canais testam títulos o tempo todo).

Regras que valem a pena saber:

- **Apagou o arquivo, baixa de novo**: o registro só conta se o arquivo ainda
  estiver na pasta.
- **Áudio e vídeo contam separado**: ter o MP4 não impede baixar o MP3.
- Para um vídeo avulso que você já tem, o botão vira **"Baixar de novo"** —
  a decisão continua sendo sua.

### Cookies (conteúdo com login)

Exporte os cookies do navegador no formato Netscape (`cookies.txt`) e informe
o caminho em **Configurações** (`s`). O padrão é
`~/storage/downloads/cookies.txt` no Termux e `~/cookies.txt` no desktop.

## Arquivos

- Configuração: `~/.config/av-downloader/config.json`
- Histórico: `~/.config/av-downloader/historico.json`
- Padrões de projeto: [`BRIEFING.md`](BRIEFING.md)

## Versão anterior

O script original em bash para Termux continua disponível em
[`downloader.sh`](downloader.sh).
