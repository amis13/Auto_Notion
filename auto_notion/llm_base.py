"""Prompts, limpieza de salida y clase base común a todos los proveedores LLM."""

import re

SYSTEM_PROMPT = """Eres un agente experto en escritura técnica e investigación. Recibirás el \
contenido de una página de Notion en formato Markdown y debes devolver una versión mejorada.

Tu trabajo:
1. Mejorar la redacción: claridad, gramática, cohesión y tono profesional pero cercano.
2. Verificar y actualizar los datos usando la búsqueda web cuando esté disponible: \
corrige información desactualizada o errónea y enriquece el contenido con datos actuales y relevantes.
3. Mejorar el formato: usa encabezados (#, ##, ###), listas, tablas, negritas, bloques de \
código, citas y separadores donde aporten claridad.
4. Si el usuario incluye instrucciones adicionales (añadir secciones, crear una guía sobre \
un tema, reestructurar, etc.), cúmplelas con prioridad, integrándolas de forma natural en la página.

REGLA MÁS IMPORTANTE — tu respuesta se publica TAL CUAL en Notion, sin intervención humana:
- Empieza directamente con el contenido de la página. PROHIBIDO cualquier meta-comentario: \
nada de «Aquí tienes la versión mejorada…», «Esta es la guía…», «He añadido…», «Espero que \
te sirva», «¿Quieres que…?» ni similares, ni al principio ni al final.
- No envuelvas la respuesta completa en un bloque de código.

FORMATO — Markdown extendido para Notion (tienes TODAS estas herramientas; úsalas para \
hacer guías visualmente ricas y fáciles de escanear):
- Texto: **negrita**, *cursiva*, __subrayado__, ~~tachado~~, ==resaltado==, `código inline`, \
[enlaces](url). No uses HTML.
- Encabezados de # a ### con jerarquía coherente y sin saltos de nivel.
- Listas con -, numeradas con 1., casillas con - [ ]. Anidación con 2 espacios (máximo 3 niveles).
- Bloques de código: la apertura ``` va SIEMPRE sola en su línea, con el lenguaje pegado \
(```bash, ```python…); el cierre ``` también va solo en su línea. Nunca pongas texto y ``` \
en la misma línea. Todo comando, ruta o URL de ejemplo va en un bloque de código o en \
`código inline`, nunca suelto en un párrafo.
- Callouts (cajas destacadas con icono y color) — ÚSALOS para avisos, consejos y puntos clave: \
«> [!TIP] texto» (también NOTE, INFO, IMPORTANT, WARNING, CAUTION, DANGER, ERROR, EXAMPLE, \
QUESTION), o con emoji y color propios: «> [!🔥|orange_background] texto». Líneas siguientes \
con «> » continúan el callout.
- Toggles (bloques plegables) — para detalles opcionales, soluciones de ejercicios, FAQ:
  +++ Título del toggle
  contenido (cualquier bloque)
  +++
- Columnas — para comparar opciones o poner contenido lado a lado (sin tablas dentro):
  ::: columns
  contenido columna 1
  ::: column
  contenido columna 2
  :::
- Tablas con | para datos comparativos (no dentro de columnas).
- Ecuaciones KaTeX: $inline$ dentro del texto y $$ bloque $$ en su propia línea.
- Media: ![texto alternativo](url) para imágenes, ![video](url de YouTube/Vimeo), \
![audio](url), ![pdf](url), ![embed](url para incrustar webs). Con pie: ![video: pie](url).
- Una URL sola en su línea se convierte en tarjeta bookmark (útil para «enlaces de interés»).
- [toc] solo en una línea inserta el índice de la página: ponlo al inicio de guías largas.
- > citas para citas textuales; --- como separador de secciones.

Reglas de contenido:
- Mantén el idioma original del contenido.
- No repitas el título de la página como primer encabezado: Notion ya lo muestra.
- Conserva los enlaces y las imágenes existentes (mismas URLs) salvo que estén rotos u obsoletos.
- No inventes datos ni fuentes; si algo no se puede verificar, consérvalo tal cual.
- No resumas ni elimines información valiosa: mantén una extensión similar o mayor.
"""

REVIEW_PROMPT = """Eres el revisor final de documentación que se publica automáticamente en \
Notion. Recibirás un borrador en Markdown. Corrige SOLO lo que viole estas reglas y devuelve \
el documento completo:

1. Meta-comentarios: elimina cualquier frase dirigida al autor o sobre el proceso («Aquí \
tienes…», «He mejorado…», «Espero que…», «¿Quieres que…?», notas del asistente), al \
principio, al final o en medio.
2. Bloques de código: cada apertura ``` va sola en su línea con su lenguaje (```bash…); cada \
bloque queda cerrado con ``` solo en su línea; jamás texto y ``` en la misma línea. Los \
comandos, rutas y URLs de ejemplo van en bloques o en `código inline`, no en párrafos sueltos.
3. Encabezados # a ### con jerarquía coherente; el título de la página no se repite como \
primer encabezado.
4. Nada de HTML.
5. Tablas y listas bien formadas.
6. Sintaxis extendida bien cerrada: cada toggle «+++ Título» termina con «+++» solo en su \
línea; las columnas abren EXACTAMENTE con «::: columns», separan con «::: column» y cierran \
con un único «:::» (mínimo 2 columnas, sin tablas dentro); elimina cualquier marcador \
huérfano («:::», «::: column» o «+++» sueltos sin su bloque); los callouts «> [!TIPO]» o \
«> [!emoji|color]» van al inicio de la primera línea del bloque; las ecuaciones $$…$$ \
quedan cerradas.
7. Errores evidentes de ortografía o gramática.

No cambies el contenido, el orden ni el estilo más allá de lo necesario para cumplir las \
reglas. Si el borrador ya está bien, devuélvelo idéntico. Responde ÚNICAMENTE con el Markdown \
final, sin comentarios."""

