# Briefing de Projeto — Padrões dos meus programas Python

Documento vivo. Reúne os padrões, convenções e decisões que quero aplicar em
**todos os meus programas** (não só neste). Vou adicionando itens com o tempo.

---

## 1. Auto-bootstrap de venv

**O que é:** todo programa deve se re-executar automaticamente usando o python
da sua própria venv, caso seja iniciado por outro interpretador.

**Por quê:** evita o erro "módulo X não instalado" quando o programa é iniciado
com o python do sistema (`python main.py`) em vez do da venv. O programa passa a
funcionar do mesmo jeito iniciado por qualquer python, por `.desktop`, atalho,
duplo-clique, etc. — sem precisar `source venv/bin/activate`.

**Convenção:** a venv fica numa pasta chamada `venv/` ao lado do script de
entrada.

**Como aplicar:** colar no topo do script de entrada, **antes** de importar
qualquer dependência que só exista na venv:

```python
import os
import sys
from pathlib import Path


def _ensure_venv() -> None:
    """Se não estivermos no python da venv, re-executa com ele."""
    here = Path(__file__).resolve().parent
    venv_dir = here / "venv"
    venv_py = venv_dir / "bin" / "python"
    if venv_py.is_file() and Path(sys.prefix).resolve() != venv_dir.resolve():
        os.execv(str(venv_py), [str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]])


_ensure_venv()

# ... a partir daqui os imports da venv (PySide6, etc.)
```

**Detalhes:**
- Compara `sys.prefix` com a pasta da venv (não o caminho do executável, que é
  um symlink e resolveria para o python do sistema).
- `os.execv` substitui o processo — não sobra um processo "pai" pendurado.
- Sem risco de loop: depois do re-exec, `sys.prefix` já é o da venv e a
  condição fica falsa.
- Se a pasta `venv/` não existir, ele não faz nada (roda com o python atual).

---

## 2. Interface — PySide6 (local) e web

**O que é:** todo programa que precise de interface gráfica **local** usa
**PySide6** e aplica o tema `dark_theme.py`. Programas com interface **web** usam
a **mesma paleta** do `dark_theme.py`, adaptada para CSS.

**Por quê:** identidade visual única em todos os programas (fundo preto `#0F0F0F`
+ azul `#019DEA`), sem reescrever o estilo do zero a cada projeto e sem cada
programa parecer de um autor diferente.

### Interface local (PySide6)

**Convenção:** copiar `dark_theme.py` para o projeto e aplicá-lo no
`QApplication` logo após criá-lo, antes de montar as janelas.

**Como aplicar:**

```python
import sys
from PySide6.QtWidgets import QApplication
from dark_theme import apply_theme, set_default_font

app = QApplication(sys.argv)
apply_theme(app)          # tema em todo o app
set_default_font(app)     # fonte padrão
# ... a partir daqui, criar as janelas
```

**Detalhes:**
- Botão secundário: `btn.setObjectName("secondary")`.
- Botão de ação destrutiva: `btn.setObjectName("danger")`.
- Título / subtítulo / status: `QLabel` com
  `setObjectName("title" | "subtitle" | "status")`.
- Separador horizontal: `QFrame` com `setObjectName("separator")`.
- Não sobrescrever cores no widget individual — se faltar um estilo, adicionar
  ao `dark_theme.py` para todos os programas herdarem.

### Interface web

**Convenção:** replicar a paleta do `dark_theme.py` em variáveis CSS e usá-las
em todo o CSS. Mesmas cores, mesma fonte — apenas o meio muda.

**Como aplicar:** colar no topo do CSS:

```css
:root {
  --bg-main:          #0F0F0F;
  --bg-card:          #121212;
  --bg-input:         #080808;
  --accent:           #019DEA;
  --accent-hover:     #00B4FF;
  --accent-press:     #007ACC;
  --border:           #1A1A1A;
  --border-mid:       #2A2A2A;
  --text:             #FFFFFF;
  --text-dim:         #AAAAAA;
  --danger-bg:        #2A1515;
  --danger-text:      #FF6666;
  --danger-border:    #4A2525;
  --secondary-bg:     #202020;
  --secondary-border: #303030;
}

body {
  background: var(--bg-main);
  color: var(--text);
  font-family: 'Segoe UI', 'Noto Sans', Arial, sans-serif;
  font-size: 15px;
}
```

**Detalhes:**
- Fundo geral `--bg-main`; cartões/painéis `--bg-card`; campos de entrada
  `--bg-input`.
- Cor de destaque (links, foco, botão primário): `--accent`, com
  `--accent-hover` no hover e `--accent-press` no clique.
- Borda de foco em inputs: `1px solid var(--accent)`.
- Ações destrutivas usam o trio `--danger-*`.

### Responsividade (sempre)

**Convenção:** toda interface é responsiva — nunca layout de tamanho fixo.

- **Web:** unidades relativas (`rem`, `%`, `vw`/`vh`), `flexbox`/`grid`,
  `max-width: 100%` em imagens e mídia, `@media` para telas menores. Conteúdo
  largo (tabelas, blocos de código) rola dentro do próprio container
  (`overflow-x: auto`), sem estourar a página na horizontal.
- **PySide6:** montar tudo com layouts (`QVBoxLayout`, `QHBoxLayout`,
  `QGridLayout`); nunca posicionar/dimensionar widgets com pixels fixos. Usar
  `setMinimumSize` em vez de tamanho travado e deixar os widgets esticarem com
  `stretch`/`setStretch`.

### Sem emojis

**Convenção:** **nunca** usar emojis — em interface, textos, botões, títulos,
logs ou mensagens. Onde precisar de ícone, usar ícone de verdade (SVG na web,
`QIcon` no PySide6) ou apenas texto.

---

## 3. Ambiente virtual (venv)

**O que é:** todo programa tem sua própria venv, com **todas** as dependências
instaladas nela. O programa sempre roda por dentro dessa venv (ver Seção 1 —
o auto-bootstrap garante isso mesmo iniciado pelo python do sistema).

**Por quê:** isola as dependências de cada programa do python do sistema e dos
outros programas — nada de conflito de versão, nada de "funciona na minha
máquina". Cada projeto é autocontido: a pasta do programa já traz tudo o que
ele precisa para rodar.

**Convenção:**
- A pasta chama-se **`venv`** — nunca `.venv`, `env` ou outro nome.
- Fica na raiz do projeto, ao lado do script de entrada.
- **Nada** de dependência instalada globalmente (`pip install` fora da venv):
  tudo vai para dentro da `venv`.
- As dependências ficam registradas em `requirements.txt` na raiz.

**Como aplicar:**

```bash
# criar a venv (dentro da pasta do projeto)
python -m venv venv

# instalar as dependências nela
venv/bin/pip install -r requirements.txt

# rodar (o auto-bootstrap da Seção 1 já re-executa na venv de qualquer forma)
venv/bin/python main.py
```

**Detalhes:**
- Combina com a Seção 1: como o programa se re-executa no `venv/bin/python`,
  basta a pasta `venv` existir para ele rodar isolado — não é preciso
  `source venv/bin/activate`.
- A pasta `venv` fica no `.gitignore` (não se versiona a venv, só o
  `requirements.txt`).
- No Windows o interpretador fica em `venv\Scripts\python.exe`; em Linux/Mac em
  `venv/bin/python`.

---

<!-- Próximos itens vão aqui -->
