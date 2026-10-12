# Tatewari

Agente local de revisión sistemática de literatura científica.

Tatewari acompaña una revisión sistemática siguiendo la guía **PRISMA 2020**:
búsqueda, cribado, elegibilidad, extracción y síntesis, dejando trazabilidad de
cada decisión. Todo el razonamiento se ejecuta **en la máquina del usuario**,
sobre [Ollama](https://ollama.com). El corpus no sale de aquí.

Las reglas que rigen el proyecto están en [AGENTS.md](AGENTS.md) y no son
negociables: ejecución local, nada de datos inventados, ecuaciones de búsqueda
literales, cribado que nunca descarta solo, y solo fuentes legales y abiertas.

---

## Qué hace, en una frase por paso

| Paso | Orden | Qué deja escrito |
|---|---|---|
| 1. Protocolo | `protocolo validar` | — |
| 2. Cosecha | `cosechar` | `registros.json`, `search_log.csv` |
| 3. Cribado | `cribar` | `cribado.csv`, `prisma.txt` |
| 4. Dudosos | `cribar --modelo-local` | `decisiones.json` |
| 5. Revisión humana | `pendientes`, `decidir` | `decisiones.json` |
| 6. Auditoría | `pendientes --modo auditoria` | `auditoria.json` |
| 7. Texto completo | `texto-completo` | `texto_completo.json` |
| 8. Exportación | `exportar` | `incluidos.bib` y tres `.md` |

Y, cuando hace falta: `ordenar`, `similares` y `casi-duplicados` para leer por
cercanía, `estado` para saber por dónde va la cosa, y `biblioteca` para acumular
varias revisiones en un acervo consultable.

---

## Instalación

### Windows, con el lanzador

Doble clic en `scripts\windows\tatewari.bat`. La primera vez comprueba Python,
crea el entorno virtual, instala las dependencias y abre una consola lista. Para
tenerlo en el Escritorio:

```bash
powershell -ExecutionPolicy Bypass -File scripts\windows\crear-acceso-directo.ps1
```

Eso deja dos iconos: **Tatewari** (la consola) y **Tatewari - interfaz** (la
interfaz gráfica, ver más abajo).

### A mano, en cualquier sistema

Requiere **Python 3.12**. En esta máquina el `python` del PATH es el 3.10, así
que conviene invocar el intérprete por su versión:

```bash
py -3.12 -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
python -m pip install -e ".[dev]"
```

Dependencias: `requests` en ejecución, `pytest` para las pruebas. Nada pesado:
ni pandas, ni numpy, ni un cliente de base de datos.

### Ollama y qué modelos descargar

El cribado determinista, la cosecha y la exportación **no necesitan Ollama**.
Hacen falta para dos cosas opcionales: pasar los dudosos por un modelo y buscar
por parecido.

Instala Ollama desde [ollama.com](https://ollama.com) y arráncalo:

```bash
ollama serve
```

Con **4 GB de VRAM**, que es la máquina de referencia, descarga estos dos:

```bash
ollama pull llama3.2:3b
```

```bash
ollama pull nomic-embed-text
```

| Modelo | Para qué | Peso | Por qué ese |
|---|---|---|---|
| `llama3.2:3b` | decidir sobre los dudosos | ~2 GB | 3B a 4 bits entra entero en la tarjeta |
| `nomic-embed-text` | búsqueda por parecido | ~274 MB | modelo de embeddings, 768 dimensiones |

**No descargues un 8B.** A 4 bits pesa unos 4,7 GB, no entra en 4 GB de VRAM,
Ollama lo reparte con la RAM del sistema y la generación pasa de segundos a
minutos. Tatewari elige solo entre lo que haya descargado y manda el 8B al final
de la lista justamente por eso; si solo tienes un 8B, funcionará, pero lento.

Comprueba qué tienes y con qué va a decidir:

```bash
ollama list
```

---

## Recorrido completo, de principio a fin

Todo lo que sigue funciona tal cual, copiando y pegando. La revisión de ejemplo
se llama `demo` y usa el protocolo `protocolos/humedales.json`, que está en el
repositorio.

### Paso 0. El correo de contacto

```bash
copy .env.example .env
```

Abre `.env` y pon **tu** correo en `TATEWARI_MAILTO`. No es opcional:

- **Unpaywall lo exige.** Sin él rechaza la petición, y sin Unpaywall no hay
  paso de texto completo.
- **OpenAlex y Crossref lo premian.** Identificarse mete las peticiones en su
  cola educada, que responde más rápido y con menos cortes.

### Paso 1. Escribir el protocolo

El protocolo es un JSON con la ventana temporal, los idiomas, los bloques de
términos y las reglas de inclusión. El de ejemplo está en
`protocolos/humedales.json`; para una revisión nueva, cópialo y cámbialo.

```bash
python -m tatewari protocolo validar protocolos/humedales.json
```

Los errores salen todos de una vez y señalan el campo exacto
(`reglas.incluir[0].todos[2]`), porque corregir un protocolo de uno en uno es un
suplicio. La forma completa está más abajo, en
[El protocolo de búsqueda](#el-protocolo-de-búsqueda).

### Paso 2. Ver las búsquedas antes de gastar red

```bash
python -m tatewari cosechar demo --protocolo protocolos/humedales.json --seco
```

Imprime las 40 ecuaciones con su **URL literal**, sin pedir nada. Pega una en el
navegador y comprueba que devuelve lo que esperas antes de lanzar las cuarenta.

### Paso 3. Cosechar de verdad

```bash
python -m tatewari cosechar demo --protocolo protocolos/humedales.json
```

Procesa 8 ecuaciones por llamada y dice cuántas faltan. **Es reanudable**:
volver a lanzar la misma orden continúa donde se quedó, así que se puede cortar
con Ctrl+C sin perder nada. Cada ecuación queda en `search_log.csv` con la URL
literal que se pidió (AGENTS.md, regla 3).

Repite hasta que diga «Cosecha completa». Para probar sin red, con los 14
registros sintéticos del repositorio:

```bash
python -m tatewari cosechar demo --protocolo protocolos/humedales.json --fixture fixtures/demo.json
```

### Paso 4. Cribar

```bash
python -m tatewari cribar demo
```

Deduplica, aplica las reglas del protocolo y escribe `cribado.csv` —una fila por
registro, con su motivo en español— y `prisma.txt` con el diagrama de flujo. Es
**determinista**: la misma entrada da siempre la misma salida, y no toca la red
ni usa ningún modelo.

### Paso 5. Pasar los dudosos por el modelo local

```bash
python -m tatewari cribar demo --modelo-local
```

Solo los dudosos, que son una fracción del total. Tarda segundos por registro.
Cada decisión queda firmada como `modelo:llama3.2:3b`, y lo que decía el filtro
**no se borra**: sigue en las columnas `decision_filtro` y `motivo_filtro`.

Si la respuesta del modelo no se entiende, el registro se queda en «dudoso».
Nunca se excluye por una respuesta que no se entendió.

### Paso 6. Resolver a mano lo que quede

```bash
python -m tatewari pendientes demo
```

Lista los que esperan una persona, con título, año, resumen recortado y el
motivo del filtro. Para decidir uno:

```bash
python -m tatewari decidir demo R0007 --decision incluir --motivo "El texto completo sí reporta remoción de DQO"
```

La decisión humana manda sobre el filtro y sobre el modelo, y queda con su
motivo, su autor y su fecha. La lista también sale como archivo en
`revision-manual.md`, con la orden ya escrita debajo de cada ficha.

### Paso 7. Auditar una muestra de las exclusiones

```bash
python -m tatewari pendientes demo --modo auditoria
```

Veinte exclusiones al azar, con el motivo por el que se descartaron. **Esto es lo
que hace honesto al cribado automático**: el filtro se equivoca poco y un modelo
de 3B se equivoca lo suficiente como para que no se le pueda confiar el descarte
final (AGENTS.md, regla 4).

Cuando la hayas revisado de verdad, apúntala con su semilla para que quede
registrada:

```bash
python -m tatewari pendientes demo --modo auditoria --semilla 12345 --registrar
```

### Paso 8. Buscar los textos completos

```bash
python -m tatewari texto-completo demo
```

Pregunta a Unpaywall por el DOI de cada incluido y guarda la URL de la versión
en acceso abierto. Los que no tengan una se listan aparte, para pedirlos a la
biblioteca.

> **Tatewari no elude muros de pago.** Nada de Sci-Hub, nada de raspar la web de
> la editorial, nada de rodear el acceso (AGENTS.md, regla 5). Cuando no hay
> versión legal abierta, el programa lo dice y se detiene ahí.

### Paso 9. Exportar

```bash
python -m tatewari exportar demo
```

Cuatro archivos en la carpeta de la revisión:

| Archivo | Para qué |
|---|---|
| `incluidos.bib` | meter la bibliografía en Zotero o Mendeley y citar |
| `incluidos.md` | una ficha por artículo, para leer de corrido |
| `revision-manual.md` | los dudosos, con la orden de `decidir` ya escrita |
| `por-conseguir.md` | los incluidos sin acceso abierto, con su DOI |

### En cualquier momento: ¿por dónde iba?

```bash
python -m tatewari estado demo
```

Ecuaciones ejecutadas y pendientes, registros únicos, conteo por decisión, qué
archivos están generados y cuál es el siguiente paso útil. Es de **solo
lectura**: no escribe nada.

---

## La interfaz gráfica

Todo lo anterior tiene también ventana: una biblioteca de tres paneles al estilo
de Zotero, en el navegador.

```bash
python -m tatewari interfaz
```

O doble clic en `scripts\windows\tatewari-interfaz.bat` (o en el icono
**Tatewari - interfaz** del Escritorio), que además abre Ollama si estaba
cerrado. Al arrancar carga el modelo local en la tarjeta para que el primer
documento no espere; la luz de la barra superior dice si ya está cargado.

- **Izquierda**, las colecciones: cada revisión con sus incluidos, dudosos y
  excluidos, y el Vault de Obsidian por estado (DRAFT, REVIEW, APPROVED,
  PUBLISHED), con conflictos, fuentes, propuestas y borradores de ZEA MAYZ.
- **Centro**, los elementos, que se ordenan por columna y se buscan sin
  importar los acentos.
- **Derecha**, la ficha: el resumen y la decisión de un artículo, con botones
  para incluir, dejar dudoso o excluir (pide motivo, como `decidir`); o la nota
  entera, con sus `[[enlaces]]` navegables y los botones para aprobar (con tu
  nombre), abrirla en Obsidian o abrir el documento original.
- Arrastra un PDF, un Word o un PowerPoint a la ventana y se procesa; el avance
  se ve en la barra de abajo.

Corre solo en `127.0.0.1` y cada arranque genera una clave nueva: ninguna otra
computadora ni ninguna otra página web abierta en el navegador puede leer ni
cambiar nada. Si cierras la ventana de la consola, la interfaz se apaga. No usa
el código de Zotero (es AGPL y Tatewari es MIT): solo su disposición.

```bash
python -m tatewari interfaz --no-abrir --puerto 9000
```

---

## Knowledge Studio: de documentos a un Vault de Obsidian

Knowledge Studio lee documentos académicos (apuntes, diapositivas, artículos) y
los convierte en notas de Obsidian enlazadas entre sí, con el modelo local de
Ollama. Cada afirmación dice de qué página, diapositiva o sección sale; lo que
el modelo no puede respaldar con una cita literal del documento queda marcado
como interpretación y en `REVIEW`. **Nada nace aprobado**: `APPROVED` lo pone
una persona. La documentación completa está en
[docs/KNOWLEDGE_STUDIO.md](docs/KNOWLEDGE_STUDIO.md), y el camino hasta el libro
de divulgación en [docs/ZEA_MAYZ_WORKFLOW.md](docs/ZEA_MAYZ_WORKFLOW.md).

Formatos: PDF (con texto; el OCR todavía no está), DOCX, PPTX, TXT y Markdown.
Para PDF hace falta PyMuPDF:

```bash
python -m pip install -e ".[documentos]"
```

### 1. Decir dónde está el Vault

En el `.env` (o con `--vault RUTA` en cada orden):

```
TATEWARI_OBSIDIAN_VAULT=C:\Users\TU_USUARIO\Documents\ZEA MAYZ
```

Tatewari solo escribe dentro del Vault y de la carpeta de datos. No toca
`.obsidian`, `.git` ni la papelera, y ningún nombre que proponga el modelo puede
sacar un archivo de ahí.

### 2. Crear la estructura

```bash
python -m tatewari conocimiento crear-vault
```

Crea `00_INBOX` … `09_LIBRO`, las plantillas de concepto, fuente, personaje,
lugar y proceso, y la configuración en `.tatewari/vault.json` (donde se pueden
renombrar las carpetas). No pisa nada que ya exista. Abre la carpeta en Obsidian
con «Open folder as vault».

### 3. Comprobar Ollama y elegir modelo

```bash
python -m tatewari conocimiento modelos
```

Dice qué modelo haría cada tarea: **extracción** (leer los trozos del documento)
y **síntesis** (la divulgación). Sin configurar nada elige el que entra en la
tarjeta; con 4 GB de VRAM, `qwen3:4b`:

```bash
ollama pull qwen3:4b
```

Para usar otro, `TATEWARI_MODELO_EXTRACCION` y `TATEWARI_MODELO_SINTESIS` en el
`.env`, o por orden:

```bash
python -m tatewari conocimiento procesar apuntes.pdf --modelo-sintesis qwen3:8b
```

Un 8B o un 14B escriben mejor, pero con 4 GB de VRAM Ollama los reparte con la
RAM y cada respuesta tarda minutos. Los nombres de modelo no están fijos: solo
ordenan la preferencia de la elección automática.

### 4. Procesar el primer documento

```bash
python -m tatewari conocimiento procesar tests/fixtures/conocimiento/edafologia_unidad1.md
```

Es un documento **ficticio** de un curso universitario de edafología que viene
con el repositorio. En la máquina de referencia (RTX 3050, 4 GB) tarda unos dos
minutos y deja:

- el original, sin tocar, en `01_MATERIA`;
- una nota de fuente en `01_MATERIA` con los conceptos extraídos y las
  referencias bibliográficas que están **en el documento** (las que el modelo
  inventa se descartan);
- una nota por concepto en `02_CONCEPTOS` (personas, lugares y referencias van a
  sus carpetas), con definición, cita literal, ubicación, relaciones como
  `[[enlaces]]` y fuentes;
- `Índice de conocimiento.md` en la raíz, que da un centro a la vista de grafo;
- un reporte en `00_INBOX/reportes`.

Sin Ollama se puede procesar igual, sin conceptos: texto, nota de fuente y
referencias.

```bash
python -m tatewari conocimiento procesar apuntes.pdf --sin-modelo
```

### 5. Revisar y aprobar

```bash
python -m tatewari conocimiento conceptos --estado REVIEW
```

```bash
python -m tatewari conocimiento conflictos
```

```bash
python -m tatewari conocimiento estado "Horizonte A" APPROVED --autor "Tu nombre"
```

Estados: `DRAFT` → `REVIEW` → `APPROVED` → `PUBLISHED`. Una nota aprobada, o
una que alguien editó a mano, **no se reescribe nunca**: si un documento nuevo
trae algo sobre ella, Tatewari deja una propuesta en `00_INBOX/propuestas`. Si
dos fuentes se contradicen, la nota conserva las dos versiones con su origen y
pasa a `REVIEW`; Tatewari no elige.

### 6. Toda una carpeta, y el mantenimiento

```bash
python -m tatewari conocimiento materia
```

Procesa lo que haya en `01_MATERIA` que no se haya procesado antes (por su
huella SHA-256). Y, cuando haga falta:

```bash
python -m tatewari conocimiento actualizar
```

```bash
python -m tatewari conocimiento validar
```

```bash
python -m tatewari conocimiento reporte
```

```bash
python -m tatewari conocimiento buscar "horizonte"
```

```bash
python -m tatewari conocimiento habilidades
```

### Pedirlo en español

```bash
python -m tatewari pedir "procesa este documento apuntes.pdf"
```

Entiende «procesa este documento …», «analiza la materia», «crea la base de
conocimiento», «actualiza el conocimiento existente», «muestra los conceptos
detectados», «muestra los conflictos» y «genera el reporte». Es un intérprete de
palabras clave, no un modelo: lo que no entiende lo dice.

### ZEA MAYZ: divulgación desde lo aprobado

```bash
python -m tatewari zea-mayz divulgar --tema "el suelo" --publico "lectores de 10 a 14 años"
```

Escribe guion (`05_GUION`), storyboard (`06_STORYBOARD`) y especificaciones de
ilustración (`08_ILUSTRACIONES`) **solo** con conceptos `APPROVED`, y valida que
cada afirmación, recuadro científico y cifra tenga base aprobada. Tras editar el
borrador a mano:

```bash
python -m tatewari zea-mayz validar "05_GUION/Guion - Mi borrador.md"
```

---

## Todos los subcomandos

| Orden | Qué hace | ¿Red? | ¿Escribe? |
|---|---|---|---|
| `version` | la versión de Tatewari | no | no |
| `protocolo validar RUTA` | valida un protocolo y lo resume | no | no |
| `cosechar REVISIÓN --protocolo RUTA` | cosecha en OpenAlex o Crossref | sí | sí |
| `cosechar … --seco` | solo imprime las ecuaciones y sus URL | no | no |
| `cosechar … --fixture RUTA` | sirve un archivo local como respuesta | no | sí |
| `cribar REVISIÓN` | deduplica y criba con las reglas | no | sí |
| `cribar … --modelo-local` | pasa los dudosos por Ollama | local | sí |
| `pendientes REVISIÓN` | lista los que esperan una persona | no | no |
| `pendientes … --modo auditoria` | muestra aleatoria de exclusiones | no | no |
| `pendientes … --registrar` | apunta esa ronda de auditoría | no | sí |
| `decidir REVISIÓN ID --decision … --motivo …` | registra una decisión humana | no | sí |
| `texto-completo REVISIÓN` | busca la versión abierta en Unpaywall | sí | sí |
| `exportar REVISIÓN` | BibTeX y las tres fichas en Markdown | no | sí |
| `estado REVISIÓN` | por dónde va la revisión | no | **no** |
| `ordenar REVISIÓN --pregunta TEXTO` | ordena por cercanía a la pregunta | local | caché |
| `similares REVISIÓN ID` | los más parecidos a uno dado | local | caché |
| `casi-duplicados REVISIÓN` | pares que la deduplicación no atrapó | local | sí |
| `biblioteca importar [REVISIÓN]` | vuelca revisiones en el acervo | no | sí |
| `biblioteca buscar [TEXTO]` | busca en todo el acervo | no | no |
| `biblioteca resumen` | cuánto hay acumulado | no | no |
| `biblioteca reconstruir` | rehace el acervo desde la evidencia | no | sí |
| `conocimiento crear-vault` | crea la estructura del Vault de Obsidian | no | sí |
| `conocimiento procesar DOCUMENTO` | documento → notas enlazadas en el Vault | local | sí |
| `conocimiento materia [CARPETA]` | procesa los documentos nuevos de una carpeta | local | sí |
| `conocimiento actualizar` | rehace enlaces e índice, sin modelo | no | sí |
| `conocimiento conceptos` | lista conceptos con tipo y estado | no | no |
| `conocimiento conflictos` | lo que dos fuentes dicen distinto | no | no |
| `conocimiento reporte` | valida el Vault y deja un reporte | no | sí |
| `conocimiento validar` | valida el Vault | no | no |
| `conocimiento buscar TEXTO` | busca notas por contenido | no | no |
| `conocimiento estado NOTA ESTADO --autor …` | DRAFT, REVIEW, APPROVED, PUBLISHED | no | sí |
| `conocimiento habilidades` | las habilidades del orquestador | no | no |
| `conocimiento modelos` | qué modelo hace cada tarea | local | no |
| `pedir PETICIÓN` | lo mismo, pedido en español | según | según |
| `zea-mayz divulgar` | borrador narrativo desde conceptos aprobados | local | sí |
| `zea-mayz validar BORRADOR` | comprueba la base aprobada de un borrador | no | no |
| `interfaz` | la interfaz gráfica en el navegador, solo en esta máquina | local | según |

«local» quiere decir que habla con Ollama en `localhost`, nunca con la nube.
«caché» quiere decir que solo escribe `vectores.json`, que es desechable.

Cada orden acepta `--help`:

```bash
python -m tatewari cribar --help
```

Códigos de salida: `0` correcto, `1` protocolo inválido, `2` archivo no
encontrado, `3` problema de configuración, `4` la cosecha no pudo arrancar,
`5` el cribado no pudo arrancar, `6` el modelo local no se pudo usar, `7` los
embeddings no se pudieron calcular, `8` Knowledge Studio no pudo completar la
orden (documento ilegible, Vault sin configurar, validación con errores).

---

## Estado

**Completo de principio a fin.** Lo que funciona:

- Carga de configuración desde `.env` con valores por defecto.
- Carga y validación del protocolo de búsqueda en JSON, con errores en español
  que señalan el campo exacto.
- Cosecha reanudable en OpenAlex y Crossref, con bitácora y modos sin red.
- Resolución de acceso abierto por DOI en Unpaywall.
- Deduplicación por DOI o por título, con identificadores estables entre
  cosechas.
- Cribado determinista contra las reglas del protocolo, con motivo en español
  por decisión, decisiones manuales que sobreescriben al filtro y diagrama
  PRISMA.
- Segunda vuelta con el **modelo local de Ollama** sobre los registros dudosos,
  con detección automática del modelo que entra en la tarjeta.
- Auditoría por muestreo de las exclusiones, registrada y repetible.
- Búsqueda por parecido con embeddings locales (capa opcional): ordenar por la
  pregunta de investigación, buscar parecidos a un registro y detectar casi
  duplicados que la deduplicación no atrapó.
- Exportación a BibTeX y a fichas en Markdown, con la lista de lo que hay que
  pedir a la biblioteca.
- Biblioteca acumulativa en SQLite para consultar varias revisiones juntas.
- Lanzador de Windows con acceso directo en el Escritorio.
- **Knowledge Studio**: documentos académicos (PDF, DOCX, PPTX, TXT, Markdown)
  a notas de Obsidian enlazadas, con trazabilidad a página, diapositiva o
  sección, citas comprobadas, estados de revisión y conflictos entre fuentes.
- **ZEA MAYZ**: borradores de divulgación solo desde conceptos aprobados, con
  validación de cada afirmación.
- **Interfaz gráfica** local de tres paneles, al estilo de un gestor de
  referencias, que carga el modelo al abrirse.

---

## Configuración

Copia `.env.example` a `.env` y ajústalo. El `.env` no se versiona.

| Variable | Por defecto | Para qué |
|---|---|---|
| `TATEWARI_MAILTO` | *(vacío)* | Correo de contacto para las APIs académicas |
| `TATEWARI_OLLAMA` | `http://localhost:11434` | Ollama local, el único modelo del proyecto |
| `TATEWARI_DATOS` | `./revisiones` | Carpeta de salida (no se versiona) |
| `TATEWARI_OBSIDIAN_VAULT` | *(vacío)* | Vault de Obsidian de Knowledge Studio |
| `TATEWARI_MODELO_EXTRACCION` | *(automático)* | Modelo que lee los documentos |
| `TATEWARI_MODELO_SINTESIS` | *(el de extracción)* | Modelo de la divulgación |

Precedencia, de menor a mayor: valores por defecto → `.env` → variables de
entorno reales. Así, un `set TATEWARI_OLLAMA=...` en la consola manda sobre el
archivo, que es lo que espera quien está depurando.

### Por qué hace falta el correo

Según la documentación oficial de cada servicio:

- **Unpaywall lo exige.** Su API pide un parámetro `email` en cada petición y
  rechaza las que no lo llevan. Sin correo, no hay consulta de acceso abierto.
- **OpenAlex y Crossref lo premian.** Identificarse mete las peticiones en su
  cola educada (*polite pool*), que responde más rápido y con menos cortes que
  la cola anónima.

No es telemetría ni registro: es la forma en que estos servicios gratuitos
saben a quién llamar si una herramienta se pone pesada con su infraestructura.

---

## Estructura

```
pyproject.toml            Dependencias y configuración de pytest
AGENTS.md                 Las reglas del proyecto
.env.example              Plantilla de configuración
src/tatewari/
  config.py               Lectura de .env y valores por defecto
  protocolo.py            Carga y validación del protocolo
  http.py                 Tiempo de espera, reintentos y fallo limpio
  cosecha.py              Cosecha reanudable, estado y bitácora
  texto.py                Normalización sin acentos y detección de términos
  dedup.py                Deduplicación e identificadores estables
  cribado.py              Motor de reglas, decisiones y salidas
  prisma.py               Diagrama de flujo PRISMA en texto
  modelo.py               Cliente de Ollama y elección del modelo
  cribado_modelo.py       Segunda vuelta: los dudosos, con el modelo local
  auditoria.py            Muestreo de las exclusiones, registrado
  embeddings.py           Vectores locales, caché y búsqueda por parecido
  texto_completo.py       Unpaywall: la versión abierta legal de cada DOI
  exportar.py             BibTeX y fichas en Markdown
  biblioteca.py           Acervo acumulativo en SQLite
  cli_conocimiento.py     Órdenes conocimiento, pedir y zea-mayz
  conocimiento/           Knowledge Studio (ver docs/KNOWLEDGE_STUDIO.md)
  zea_mayz/               Divulgación desde conocimiento aprobado
  interfaz/               La interfaz gráfica local (servidor y página)
  fuentes/
    openalex.py           Fuente primaria
    crossref.py           Fuente secundaria
    unpaywall.py          Acceso abierto por DOI
  cli.py                  Línea de órdenes
  __main__.py             python -m tatewari
protocolos/humedales.json Protocolo real de ejemplo
fixtures/demo.json        14 registros sintéticos para las pruebas
tests/                    pytest, sin red
tests/fixtures/           Documentos ficticios de ejemplo para Knowledge Studio
docs/                     Arquitectura, hoja de ruta, Knowledge Studio, ZEA MAYZ
scripts/windows/          Lanzador .bat y creador de acceso directo
tests/respuestas/         Respuestas de las APIs: documentadas y capturas reales
```

---

## El protocolo de búsqueda

Un protocolo es un JSON con esta forma:

| Campo | Obligatorio | Qué es |
|---|---|---|
| `titulo` | sí | Título de la revisión |
| `ventana` | sí | `[año_inicial, año_final]` |
| `idiomas` | sí | Códigos de idioma admitidos |
| `tipos` | sí | Tipos de documento (`article`, `review`…) |
| `bloques` | sí | Nombre → lista de términos de búsqueda |
| `exclusion` | no | Términos de exclusión temática |
| `grupos` | no | Agrupaciones adicionales de términos, citables por nombre |
| `clasificacion` | no | Etiquetas temáticas: `{ etiqueta, todos }` |
| `consulta` | no | `{ eje, cruce }`: cómo se arman las ecuaciones |
| `reglas` | no | `sinResumen`, `incluir`, `dudoso` |

### Semántica de una regla

Una regla se cumple cuando se dan las tres condiciones a la vez:

- `todos`: están presentes **todos** los bloques de la lista.
- `alguno_de`: de **cada** sublista hay presente **al menos uno**.
- `ninguno`: no está presente **ninguno** de los de la lista.

Los tres campos son opcionales, pero al menos uno debe aparecer: una regla sin
condiciones se cumpliría siempre. `motivo` es texto libre que se copiará tal
cual a la bitácora; si falta, queda como `"NR"`.

### Nombres

Los nombres citados en `clasificacion`, en `consulta.eje` y dentro de las
reglas tienen que estar definidos en `bloques` o en `grupos`. Citar un nombre
inexistente es un **error de validación**, no una advertencia: sería una
condición que jamás se cumple y que dejaría el cribado mudo sin avisar.

### Ecuaciones previstas

`consulta` define un bloque **eje** y una lista de términos de **cruce**. Se
prevé una ecuación por cada par (término del eje × término del cruce). En
`humedales.json`: 10 términos de `P2_humedal` × 4 de cruce = **40 ecuaciones**.

### Duplicación deliberada en `humedales.json`

Los términos de análisis de ciclo de vida aparecen dos veces: en `exclusion`
(la lista global) y en el grupo `G_ciclo_vida`. No es un descuido. `exclusion`
es la lista temática del protocolo; `G_ciclo_vida` existe para que las reglas
puedan **citarla por nombre** en un `ninguno`, porque las reglas solo aceptan
nombres de bloques o de grupos.

---

## La cosecha

`cosechar` es **reanudable**. Una cosecha completa son decenas de ecuaciones y
miles de peticiones; si se corta a la mitad —y se corta— hay que poder
retomarla sin repetir lo hecho ni perder el rastro.

Cada revisión escribe en `revisiones/<nombre>/`:

| Archivo | Qué guarda |
|---|---|
| `estado.json` | Qué ecuaciones ya se ejecutaron. Volver a lanzar continúa desde ahí |
| `search_log.csv` | Una fila por ecuación, con la **URL literal** que se pidió |
| `registros.json` | Los registros cosechados, **con sus duplicados** |

Cada llamada procesa un lote (8 ecuaciones por defecto, `--max-consultas`) y
dice cuántas faltan. Un error en una ecuación no tumba la cosecha: se anota en
la bitácora con su mensaje y se sigue con la siguiente.

Las que fallaron vuelven a la cola con `--reintentar`, hasta **3 intentos**.
Pasados esos, la ecuación se da por perdida y deja de volver: una ecuación rota
no puede atascar la cosecha en bucle. El contador vive en `estado.json`.

### Modos sin red

| Modo | Qué hace |
|---|---|
| `--seco` | No pide nada. Imprime las ecuaciones con su URL literal para pegarlas en el navegador |
| `--fixture RUTA` | Sirve un archivo local como respuesta, en vez de la API |
| `--reintentar` | Vuelve a lanzar las ecuaciones que fallaron |

En modo `--fixture` el archivo se sirve como respuesta de la **primera**
ecuación del lote; si el lote lleva más, esas quedan en la bitácora con 0
resultados y la observación de que el fixture ya se había servido. Por eso, en
modo fixture el lote es de **una sola ecuación** salvo que se pida otra cosa
con `--max-consultas`.

### La bitácora

Columnas de `search_log.csv`: `N`, `fecha`, `base`, `ecuacion`, `url`,
`idiomas`, `ventana`, `resultados`, `observaciones`.

La **URL literal es obligatoria**. Sin la cadena exacta que se envió, la
búsqueda no se puede repetir y la revisión deja de ser sistemática
(AGENTS.md, regla 3).

> El CSV se escribe en UTF-8 sin BOM. Excel en Windows abre esos archivos con
> la página de códigos local y destroza los acentos: hay que importarlo
> eligiendo UTF-8, o abrirlo con LibreOffice, que lo detecta solo.

---

## El cribado

`cribar` es **determinista**: no hay Ollama, no hay embeddings, y la misma
entrada da siempre la misma salida. Todo lo que decide lo decide una regla
escrita en el protocolo, y el motivo de cada decisión cita el término o el
bloque que la disparó, para poder auditarla sin volver a leer el resumen.

### Orden de evaluación

El orden no es decorativo: cambia el motivo que acaba escrito.

| # | Paso | Si no pasa |
|---|---|---|
| 1 | Ventana temporal | `excluir`, motivo *Fuera de la ventana temporal* |
| 2 | Idioma | `excluir`, motivo *Idioma no admitido* |
| 3 | ¿Hay resumen? | lo que diga `reglas.sinResumen`, por defecto `dudoso` |
| 4 | Términos de exclusión temática | `excluir`, motivo *Exclusión temática* |
| 5 | Reglas de bloques: `incluir`, luego `dudoso` | `excluir`, *No cumple ninguna regla de inclusión* |

Un artículo de 2009 se excluye por el año, no por su contenido, porque ese es el
motivo verdadero. Y **un dato que falta nunca es motivo de exclusión
automática**: sin resumen, sin año o sin idioma, el registro es `dudoso` y pasa a
revisión humana (AGENTS.md, regla 4).

La clasificación aplica la **primera** etiqueta de `clasificacion` que cuadre, o
`"NR"`. El orden de esa lista en el protocolo es por tanto una decisión: la
etiqueta más específica va primero.

### El fallo del acento

Los términos del protocolo se escriben a mano y a veces van sin acento
(`"remocion"`, `"tanque septico"`). Si el texto del registro solo se pasara a
minúsculas, un resumen en español que diga «remoción» **no coincidiría**: el
cribado se quedaría mudo, sin fallar y sin avisar, y los artículos en español
acabarían excluidos por no cumplir ninguna regla.

Así que `texto.py` normaliza **los dos lados** con la misma función: minúsculas,
NFD y fuera los diacríticos combinantes. Los términos se buscan como **palabra
completa**, porque `pH` aparece dentro de *phosphorus* y `LCA` dentro de
*alcalinidad*; y la última palabra admite plural, porque el término
`treatment wetland` tiene que encontrar *treatment wetlands*.

### Deduplicación e identificadores

La clave es el **DOI normalizado** (sin `https://doi.org/`, en minúsculas) y, si
no hay DOI, el **título reducido a letras y números**.

Cada artículo único recibe un identificador `R0001`, `R0002`… que **se conserva
entre cosechas**, guardado en `identificadores.json`. No es cosmética: si los
identificadores se recalcularan, una decisión manual sobre `R0007` pasaría a
apuntar a otro artículo en cuanto llegaran registros nuevos. Los identificadores
dados no se reordenan ni se reutilizan nunca.

Al fusionar duplicados, `consulta_origen` **acumula** todas las ecuaciones por
las que llegó el artículo, y cada `"NR"` se rellena con el primer valor real que
traiga un duplicado. Eso no es inventar: es copiar un dato que alguna fuente sí
reportó.

### Decisiones manuales

`decisiones.json`, en la carpeta de la revisión, sobreescribe al filtro **sin
borrarlo**:

```json
{
  "R0007": {
    "decision": "incluir",
    "motivo": "El texto completo sí reporta remoción de DQO.",
    "autor": "Pedro",
    "fecha": "2026-09-12"
  }
}
```

Los cuatro campos son obligatorios: una decisión sin motivo, autor y fecha no es
auditable, y entonces no vale más que la del filtro. En `cribado.csv`, la columna
`decidido_por` dice `filtro`, el nombre de la persona o —más adelante— el del
modelo, y `decision_filtro` con `motivo_filtro` conservan lo que había propuesto
el filtro. Sin eso no se puede medir cuánto se equivoca, que es justo lo que hay
que medir.

### Salidas

| Archivo | Qué guarda |
|---|---|
| `cribado.csv` | Una fila por artículo único, con decisión, motivo, categoría, bloques y clasificación |
| `prisma.txt` | El diagrama de flujo PRISMA 2020 en texto |
| `identificadores.json` | Clave → identificador estable, solo crece |

> `cribado.csv` va en UTF-8 **sin BOM**. La excepción del BOM que autoriza
> AGENTS.md es solo para `search_log.csv`. Para abrirlo en Excel hay que
> importarlo eligiendo UTF-8, o usar LibreOffice, que lo detecta solo.

### La prueba de oro

`tests/test_oro.py` fija **exactamente** qué decide el cribado sobre los 14
registros del fixture con `protocolos/humedales.json`:

| Medida | Valor |
|---|---|
| Registros identificados | 14 |
| Duplicados eliminados | 1 |
| Registros únicos cribados | **13** |
| Incluir | 8 |
| Dudoso | 2 |
| Excluir | **3**: uno por ventana, uno por idioma, uno por tema |

Si alguien cambia las reglas del protocolo, los términos de un bloque o el orden
de evaluación, y estos catorce registros dejan de decidirse igual, la prueba se
rompe. Cuando el cambio sea el correcto, esos números se actualizan **a mano** y
en el mismo commit, para que quede escrito que la decisión cambió.

Los dos `dudoso` son el registro sin resumen (`sintetico.007`) y el de humedales
de aguas pluviales (`sintetico.011`), que habla de humedales pero nunca dice si
trata agua residual. Ninguno de los dos se descarta en automático.

---

## El modelo local

El único modelo de lenguaje del proyecto es **Ollama, en esta máquina**
(AGENTS.md, regla 1). No hay ningún camino de código que llame a un modelo en la
nube, ni un `import` comentado por si acaso: `modelo.py` solo habla con
`localhost`, y el corpus no sale de aquí.

El modelo **no criba la revisión entera**: solo los registros que el filtro
determinista dejó en «dudoso». En el fixture son 2 de 13. A segundos por
registro, preguntar por todo convertiría una revisión en un fin de semana de
cómputo.

### Elegir el modelo con 4 GB de VRAM

La tarjeta de referencia tiene 4 GB, y eso decide todo. Un 8B a 4 bits pesa unos
4,7 GB: no entra, Ollama lo reparte con la RAM del sistema y la generación pasa
de segundos a minutos. Un 3B a 4 bits pesa unos 2 GB, entra entero y deja sitio
para el contexto.

`cribar --modelo-local` consulta `/api/tags` y ordena lo que haya descargado, de
mejor a peor:

| Orden | Qué |
|---|---|
| 1 | 3B–4B **cuantizado a 4 bits**: entra en la tarjeta y entiende una instrucción |
| 2 | 3B–4B sin cuantizar a 4 bits |
| 3 | 1B–3B cuantizado, y luego sin cuantizar |
| 4 | Menos de 1B: entran en cualquier sitio y se equivocan demasiado |
| 5 | 4B–8B cuantizado, y luego sin cuantizar: van justos |
| 6 | Tamaño desconocido |
| 7 | **8B o más**: se desborda a RAM y se arrastra |

A igualdad de grupo gana el modelo **general** sobre el de código, luego el que
dice ser instruido, y después el más pequeño: con 4 GB, lo que sobra de VRAM es
contexto. El nombre desempata al final, para que dos máquinas con los mismos
modelos elijan el mismo.

Los modelos de *embeddings* se descartan del todo: no generan texto. Los de
**código** no se descartan, pero se van al final de su grupo. Eso no es
teórico: en esta máquina, con `qwen2.5-coder:3b` y `qwen3:4b` instalados, sin esa
regla ganaba el de código por ser 0,9 mil millones de parámetros más pequeño, que
es exactamente la decisión equivocada para leer un resumen en español.

Se puede forzar con `--modelo NOMBRE`, y entonces se comprueba que esté
descargado **antes** de empezar: más vale plantarse ahora que a los veinte
minutos con un nombre mal escrito.

Si Ollama no responde, el error dice qué hacer, por orden: `ollama serve`,
`ollama pull llama3.2:3b`, `ollama list`. Y deja claro que no hay plan B en la
nube.

### Cómo se le pregunta, y qué se hace con lo que contesta

Temperatura **0** y `num_ctx` **explícito**. Lo segundo importa: sin él, Ollama
usa la ventana que traiga el Modelfile de cada modelo, y el mismo prompt daría
respuestas distintas según lo que hubiera descargado la máquina.

El prompt lleva los criterios de inclusión del protocolo, los temas excluidos, y
el título con el resumen recortado a 1200 caracteres. Se le dice explícitamente
que **no** mire el año ni el idioma, que ya los comprobó el filtro con datos. Y
se le exige responder solo con un JSON:

```json
{"decision": "incluir|excluir|dudoso", "motivo": "máximo doce palabras"}
```

La respuesta se interpreta **con tolerancia**: se busca el primer objeto JSON
equilibrado que traiga una decisión reconocible, y da igual que venga envuelto en
«Claro, aquí tienes:», en un bloque ```json, o detrás de un `{el artículo}` que
no es JSON.

> [!IMPORTANT]
> **Si la respuesta no se entiende, se reintenta una vez; si vuelve a fallar, el
> registro se queda en «dudoso».** Nunca se excluye por una respuesta que no se
> entendió (AGENTS.md, regla 4). Por lo mismo, un `"no"` suelto no se lee como
> «excluir»: puede estar contestando a otra cosa.

Toda decisión del modelo se guarda con `decidido_por = "modelo:NOMBRE"`, con la
etiqueta exacta (`modelo:qwen3:4b`). Un cribado hecho con un 1B y otro hecho con
un 4B no valen lo mismo, y dentro de seis meses nadie se va a acordar de con qué
se hizo. Lo que decía el filtro sigue en `decision_filtro` y `motivo_filtro`.

### El modelo que piensa en voz alta

Medido el **2026-09-12** con `qwen3:4b`: es un modelo de razonamiento, y Ollama
le pone la salida en el campo **`thinking`** dejando **`response` vacío**. El
primer cribado devolvió cero respuestas interpretables por esto, no por el
modelo.

La cura es mandar `"think": false` en la petición, que funciona igual en modelos
de razonamiento y en los que no lo son (comprobado con `qwen3:4b`, `qwen:4b` y
`llama2:7b`: ninguno lo rechaza). Como red de seguridad, si `response` viene
vacío se lee `thinking`, y antes de buscar el JSON se quitan los bloques
`<think>…</think>`: si no, se leería la opción que el modelo **descartó** por el
camino en vez de su conclusión.

---

## La auditoría de las exclusiones

Esto es lo que hace honesto al cribado automático. El filtro se equivoca poco,
pero un modelo de 4B en una tarjeta de 4 GB se equivoca lo suficiente como para
que no se le pueda confiar el descarte final. Si nadie mira nunca lo que se
descartó, la revisión está afirmando algo que no ha comprobado.

```bash
python -m tatewari pendientes demo --modo auditoria
```

Saca 20 exclusiones al azar (o todas, si hay menos) con su título, año, resumen
recortado y el motivo por el que se descartaron, y **registra la ronda** en
`auditoria.json`: fecha, semilla, tamaño de la población e identificadores. Con la
semilla se reconstruye exactamente la misma muestra, que es lo que convierte una
lista de veinte registros en una auditoría (AGENTS.md, regla 4).

Es la única forma de `pendientes` que escribe algo, y lo dice en su salida.

> El muestreo usa `random.sample`, no `sorted(key=lambda _: random.random())`.
> Ese atajo parece un barajado y no lo es: cuando dos claves salen iguales el
> desempate lo decide el orden original, así que no es uniforme. `random.sample`
> hace un muestreo sin reemplazo de verdad y no admite ese error.

---

## La búsqueda por parecido

Capa **opcional**, con embeddings locales. Convierte cada registro en un vector y
sirve para tres cosas concretas. No es una función genérica de «buscar»: son tres
usos, cada uno con su orden.

> [!IMPORTANT]
> **La similitud es una ayuda de lectura, no un criterio de inclusión.**
>
> Ninguna de estas tres órdenes puede cambiar por sí sola una decisión del
> cribado, y ninguna escribe en `decisiones.json`. Un número de coseno no es
> evidencia de que un artículo cumpla un criterio del protocolo: dos artículos
> pueden hablar de lo mismo y solo uno reportar remoción de DQO. La similitud
> sirve para decidir **qué leer primero**, y ahí se acaba su trabajo. Quien
> decide sigue siendo el filtro determinista, el modelo local o una persona, y
> siempre con su motivo escrito.
>
> Está garantizado por construcción, no por buena voluntad: las tres órdenes usan
> `Cribado.calcular()`, que lee y no escribe, y hay una prueba
> (`test_ordenar_no_cambia_ninguna_decision_del_cribado`) que lanza las tres y
> comprueba que `cribado.csv` queda byte por byte igual.

Y es opcional de verdad: si `nomic-embed-text` no está descargado, estas tres
órdenes fallan con un mensaje que dice qué hacer y **todo lo demás funciona
igual**. Nada de la cosecha, el cribado, el PRISMA o las decisiones pasa por
aquí.

### a) Ordenar por la pregunta de investigación

```bash
python -m tatewari ordenar demo --pregunta "remoción de DQO en humedal artificial precedido de biodigestor"
```

Ordena los registros por similitud coseno con la pregunta. Para esto se hizo:
cuando el cribado deja cien dudosos, dice por cuál empezar a leer. Con
`--modo dudoso` se mira solo esa parte, y con `--cuantos N` se acorta la lista.

### b) Los parecidos a uno dado

```bash
python -m tatewari similares demo R0007 --cuantos 10
```

### c) Casi duplicados

```bash
python -m tatewari casi-duplicados demo --umbral 0.97
```

Los registros que llegan aquí ya sobrevivieron a la deduplicación, así que cada
uno tiene una clave distinta: DOI distinto, o título distinto sin DOI. El
parecido de los vectores es lo único que queda para encontrar **el preprint y su
versión publicada**, o el mismo trabajo con el título retocado.

Cada par se reporta con un diagnóstico de *por qué* la deduplicación no lo
atrapó —«DOI distintos», «ninguno trae DOI», «uno de los dos no trae DOI»— y el
reporte queda en `casi_duplicados.csv`.

> [!WARNING]
> **Se reportan, no se fusionan.** Decidir que dos registros son el mismo trabajo
> es una decisión humana. Con 0,97 también salen dos estudios distintos del mismo
> grupo sobre el mismo humedal, y esos son dos artículos que cuentan por
> separado. El umbral es alto a propósito: con 0,90 la lista se llena de pares que
> solo comparten el tema, y una lista de falsos positivos no la revisa nadie.

### Qué se vectoriza, y la caché

Título más resumen. **Si no hay resumen, solo el título, y el vector queda
marcado como de baja calidad**: un título son diez palabras y un resumen
doscientas, así que el parecido calculado solo sobre el título es mucho más
grueso. Sale marcado en la salida como `(solo título)`. Marcarlo es lo honesto;
hacer como si valiera lo mismo sería engañar a quien lee el orden.

Vectorizar es lo caro de todo esto, así que los vectores se guardan en
`vectores.json`, en la carpeta de la revisión, indexados por el identificador
estable del registro y por un **hash del texto**. Si el texto no cambió, el vector
no se vuelve a pedir; si cambió —llegó el resumen que faltaba— se recalcula solo
ese. La segunda corrida sobre el fixture pide **un** vector, el de la pregunta, en
vez de catorce.

Dos avisos:

- **Cambiar de modelo descarta la caché entera.** Los vectores de dos modelos
  viven en espacios distintos y no son comparables: reutilizarlos daría un orden
  con toda la pinta de estar bien y sin ningún sentido. Se avisa cuando pasa.
- Se guarda en JSON con seis decimales, porque el proyecto no arrastra numpy por
  esto y a seis decimales el coseno no se mueve ni en 1e-6. El precio es el
  tamaño: un millar de registros son unos quince megas.

### Los dos endpoints de Ollama

Ollama cambió los embeddings de sitio a mitad de camino:

| Endpoint | Entrada | Salida | Lote |
|---|---|---|---|
| `/api/embed` | `input` (lista) | `embeddings` | el lote entero de una vez |
| `/api/embeddings` | `prompt` (uno) | `embedding` | uno por petición |

Se prueba el nuevo y, si responde 404, se usa el viejo. La ruta que funcionó se
recuerda. El orden importa: **primero** se comprueba que el modelo esté
descargado, y así un 404 solo puede significar «esa ruta no existe» y no «ese
modelo no está».

> Medido el 2026-09-12: pedirle un vector a un modelo **generativo** (`qwen3:4b`)
> no da un 404, da un **501** con «This server does not support embeddings». Por
> eso `ErrorHttp` guarda el cuerpo de la respuesta: sin ese texto solo se sabría
> que fue un 501, y el mensaje no podría decir que la cura es usar un modelo de
> embeddings de verdad.

---

## Cómo se consulta OpenAlex

OpenAlex **no acepta una booleana anidada arbitraria** dentro de un solo
filtro. El protocolo sí la tiene. Así que el AND/OR se despliega: una consulta
por cada par (término del eje × término del cruce).

```
"humedal artificial" AND "anaerobic"
```

que viaja así:

```
https://api.openalex.org/works?filter=title_and_abstract.search:%22humedal%20artificial%22%20AND%20%22anaerobic%22,from_publication_date:2016-01-01,to_publication_date:2026-12-31,language:es|en,type:article|review&per-page=200&cursor=*&mailto=...
```

### Los errores conocidos, medidos

Medido contra la API el **2026-09-12** con `"constructed wetland" AND
"anaerobic"` y la ventana 2016-2026. Cada fila tiene su prueba en
`tests/test_urls.py`.

**Ninguna de las formas malas devuelve error.** Todas responden 200, que es
peor: el recuento sale distinto y nadie se entera.

| Forma | Recuento | Qué pasa |
|---|---|---|
| sin filtro de idioma | 842 | — |
| `language:es\|en` ← el nuestro | **788** | es (5) + en (783) |
| `language:en` | 783 | |
| `language:languages/en` | **783** | Responde 200, pero se come el español |
| sin filtro de tipo | 842 | — |
| `type:article\|review` ← el nuestro | **614** | |
| `type:types/article` | **608** | Responde 200, pero se come las revisiones |
| `%20` y `AND` ← el nuestro | 842 | |
| `+` en vez de `%20` | 842 | Hoy da igual |
| `and` en minúsculas | 842 | Hoy da igual |
| **sin comillas** | **892** | Deja de buscar la frase y busca palabras sueltas |

Conclusión: los dos primeros errores son reales y **silenciosos**, que es la
peor clase. Los de `+` y minúsculas hoy no se reproducen, pero el código sigue
usando `%20` y mayúsculas, que es la forma documentada, la que se pega en un
navegador sin sorpresas y la que se lee en la bitácora.

El que no estaba en la lista y sí cambia el resultado son **las comillas**.

Y que el `AND` es un AND de verdad, también medido:

| Consulta | Recuento |
|---|---|
| `"constructed wetland"` | 21 371 |
| `"constructed wetland" AND "anaerobic"` | 1 469 |
| `"constructed wetland" AND "zzzzqqqwxyz"` | **0** |

Ese 0 es la prueba: si el `AND` se ignorara, la palabra inventada no filtraría
nada.

### Cuota: la cosecha no cabe de una vez

OpenAlex cobra por **créditos**, no por peticiones. Medido el mismo día en la
cola anónima: 1000 créditos por ventana, 10 por petición, unas **100
peticiones**. Cuarenta ecuaciones con hasta 5 páginas cada una son hasta 200.

Así que `http.py` lee las cabeceras `x-ratelimit-*` y la cosecha **se para
sola** cuando no le quedan créditos para una ecuación entera: mejor cortar
limpio que dejar una ecuación a medias diciendo en la bitácora que se buscó
algo que en realidad no se buscó del todo. Lo hecho queda guardado y se retoma
cuando la cuota se repone.

Falta por comprobar si la cola educada (con `mailto`) da más.

### El resumen viene del revés, y casi nunca viene

OpenAlex no devuelve el resumen como texto corrido, sino como
`abstract_inverted_index`: un diccionario de palabra → lista de posiciones. Una
palabra puede aparecer en **varias** posiciones, así que hay que colocar cada
aparición en su hueco y unir por posición. Ordenar las palabras por su primera
aparición da un texto distinto y mal: se pierden todas las repeticiones. En una
obra real de la captura, 34 de 160 palabras aparecían repetidas.

> [!IMPORTANT]
> **Solo 6 de cada 50 obras traen resumen** (12 %, medido el 2026-09-12 sobre
> esta ecuación). El resto se normaliza a `"NR"`.
>
> Esto no es un fallo, es el material con el que hay que trabajar, y condiciona
> el cribado: el protocolo `humedales.json` manda los registros sin resumen a
> `dudoso`, así que el 88 % cae en revisión humana, que sería tanto como no
> cribar. La respuesta es la segunda vuelta con el modelo local: `cribar
> --modelo-local` le pasa esos dudosos, y cuando un registro no trae resumen el
> prompt le dice que decida **solo con el título** y que responda «dudoso» si el
> título no basta. Lo que el modelo no resuelva sigue yendo a una persona.
>
> No lo arregla del todo: un título no es un resumen. La cosecha sigue informando
> del porcentaje en cada lote para que el dato esté a la vista.

Crossref tampoco ayuda mucho: de los items reales capturados, ninguno traía
`abstract`.

### Cuando no hay versión abierta

Unpaywall marca el registro como `requiere_credencial_institucional` y la
cosecha sigue. **No se intenta ninguna otra vía**: ni Sci-Hub, ni raspar la web
de la editorial, ni rodear el muro de pago (AGENTS.md, regla 5). El texto se
pide por la biblioteca de la institución, que para eso está.

---

## El fixture es sintético: no lo cites

> **Aviso.** Los 14 registros de `fixtures/demo.json` son **inventados**. No son
> literatura real: los DOI, los autores, las revistas, los años y las cifras de
> los resúmenes no corresponden a ningún artículo existente. Están ahí para
> probar el código y **no deben citarse, exportarse a un gestor bibliográfico
> ni aparecer en ninguna revisión**.

Para que sea imposible confundirlos:

- Todos los títulos empiezan por `SINTETICO DE PRUEBA`.
- Los DOI usan el prefijo `10.0000/`, que no está asignado a ninguna editorial.
- Las URL apuntan a `ejemplo.invalid`, un dominio que por diseño nunca resuelve
  (RFC 2606).

El fixture cubre a propósito los casos que rompen las cosas:

| Caso | Registro |
|---|---|
| Artículo duplicado | `sintetico.003`, dos veces: DOI en mayúsculas, título sin acentos, otra revista |
| Anterior a la ventana | `sintetico.004`, de 2009 |
| Idioma no admitido | `sintetico.005`, en portugués |
| Excluido por tema | `sintetico.006`, análisis de ciclo de vida |
| Sin resumen | `sintetico.007`, con `resumen` en `"NR"` |
| Sin identificador | uno con `doi`, `revista`, `autores` y `citas` en `"NR"` |
| Dudoso de verdad | `sintetico.011`: humedales, pero quizá no de agua residual |
| Plural que no cuadra | `sintetico.011` dice *treatment wetlands* y el protocolo, `treatment wetland` |
| Varios que sí cumplen | el resto |

---

## Pruebas

```bash
python -m pytest
```

675 pruebas, todas **sin red** (AGENTS.md, regla 6). Ninguna toca una API real:
salen de `protocolos/`, de `fixtures/` y de `tests/respuestas/`. El código de
red se prueba con un cliente falso; los reintentos, con un reloj falso, así que
la suite tarda un segundo.

`tests/respuestas/` tiene dos clases de archivo:

- Los `*_pagina*.json` sin `real` en el nombre están **escritos según la
  documentación** y llevan datos sintéticos.
- Los `*_real_*.json` son **capturas de verdad** del 2026-09-12. Su trabajo es
  distinto: no comprueban que el código haga lo que queremos, sino que la forma
  real de la respuesta siga siendo la que creíamos. Si OpenAlex o Crossref
  cambian algo, son las que se ponen rojas.

La construcción de URLs se prueba **sin simular nada**: se compara la cadena
generada contra la forma documentada, carácter a carácter.

---

## Pendiente de verificar

**Ninguna prueba llama a una API real**, ni debe hacerlo (AGENTS.md, regla 6).
Lo que sigue se comprobó **a mano**, el 2026-09-12, con peticiones sueltas
fuera de la suite.

### Comprobado

- ✅ **El `AND` de OpenAlex es un AND.** Ver la tabla de arriba: una palabra
  inventada deja el recuento en 0.
- ✅ **Las comillas buscan la frase.** Sin ellas el recuento sube.
- ✅ **`language:languages/en` y `type:types/article` no fallan, mienten.**
  Responden 200 y estrechan la búsqueda sin avisar.
- ✅ **Unpaywall exige el correo.** Sin `?email=` responde **HTTP 422**:
  `"Email address required in API call"`. Como es un 4xx, `http.py` no lo
  reintenta, que es lo correcto.
- ✅ **Las cabeceras de cuota existen.** `x-ratelimit-limit: 1000`,
  `x-ratelimit-credits-used: 10` por petición en la cola anónima.
- ✅ **La forma de las respuestas.** `tests/respuestas/openalex_real_*.json` y
  `crossref_real_pagina1.json` son capturas de verdad, y la normalización pasa
  contra ellas en `tests/test_respuestas_reales.py`.
- ✅ **Ollama pone la salida de un modelo de razonamiento en `thinking`.** Con
  `qwen3:4b`, `response` llega **vacío**. Mandar `"think": false` lo arregla, y
  ni `qwen3:4b` ni `qwen:4b` ni `llama2:7b` rechazan ese campo.
- ✅ **`ordenar demo` funciona con `nomic-embed-text`.** Comprobado el
  2026-09-17: 13 registros vectorizados a 768 dimensiones, 151 KB de caché, y la
  segunda corrida pide un solo vector (el de la pregunta). El primer resultado
  para «remoción de DQO en humedal artificial precedido de biodigestor» fue el
  artículo de tanque séptico más humedal con eficiencia de remoción, que es la
  respuesta correcta.
- ✅ **Un modelo generativo no sirve para embeddings.** Pedirle un vector a
  `qwen3:4b` responde **501** «This server does not support embeddings», no un
  404. El mensaje de error lo distingue y dice que la cura es un modelo de
  embeddings.
- ✅ **`cribar demo --modelo-local` funciona de punta a punta** en esta máquina:
  eligió `qwen3:4b` (4B, Q4_K_M, 2,5 GB) entre doce modelos descargados, resolvió
  los dos dudosos del fixture y dejó cada decisión firmada como
  `modelo:qwen3:4b`. Unos 4 s por registro, con el primero más lento porque carga
  el modelo en memoria.

### Sigue sin comprobar

1. **La cola educada.** Falta medir si `mailto` sube los 1000 créditos. Se ve
   en la cabecera `x-ratelimit-limit` de la primera cosecha con correo puesto.
2. **El vocabulario de tipos.** La tabla de `fuentes/crossref.py` cubre lo que
   apareció en la captura. Lo que no esté se deja tal cual vino, nunca se
   adivina, pero falta ver qué tipos salen de verdad en este dominio.
3. **El idioma.** No siempre viene y no siempre es fiable. Se copia tal cual, o
   `"NR"`. Falta medir cuánto llega vacío.
4. **Cuánto se equivoca el modelo local.** Lo decidido por `modelo:` está
   firmado y se puede comparar contra lo que decida una persona, pero **nadie lo
   ha medido todavía**. Hasta que se mida, la auditoría por muestreo no es
   opcional. Para medirlo hace falta un lote real revisado a mano, no el fixture
   sintético.
5. **Si un 3B da mejor resultado que un 4B en este dominio.** El orden de
   preferencia está razonado por lo que entra en 4 GB de VRAM, no por calidad
   medida en cribado de resúmenes.
6. **Si 0,97 es el umbral correcto para los casi duplicados.** Está elegido por
   lo que suele separar un preprint de su versión publicada, no medido sobre un
   corpus real de esta revisión.

Cuando algo de esto se compruebe, se corrige aquí y se borra de la lista.