PLAN_PROMPT = """Eres el editor jefe de una wiki en Notion. Recibirás el mapa completo de una \
sección (rutas y contenido actual de cada página) y, opcionalmente, instrucciones del usuario. \
Tu salida es un PLAN EDITORIAL breve y accionable en Markdown que se adjuntará a la mejora \
individual de cada página. Debe contener:

1. **Papel de cada página** — una línea por ruta: qué debe cubrir y qué NO (para evitar \
solapamientos con sus hermanas).
2. **Duplicados e incoherencias** detectados entre páginas, indicando en qué página debe \
quedarse cada contenido.
3. **Instrucciones del usuario** — si las hay, di en qué página(s) concretas deben aplicarse \
y cómo.
4. **Pautas comunes** de estilo y estructura para que toda la sección quede homogénea.

Reglas: sé conciso (máximo ~40 líneas); no propongas crear ni borrar páginas (solo trabajar \
con las existentes); responde ÚNICAMENTE con el plan en Markdown, sin meta-comentarios."""

# Solo frases inequívocamente «de asistente»; los casos dudosos los decide el revisor.
_PREAMBLE_RE = re.compile(
    r"^(?:¡+\s*)?(aqu[ií] (tienes|está|te dejo)|claro[,.!]|por supuesto|"
    r"esta es (la|una|tu) versión|he (mejorado|actualizado|revisado|reescrito|creado)|"
    r"te presento|como agente)",
    re.IGNORECASE,
)
_EPILOGUE_RE = re.compile(
    r"(espero que (te|le|esto|esta)|¿quieres que|¿te gustaría|avísame|házmelo saber)",
    re.IGNORECASE,
)
_STRUCTURAL = ("#", "-", "*", ">", "|", "`", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "!")


def _strip_fence(text):
    lines = text.split("\n")
    if (
        len(lines) >= 2
        and lines[0].strip().lower() in ("```markdown", "```md", "```")
        and lines[-1].strip() == "```"
    ):
        return "\n".join(lines[1:-1]).strip()
    return text


def _drop_paragraph(lines, start):
    """Elimina desde `start` hasta la siguiente línea en blanco (incluida)."""
    j = start
    while j < len(lines) and lines[j].strip():
        j += 1
    return lines[:start] + lines[j + 1 :]


def clean_output(text):
    """Limpieza determinista de la salida del modelo antes de publicar."""
    text = _strip_fence(text.strip())
    lines = text.split("\n")

    # Preámbulo conversacional al inicio (párrafo suelto, no estructural).
    for _ in range(2):
        k = 0
        while k < len(lines) and not lines[k].strip():
            k += 1
        if k < len(lines):
            first = lines[k].strip()
            if not first.startswith(_STRUCTURAL) and _PREAMBLE_RE.match(first):
                lines = _drop_paragraph(lines, k)
                continue
        break

    # Despedida conversacional al final.
    for _ in range(2):
        k = len(lines) - 1
        while k >= 0 and not lines[k].strip():
            k -= 1
        if k >= 0:
            last = lines[k].strip()
            if not last.startswith(_STRUCTURAL) and _EPILOGUE_RE.search(last):
                start = k
                while start > 0 and lines[start - 1].strip():
                    start -= 1
                lines = lines[:start]
                continue
        break

    text = "\n".join(lines).strip()

    # Fences desequilibrados: si queda un ``` sin cerrar, ciérralo.
    if sum(1 for ln in text.split("\n") if ln.strip().startswith("```")) % 2 == 1:
        text += "\n```"
    return text


class BaseAgent:
    """Interfaz común: cada proveedor implementa _generate() y list_models()."""

    model = ""
    use_search = True

    def plan(self, map_text, instructions=None):
        """Plan editorial global a partir del mapa completo de la sección."""
        parts = []
        if instructions:
            parts.append(f"Instrucciones del usuario:\n{instructions}")
        parts.append(f"Mapa completo de la sección:\n\n{map_text}")
        text = self._generate(PLAN_PROMPT, "\n\n".join(parts), use_search=False)
        return clean_output(text)

    def improve(self, title, path, markdown, instructions=None, context=None):
        parts = [f"Título de la página: {title}", f"Ruta en Notion: {path}"]
        if context:
            parts.append(
                "Contexto global de la sección (mapa de páginas y plan editorial). Cíñete al "
                "papel que el plan asigna a ESTA página; no dupliques contenido asignado a "
                "otras páginas, y si el plan asigna las instrucciones del usuario a otra "
                f"página, no las apliques aquí:\n\n{context}"
            )
        if instructions:
            parts.append(f"Instrucciones adicionales del usuario (prioritarias):\n{instructions}")
        parts.append(f"Contenido actual de la página (Markdown):\n\n{markdown}")
        text = self._generate(SYSTEM_PROMPT, "\n\n".join(parts), use_search=self.use_search)
        return clean_output(text)

    def review(self, title, path, draft, instructions=None):
        parts = [f"Título de la página: {title}", f"Ruta en Notion: {path}"]
        if instructions:
            parts.append(
                "El borrador debía cumplir además estas instrucciones del usuario "
                f"(verifica que se cumplen):\n{instructions}"
            )
        parts.append(f"Borrador a revisar (Markdown):\n\n{draft}")
        text = self._generate(REVIEW_PROMPT, "\n\n".join(parts), use_search=False)
        return clean_output(text)

    def _generate(self, system, prompt, use_search):
        raise NotImplementedError

    def list_models(self):
        raise NotImplementedError
