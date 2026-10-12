# Knowledge Studio

Knowledge Studio convierte documentos académicos en una base de conocimiento en
un Vault de Obsidian, con un modelo local de Ollama. Es un subsistema de
Tatewari: comparte su configuración, su cliente de Ollama, su normalización de
texto y sus reglas ([AGENTS.md](../AGENTS.md)), y no cambia nada de la revisión
sistemática.

La regla que lo gobierna todo: **el modelo propone, una persona aprueba, y nada
inventado llega al Vault con aspecto de hecho.**

---

## El recorrido de un documento

```
DOCUMENTO ─▶ ingesta ─▶ extracción ─▶ normalización ─▶ troceado
                                                          │
             ┌────────────────────────────────────────────┘
             ▼
       análisis (Ollama) ─▶ validación del esquema ─▶ verificación de citas
             │
             ▼
   objetos de conocimiento ─▶ vínculos (crear / actualizar / proponer)
             │
             ▼
   notas Markdown ─▶ Vault de Obsidian ─▶ índice ─▶ reporte
```

| Paso | Módulo | Habilidad | ¿Modelo? |
|---|---|---|---|
| Ingesta: tipo real, tamaño, huella SHA-256 | `ingesta.py` | `document_ingest` | no |
| Extracción con su ubicación | `extraccion.py` | `document_extract` | no |
| Normalización y troceado | `normalizacion.py` | (dentro de `document_extract`) | no |
| Análisis de cada trozo | `analisis.py` | `knowledge_extract` | **sí** |
| Esquema, estados, citas | `objetos.py` | (dentro de `knowledge_extract`) | no |
| Deduplicación y conflictos | `vinculos.py` | `knowledge_link` | no |
| Notas nuevas | `vault.py`, `markdown.py` | `obsidian_create_note` | no |
| Notas existentes | `vault.py` | `obsidian_update_note` | no |
| Búsqueda en el Vault | `vault.py` | `obsidian_search` | no |
| Validación del Vault | `validacion.py` | `obsidian_validate` | no |
| Reporte | `reporte.py` | `knowledge_report` | no |

Todo vive en `src/tatewari/conocimiento/`. El modelo interviene en **un solo
paso**; el resto es determinista y se prueba sin Ollama.

### 1. Ingesta

Admite PDF, DOCX, PPTX, TXT y Markdown. El tipo se comprueba **por dentro**, no
por la extensión: un `.pdf` que no empieza por `%PDF` se rechaza, y un `.docx`
tiene que ser un ZIP con `word/document.xml`. Rechaza con un mensaje que dice
qué hacer:

| Caso | Mensaje |
|---|---|
| Imagen (`.png`, `.jpg`…) | el OCR todavía no está |
| `.doc` o `.ppt` antiguos | guárdalo como DOCX o PPTX |
| Archivo vacío, carpeta, no existe | dice cuál de las tres |
| Más de 80 MB | pártelo por capítulos |
| ZIP dañado o PDF con contraseña | dice que está dañado o protegido |

### 2. Extracción, con trazabilidad

Cada trozo de texto es un `Fragmento` con su **ubicación**:

| Formato | Unidad | Ubicación | Cómo |
|---|---|---|---|
| PDF | página | `p. 7` | PyMuPDF (extra opcional `documentos`) |
| DOCX | sección | `sección «Horizontes»` | ZIP + XML de la biblioteca estándar |
| PPTX | diapositiva | `diapositiva 3` | ZIP + XML, en el orden de la presentación, con notas del orador |
| Markdown | sección | `sección «…»` | por encabezados, sin frontmatter ni bloques de código |
| TXT | bloque | `líneas 4–9` | por párrafos |

También se leen título, autores y fecha de los metadatos cuando existen. Una
página de PDF sin texto se avisa: probablemente es un escaneo y hará falta OCR.
Un TXT que no es UTF-8 se lee como Windows-1252 y se avisa.

DOCX y PPTX se leen sin dependencias externas. PyMuPDF es opcional:

