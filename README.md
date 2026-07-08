# Auto Notion

Mejora, crea y mantiene páginas de Notion automáticamente usando IA como agente de
escritura e investigación. Le das una ruta (ej. `docs/Web3`) y:

- lee esa página y todas sus subpáginas,
- genera un **plan editorial global** de la sección,
- la IA mejora redacción, formato y datos (verificándolos con **búsqueda web**),
- un **revisor** valida cada borrador antes de publicar,
- y reescribe las páginas en Notion con formato rico (callouts, toggles, columnas…).

También puede **subir páginas nuevas** desde archivos Markdown locales (`new_pages/`) y
**restaurar** cualquier página desde los backups que guarda antes de tocar nada.

Proveedores de IA soportados: **Gemini** (API key), **Gemini CLI** (tu cuenta de Google,
gratis), **Codex CLI** (tu cuenta de ChatGPT), **Claude Code CLI** (tu cuenta de Claude)
y **OpenRouter** (GPT y cualquier otro modelo, pago por uso).

## Estructura

```
Auto_Notion/
├── main.py                  # mejorar páginas existentes (comando principal)
├── subir.py                 # subir .md de new_pages/ como páginas nuevas
├── restaurar.py             # restaurar páginas desde backups/
├── new_pages/               # tus borradores .md (la _plantilla.md muestra la sintaxis)
├── backups/                 # backup automático antes de cada cambio (+ _plan.md)
├── preview/                 # resultados de --dry-run
├── .env                     # tus claves y configuración (NO subir a git)
└── auto_notion/
    ├── pipeline.py          # orquestación: plan → mejora → revisión → publicar
    ├── agents.py            # selección de proveedor LLM
    ├── llm_base.py          # prompts (escritor, revisor, editor jefe) y limpieza
    ├── gemini_agent.py      # proveedor Gemini API
    ├── gemini_cli_agent.py  # proveedor Gemini CLI (cuenta Google)
    ├── codex_agent.py       # proveedor Codex CLI (cuenta ChatGPT)
    ├── claude_agent.py      # proveedor Claude Code CLI (cuenta Claude)
    ├── openrouter_agent.py  # proveedor OpenRouter
    ├── notion_api.py        # rutas, lectura/escritura de bloques, crear páginas
    ├── md_to_blocks.py      # Markdown extendido → bloques de Notion
    └── blocks_to_md.py      # bloques de Notion → Markdown extendido
```

## Instalación

Requisitos: Python 3.10+ (y Node 20+ solo si vas a usar los proveedores CLI).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # y rellena los valores
```

### 1. Token de Notion (obligatorio)

1. Crea una integración interna en <https://www.notion.so/my-integrations>.
2. Copia el token en `NOTION_TOKEN` dentro de `.env`.
3. **Importante:** comparte la página raíz con la integración: en Notion, abre la
   página → menú `···` → *Conexiones* → añade tu integración (las subpáginas heredan).

### 2. Proveedor de IA (elige al menos uno)

El proveedor por defecto se fija con `LLM_PROVIDER` en `.env` y se puede cambiar por
ejecución con `--proveedor`. Los modelos de cada uno están comentados en `.env.example`.

| Proveedor | Requisitos | Coste |
|---|---|---|
| `gemini-cli` | `npm i -g @google/gemini-cli` + `gemini` → *Login with Google* | Gratis (~60/min, ~1000/día de Pro) |
| `codex` | `npm i -g @openai/codex` + `codex login` (cuenta ChatGPT Plus/Pro) | Cuota de tu plan |
| `claude` | Claude Code instalado + sesión iniciada (`claude` → `/login`) | Cuota de tu plan |
| `gemini` | API key de <https://aistudio.google.com/apikey> en `GEMINI_API_KEY` | Gratis: solo flash, ~20 peticiones/día |
| `openrouter` | API key de <https://openrouter.ai/settings/keys> | Pago por uso |

## Uso: mejorar páginas existentes

```bash
# Modo interactivo: pregunta la ruta e instrucciones opcionales
.venv/bin/python main.py

# Mejorar una página y todas sus subpáginas
.venv/bin/python main.py "docs/Web3"

# Con instrucciones: añadir secciones, guías nuevas, reestructurar…
.venv/bin/python main.py "docs/Web3" -p "mete también una guía de MetaMask"

# Ver el resultado sin tocar Notion (se guarda en preview/)
.venv/bin/python main.py "docs/Web3" --dry-run