```bash
python -m pip install -e ".[documentos]"
```

### 3. Normalización y troceado

Une palabras partidas por guion a final de línea (nunca entre cifras: `10-30`
se queda), quita guiones blandos y caracteres de control, y en los PDF elimina
cabeceras, pies y números de página que se repiten. Luego trocea en bloques de
hasta 2600 caracteres, **sin mezclar la ubicación**: un trozo sabe de qué
fragmentos viene, y un fragmento demasiado grande se parte heredando la suya.

### 4. Análisis con el modelo

Cada trozo va al modelo de extracción con estas reglas (el prompt está en
`analisis.construir_prompt`):

1. Solo lo que está en el texto. Si el fragmento no basta, `"suficiente": false`
   y el motivo: el modelo **tiene que decir** que no hay información.
2. Toda definición y todo detalle traen una **cita literal** del fragmento.
3. Lo que el modelo deduce va marcado como inferencia.
4. No inventar autores, fechas, páginas, cifras ni referencias.
5. Respuesta en JSON con un esquema fijo.

Si la respuesta no se entiende, se repite una vez con un recordatorio; si
tampoco, el trozo se salta y el reporte lo dice. No se escribe nada a medias.

### 5. Validación y verificación de citas

`objetos.validar_respuesta` valida cada objeto contra el esquema (tipos,
longitudes, estados) y luego **busca cada cita en el texto del trozo**, sin
acentos ni puntuación y con al menos cuatro palabras. Esto es lo que hace
funcionar todo:

| La cita… | La afirmación queda como | El objeto |
|---|---|---|
| aparece en el trozo | `fuente`, con la ubicación del fragmento donde aparece | `DRAFT` |
| no aparece | `inferencia`, sin verificar | `REVIEW`, confianza ≤ 0,4 |
| falta | `inferencia` | `REVIEW` si no hay ninguna verificada |

**Las páginas nunca las da el modelo**: salen del fragmento donde se encontró
la cita. Un modelo de 4B se inventa citas con naturalidad («Según Darwin…»); las
pruebas incluyen una de esas trampas y comprueban que llega marcada.

Las referencias bibliográficas se tratan igual: una referencia del modelo solo
se conserva si sus primeras ocho palabras están en el trozo. Además se sacan
sin modelo los DOI y las líneas de la sección de bibliografía.

### 6. Vínculos: crear, actualizar o proponer

`vinculos.planificar` decide qué hacer con cada objeto:

- **Deduplicación**: por nombre (sin acentos, con plurales), por alias y por
  contenido (Jaccard ≥ 0,55 entre definiciones). Un parecido de contenido no
  funde: se crea la nota y el reporte lo señala como posible duplicado.
- **Crear**: no hay nota con ese nombre.
- **Actualizar**: hay una nota de Tatewari en `DRAFT` o `REVIEW` que nadie ha
  tocado. Se funde lo nuevo **conservando todas las fuentes**.
- **Proponer**: la nota está aprobada, publicada, fue editada a mano (su huella
  no coincide) o la escribió una persona. **No se toca**: se deja una propuesta
  en `00_INBOX/propuestas` con el motivo.
- **Conflictos**: dos definiciones verificadas de documentos distintos con
  cifras distintas o muy diferentes entre sí. Se guardan las dos con su origen,
  la nota pasa a `REVIEW` y Tatewari no elige.

### 7. La nota

```markdown
---
tatewari_id: "KS-68def3d685"
tipo: "concepto"
estado: "DRAFT"
fuentes:
  - "edafologia_unidad1.md, sección «Horizontes del suelo»"
generado_por: "modelo:qwen3:4b"
tatewari_hash: "53ad901509c2d5f2"
---
# Horizonte

> [!info] Estado: DRAFT · Confianza: 0.80 · Generado por: modelo:qwen3:4b
> Borrador generado por Tatewari. No es conocimiento aprobado: …

## Definición

- Capa del suelo aproximadamente paralela a la superficie, …
  *(de la fuente · [[Fuente - Edafología I …|edafologia_unidad1.md]], sección «Horizontes del suelo»)*
  > «Un horizonte es una capa del suelo aproximadamente paralela a la superficie, …»

## Resumen (interpretación del modelo)
## Detalles
## Relaciones
- es parte de → [[El suelo]]
## Conflictos entre fuentes
## Referencias citadas en la fuente
## Fuentes

%% tatewari-datos
{ … el objeto completo en JSON … }
%%
```

- Markdown estándar, frontmatter YAML y enlaces `[[…]]`: nada de plugins.
- Las relaciones enlazan aunque la nota destino no exista todavía: Obsidian
  las muestra como pendientes y ofrece crearlas.
- `%% … %%` es un comentario de Obsidian: no se ve al leer. Guarda el objeto
  completo para poder fundir fuentes después sin reinterpretar el Markdown.
- `tatewari_hash` es la huella del cuerpo tal como lo escribió Tatewari. Si
  alguien edita la nota, deja de coincidir y la nota pasa a ser intocable.
- La fuente de lo que se dice está siempre separada: «de la fuente», con cita,
  o «interpretación del modelo».

Cada documento deja además una **nota de fuente** en `01_MATERIA` (el original
enlazado, lo extraído, las referencias y los avisos), el
`Índice de conocimiento.md` en la raíz, que da un centro a la vista de grafo, y
un **reporte** en `00_INBOX/reportes`.

---

## Estados

```
DRAFT ⇄ REVIEW ─▶ APPROVED ─▶ PUBLISHED
  └───────────────▲    │           │
                       └─▶ REVIEW ◀┘
```

- Lo que genera el modelo solo nace en `DRAFT` (todo verificado) o `REVIEW`
  (algo sin verificar, un conflicto, información insuficiente).
- `APPROVED` y `PUBLISHED` exigen `--autor` y rechazan autores `modelo:…`. Se
  anota quién y cuándo, y el aviso visible de la nota cambia.
- `PUBLISHED` solo desde `APPROVED`.
- Una nota aprobada o publicada **nunca se reescribe**. Para corregirla, se
  devuelve a `REVIEW` a mano.

```bash
python -m tatewari conocimiento estado "Horizonte A" APPROVED --autor "Tu nombre"
```

---

## El Vault

Estructura por defecto (ZEA MAYZ), configurable en `.tatewari/vault.json`:

| Carpeta | Contenido |
|---|---|
| `00_INBOX` | `reportes/` y `propuestas/` |
| `01_MATERIA` | originales y notas de fuente |
| `02_CONCEPTOS` | conceptos, procesos, métodos, problemas… |
| `03_PERSONAJES` | personas (y los personajes de la narrativa) |
| `04_TERRITORIO` | lugares |
| `05_GUION` | borradores narrativos de ZEA MAYZ |
| `06_STORYBOARD` | viñetas |
| `07_REFERENCIAS` | referencias como notas |
| `08_ILUSTRACIONES` | especificaciones de ilustración |
| `09_LIBRO` | maquetación (futuro) |
| `_plantillas` | concepto, fuente, personaje, lugar, proceso |

Las plantillas usan `{{title}}`, así que sirven también al plugin de plantillas
de Obsidian.

### La jaula

Toda escritura pasa por `rutas.Jaula`, que solo autoriza el Vault y la carpeta
de datos de Tatewari. Resuelve la ruta real antes de escribir (así `..` o un
enlace simbólico no sirven para salir), prohíbe `.obsidian`, `.git` y `.trash`,
y `nombre_de_nota` limpia los nombres que propone el modelo: caracteres
prohibidos en Windows o en enlaces de Obsidian, nombres reservados (`CON`,
`NUL`…), puntos y espacios finales y longitud.

---

## Modelos

Dos tareas, cada una con su modelo:

| Tarea | Para qué | Contexto | Variable |
|---|---|---|---|
| `extraccion` | leer los trozos | 4096 | `TATEWARI_MODELO_EXTRACCION` |
| `sintesis` | divulgación de ZEA MAYZ | 8192 | `TATEWARI_MODELO_SINTESIS` |