# Cambiar proveedor/modelo puntualmente
.venv/bin/python main.py "docs" --proveedor claude
.venv/bin/python main.py "docs" --modelo openai/gpt-5.5   # «/» activa OpenRouter solo
```

| Opción | Efecto |
|---|---|
| `-p, --prompt TEXTO` | Instrucciones extra para la IA (el plan decide en qué página aplicarlas) |
| `--dry-run` | No modifica Notion; guarda las propuestas en `preview/` |
| `--no-recursivo` | Solo la página indicada, sin subpáginas |
| `-y, --si` | No pedir confirmación |
| `--proveedor` | `gemini`, `gemini-cli`, `codex`, `claude` u `openrouter` |
| `--modelo NOMBRE` | Modelo concreto (con `/` activa OpenRouter automáticamente) |
| `--sin-busqueda` | Desactiva la búsqueda web (más rápido, sin verificación de datos) |
| `--sin-revision` | Omite el pase de revisión del borrador |
| `--sin-plan` | Omite el plan editorial global |
| `--listar-modelos` | Lista los modelos disponibles del proveedor y sale |

La ruta también puede ser una **URL o ID** de página de Notion.

### Cómo funciona por dentro

1. **Resuelve la ruta** (`docs/Web3` = página `docs` → subpágina `Web3`) y recopila el
   árbol completo de subpáginas; muestra la lista y pide confirmación.
2. **Plan editorial global** (si hay >1 página): la IA ve el mapa completo de la
   sección y decide el papel de cada página, dónde resolver duplicados y a qué página
   aplicar tus instrucciones. Se guarda en `backups/<fecha>/_plan.md`.
3. **Backup** de cada página en `backups/<fecha>/` (con `manifest.json`).
4. **Mejora**: la IA reescribe la página siguiendo el plan, con búsqueda web.
5. **Revisión**: un segundo pase valida formato y elimina meta-comentarios; además hay
   una limpieza determinista (preámbulos tipo «Aquí tienes…», fences sin cerrar,
   marcadores huérfanos).
6. **Publica**: reemplaza el contenido de la página en Notion.

Coste por ejecución: 1 llamada de plan + 2 llamadas por página.

## Subir páginas nuevas (new_pages/)

Escribe archivos `.md` en `new_pages/` y súbelos como páginas nuevas. Cada `# Título`
(H1) abre una página; el contenido hasta el siguiente H1 es su cuerpo (los `#` dentro
de bloques de código no cuentan). Sin H1, la página toma el nombre del archivo. Los
archivos que empiezan por `_` se ignoran — `new_pages/_plantilla.md` es la chuleta de
toda la sintaxis.

```bash
.venv/bin/python subir.py new_pages/guia.md docs      # un archivo bajo «docs»
.venv/bin/python subir.py new_pages docs              # toda la carpeta
.venv/bin/python subir.py new_pages/guia.md docs --mejorar   # la IA pule antes de subir
```

## Restaurar desde un backup

```bash
# Todas las páginas de una carpeta de backup, bajo una ruta raíz
.venv/bin/python restaurar.py backups/2026-07-07_220714 docs

# Una sola página
.venv/bin/python restaurar.py backups/2026-07-07_220714/docs-Github.md docs/Github
```

Antes de restaurar se guarda copia del estado actual en `backups/<fecha>_pre-restauracion/`.

## Markdown extendido

Los conversores (y las IAs, vía prompt) manejan todo el catálogo de bloques que la API
de Notion permite crear:

| Sintaxis | Bloque de Notion |
|---|---|
| `# ## ###`, listas `-`/`1.`, `- [ ]`, `> cita`, tablas `\|`, `---` | Bloques estándar |
| `**negrita**` `*cursiva*` `__subrayado__` `~~tachado~~` `==resaltado==` `` `código` `` | Estilos de texto |
| `> [!TIP] texto` (NOTE, INFO, IMPORTANT, WARNING, DANGER, ERROR, EXAMPLE, QUESTION) | Callout con icono y color |
| `> [!🔥\|orange_background] texto` | Callout con emoji y color propios |
| `+++ Título` … `+++` | Toggle (bloque plegable) |
| `::: columns` … `::: column` … `:::` | Columnas (sin tablas dentro; se extraen solas) |
| `$inline$` y `$$ bloque $$` | Ecuaciones KaTeX |
| `![texto](url)` / `![video](url)` `![audio](url)` `![pdf](url)` `![embed](url)` | Imagen / media incrustada |
| URL sola en una línea | Tarjeta bookmark |
| `[toc]` | Índice automático de la página |

Robustez integrada: los marcadores huérfanos (`:::`, `+++` sueltos) se descartan y
nunca llegan como texto a Notion; los `<aside>emoji…</aside>` (formato con el que
Notion exporta callouts) se reconocen al subir contenido pegado desde Notion; los
bloques de código con lenguaje de dos palabras (`plain text`) se parsean bien.

## Límites conocidos

- Las **subpáginas, bases de datos y archivos subidos a Notion** nunca se borran, pero
  la API no permite mover bloques, así que quedan agrupados al inicio de la página
  tras una reescritura.
- Las imágenes por URL externa se conservan; los archivos subidos a Notion se
  conservan como bloque (sus URLs firmadas caducan y no se pueden recrear).
- Listas con más de 3 niveles se aplanan al tercero (límite de la API por petición).
- Cuota gratuita de Gemini API: ~20 peticiones/día (`gemini-2.5-flash`); con la
  revisión activada cada página gasta 2. Si se agota: `--modelo gemini-2.5-flash-lite`
  o usa `gemini-cli`/`codex`/`claude`.

## Seguridad

- `.env` contiene tus claves y está en `.gitignore`: no lo subas a ningún repositorio
  (usa `.env.example` como plantilla pública).
- Antes de cualquier modificación hay backup local en `backups/` y confirmación
  interactiva (`-y` para saltarla en scripts).
- Los proveedores CLI (`codex`, `claude`, `gemini-cli`) se ejecutan en sandbox de solo
  lectura y en un directorio vacío: solo pueden buscar en la web, no tocar tus archivos.