Prioridad: opción de la orden (`--modelo-extraccion`, `--modelo-sintesis`) →
variable de entorno o `.env` → elección automática. La automática es la de
`modelo.elegir_modelo`: el modelo general más capaz de los instalados que entra
en 4 GB de VRAM (los de código y los de embeddings quedan detrás). En la
máquina de referencia sale `qwen3:4b`. Ningún nombre de modelo está fijo en
Knowledge Studio. Síntesis, si no se dice nada, usa el
mismo que extracción.

Con un 8B o un 14B las respuestas son mejores, pero con 4 GB de VRAM Ollama los
reparte con la RAM y cada trozo tarda minutos. Una opción razonable con una
tarjeta pequeña: extracción con `qwen3:4b` y síntesis con `qwen3:8b`, porque la
síntesis es una sola llamada.

```bash
python -m tatewari conocimiento modelos
```

Pensamiento desactivado (`think: false`) y salida JSON forzada (`format:
json`). Todo es local: si Ollama no responde, se dice y se sugiere
`--sin-modelo`.

---

## Órdenes

| Orden | Acción de alto nivel |
|---|---|
| `conocimiento crear-vault` | crear base de conocimiento |
| `conocimiento procesar DOCUMENTO` | procesar documento |
| `conocimiento materia [CARPETA]` | analizar materia |
| `conocimiento actualizar` | actualizar conocimiento existente |
| `conocimiento conceptos [--estado] [--tipo]` | mostrar conceptos detectados |
| `conocimiento conflictos` | mostrar conflictos |
| `conocimiento reporte` | generar reporte |
| `conocimiento validar` | validar el Vault sin escribir |
| `conocimiento buscar TEXTO` | buscar en el Vault |
| `conocimiento estado NOTA ESTADO --autor …` | cambiar el estado |
| `conocimiento habilidades` | listar las habilidades |
| `conocimiento modelos` | qué modelo hace cada tarea |
| `pedir "…"` | cualquiera de las anteriores, en español |

`pedir` es un intérprete de palabras clave, determinista: no gasta modelo en
entender la orden y, si no la entiende, dice lo que sí sabe hacer.

Código de salida `8` cuando la orden no se pudo completar; `6` si el modelo
no se pudo usar; `3` si falla la configuración.

---

## Ejemplo completo: un curso universitario ficticio

El repositorio trae
[`tests/fixtures/conocimiento/edafologia_unidad1.md`](../tests/fixtures/conocimiento/edafologia_unidad1.md),
la primera unidad **inventada** de un curso de Edafología I, y
[`edafologia_otra_fuente.md`](../tests/fixtures/conocimiento/edafologia_otra_fuente.md),
un apunte de campo que contradice el espesor del horizonte A (10–30 cm frente a
20–50 cm). Las cifras son de ejemplo y no deben citarse.

**1. Crear el Vault y procesar la unidad.**

```bash
python -m tatewari conocimiento crear-vault --vault "C:\Vaults\Edafologia"
```

```bash
python -m tatewari conocimiento procesar tests/fixtures/conocimiento/edafologia_unidad1.md --vault "C:\Vaults\Edafologia"
```

Resultado real con `qwen3:4b` en una RTX 3050 de 4 GB (unos 110 s):

```
Archivo procesado   : edafologia_unidad1.md (MD)
Extensión           : 6 secciones, 6 fragmentos, 1 trozos
Modelo              : modelo:qwen3:4b · 1/1 trozos analizados
Conocimiento        : 4 objetos (3 concepto, 1 proceso)
Notas nuevas        : 4
Referencias         : 2
Sin verificar       : 0 afirmaciones sin cita comprobada
Errores             : 0

Notas nuevas:
  + El suelo
  + Horizonte
  + Meteorización
  + Materia orgánica
```

Cada nota trae su definición con la cita literal y la sección de donde sale; las
relaciones que apuntan a conceptos todavía sin nota («Material parental del
suelo») quedan como enlaces pendientes.

**2. Revisar y aprobar.** Abre el Vault en Obsidian, lee cada nota contra la
fuente y aprueba lo que esté bien:

```bash
python -m tatewari conocimiento estado Horizonte APPROVED --autor "Tu nombre" --vault "C:\Vaults\Edafologia"
```

**3. Añadir la segunda fuente.** Si «Horizonte» sigue en `DRAFT`, se funde con
las dos definiciones y queda en `REVIEW` con el conflicto a la vista. Si ya está
aprobada, no se toca y aparece una propuesta en `00_INBOX/propuestas`:

```bash
python -m tatewari conocimiento procesar tests/fixtures/conocimiento/edafologia_otra_fuente.md --vault "C:\Vaults\Edafologia"
```

```bash
python -m tatewari conocimiento conflictos --vault "C:\Vaults\Edafologia"
```

**4. Divulgar.** Con conceptos aprobados, ZEA MAYZ escribe un borrador (ver
[ZEA_MAYZ_WORKFLOW.md](ZEA_MAYZ_WORKFLOW.md)).

---

## Errores y cómo se comportan

| Situación | Qué pasa |
|---|---|
| Documento dañado, vacío, protegido o no admitido | mensaje claro, código 8, nada escrito |
| Vault sin configurar | pide `TATEWARI_OBSIDIAN_VAULT` o `--vault` |
| Sin permisos de escritura | el error se recoge en el reporte; lo demás sigue |
| Ollama apagado | se dice antes de empezar y se sugiere `--sin-modelo` |
| Modelo no instalado | se dice con la orden `ollama pull` exacta |
| Respuesta del modelo inválida | un reintento; si falla, el trozo se salta y se informa |
| El modelo dice que no hay información | aviso en el reporte, sin objetos inventados |
| Cita o referencia inventada | la cita queda como inferencia en `REVIEW`; la referencia se descarta |

---

## Decisiones de diseño

Donde la arquitectura se aparta de lo pedido, y por qué:

- **No había orquestador ni skills.** Tatewari era una CLI que llamaba a
  funciones. En lugar de importar un marco de agentes, se añadió un registro
  mínimo (`habilidades.py`: nombre → función, con las marcas `usa_modelo` y
  `escribe`) y un `Orquestador` que encadena habilidades y deja traza de cuáles
  usó. Las órdenes existentes no cambian.
- **Nombres en español en el código.** El esquema pedido (`title`, `summary`,
  …) se corresponde uno a uno con el del código (`titulo`, `resumen`, …); la
  tabla está en el docstring de `objetos.py`. `definition` es una lista
  (`definiciones`), una por fuente, para poder guardar conflictos.
- **El objeto completo va dentro de la nota**, en un comentario de Obsidian, y
  no en una base de datos aparte: el Vault es la fuente de verdad y se puede
  copiar, versionar o sincronizar sin perder nada.
- **La verificación de citas es literal y determinista**, no semántica: más
  estricta y comprobable. Una paráfrasis del modelo no pasa por cita.
- **La intención en español es por palabras clave**, no por modelo: es
  instantánea, no se equivoca de forma creativa y funciona sin Ollama.
- **OCR, imágenes y maquetación** quedan fuera; ver [ROADMAP.md](ROADMAP.md).

## Límites conocidos

- Un PDF escaneado no tiene texto: sin OCR no se procesa (se avisa).
- Un modelo de 4B deja conceptos fuera y a veces nombra mal («El suelo» en vez
  de «Suelo»). La deduplicación por nombre y alias lo mitiga, no lo elimina.
- La deduplicación por contenido es léxica (Jaccard); los embeddings de
  Tatewari podrían mejorarla.
- Documentos largos: cada trozo es una llamada al modelo. Un PDF de 100 páginas
  en `qwen3:4b` tarda del orden de una hora en una tarjeta de 4 GB.
