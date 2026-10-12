# Propuesta de arquitectura — módulo `biblioteca`

> Documento de diseño. **No hay código todavía**: esto es lo que se va a construir
> y por qué, para revisarlo antes de escribir nada.
>
> Fecha: 2026-09-17 · Destino: `src/tatewari/`

---

## 0. El punto de partida: qué ya existe

Antes de proponer nada conviene dejar escrito qué parte del encargo **ya está
resuelta en el repositorio**, porque cambia el tamaño del trabajo.

| # | Lo pedido | Estado | Dónde |
|---|-----------|--------|-------|
| 1 | Entrada: tema + idiomas + ventana + dimensiones ad hoc | 🟡 Parcial | `protocolo.py` ya tiene `idiomas`, `ventana` y `clasificacion` configurable. Falta: tema en lenguaje natural → protocolo |
| 2 | Descomponer en varias queries, barrido por región | 🟡 Parcial | `openalex.construir_ecuaciones()` despliega `eje × cruce`. Falta: varios ejes a la vez |
| 3 | Metadatos desde la API, nunca del modelo; marcar lo que falta | ✅ **Hecho** | Regla 2 de AGENTS.md, `"NR"` literal, `fuentes/__init__.py` |
| 4 | Anotación con modelo local, bajo contexto, 4 GB VRAM | ✅ **Hecho** | `cribado_modelo.py` solo pregunta por dudosos, recorta el resumen |
| 5 | Persistencia SQLite, dedup, crecimiento incremental | 🔴 **Falta SQLite** | El dedup ✅ existe (`dedup.py`), pero la persistencia es JSON por revisión |
| 6 | Reporte Markdown con tablas cruzadas + export `.bib`/`.ris` | 🔴 **Falta** | El README ya lo declara pendiente |
| 7 | Reportar huecos vacíos explícitamente | 🟡 Parcial | `search_log.csv` ya guarda el nº de resultados por ecuación; falta el reporte |

**Conclusión: no es un módulo nuevo, son cuatro adiciones a Tatewari.** Construir
una "literature-library" aparte duplicaría `cosecha`, `dedup`, `cribado` y
`fuentes/`, y tendría que mantenerse dos veces.

### Sobre el nombre

`literature-library` desentona: todos los módulos del proyecto tienen nombre en
español (`cosecha`, `cribado`, `dedup`, `auditoria`). La propuesta es
**`biblioteca`**, que además dice lo que es: el acervo acumulado que sobrevive a
las revisiones individuales.

---

## 1. La decisión de fondo: qué es "fuente de verdad"

Pediste SQLite como fuente de verdad. Hay una tensión real con AGENTS.md que
conviene resolver de frente, porque determina todo el resto del diseño.

Las reglas 3 y 4 obligan a conservar **la ecuación literal de cada búsqueda** y
**la auditoría registrada de cada exclusión**. Hoy eso vive en archivos
append-only (`search_log.csv`, `auditoria.json`, `decisiones.json`) que están
cubiertos por 18 módulos de pruebas. Meterlos dentro de una base de datos
implicaría reescribir `cosecha`, `cribado` y `auditoria`, y romper esas pruebas.

**Propuesta: dos capas, con una regla clara de reconstrucción.**

```
Evidencia (append-only, por revisión)        Biblioteca (consultable, acumulativa)
revisiones/<nombre>/                          biblioteca.sqlite3
  search_log.csv    ← regla 3                   ├── se llena DESDE la evidencia
  decisiones.json   ← regla 4                   ├── se puede BORRAR y rehacer
  auditoria.json    ← regla 4                   └── nunca es la única copia
  registros.json
  estado.json
        │                                              ▲
        └──────────── importar ───────────────────────┘
                   (reconstruible)
```

La regla que lo gobierna, en una línea:

> **La base se puede reconstruir desde los archivos de evidencia; los archivos de
> evidencia no se pueden reconstruir desde la base.**

Con eso, SQLite **sí** es la fuente de verdad para todo lo que se consulta, se
clasifica, se anota y se exporta — que es lo que pediste y lo que la app de
escritorio necesita. Y una base corrupta deja de ser una catástrofe: se corre
`biblioteca reconstruir` y vuelve. Sin esto, un `.sqlite3` roto se lleva por
delante meses de revisión y la trazabilidad PRISMA con ella.

Habría una orden `biblioteca reconstruir` que rehace la base desde cero
recorriendo `revisiones/`. Lo único que **no** se puede reconstruir son las
anotaciones y etiquetas manuales tuyas, así que esas van además a un
`biblioteca_manual.json` de respaldo.

---

## 2. Estructura de archivos

Módulos nuevos, siguiendo las convenciones del proyecto (un módulo = una
responsabilidad, docstring largo que explica el *porqué*, pruebas espejo):

```
src/tatewari/
  biblioteca.py         # NUEVO  Conexión, alta con dedup, consultas
  esquema.sql           # NUEVO  DDL versionado (leído por biblioteca.py)
  dimensiones.py        # NUEVO  Ejes de clasificación configurables
  informe.py            # NUEVO  Markdown, tablas cruzadas, huecos
  exportar.py           # NUEVO  BibTeX y RIS
  propuesta.py          # NUEVO  Tema en lenguaje natural → borrador de protocolo
  fuentes/
    pubmed.py           # NUEVO  E-utilities (esearch + efetch), para biomédico
    arxiv.py            # NUEVO  API Atom
  protocolo.py          # TOCADO  Admitir `dimensiones` y `consulta` como lista
  cosecha.py            # TOCADO  Registrar huecos (ecuaciones con 0 resultados)
  cli.py                # TOCADO  Órdenes nuevas

tests/
  test_biblioteca.py    test_dimensiones.py   test_informe.py
  test_exportar.py      test_propuesta.py     test_pubmed.py   test_arxiv.py

fixtures/
  pubmed_efetch.xml     arxiv_atom.xml        # Para probar sin red (regla 6)
```

Órdenes nuevas de la CLI:

```
python -m tatewari proponer "biodigestor + humedal para PTAR rural"   → borrador de protocolo
python -m tatewari biblioteca importar demo                           → vuelca una revisión a la base
python -m tatewari biblioteca buscar "remoción DQO" --dimension region=México
python -m tatewari biblioteca reconstruir
python -m tatewari etiquetar demo --dimension clima                   → asigna dimensiones
python -m tatewari informe demo --cruzar region clima                 → Markdown con tabla cruzada
python -m tatewari exportar demo --formato bib                        → .bib / .ris
python -m tatewari huecos demo                                        → qué se buscó y salió vacío
```

---

## 3. Esquema SQLite

Diseñado alrededor de una idea: **las dimensiones de clasificación no van como
columnas**. Si `region` y `clima` fueran columnas, añadir un eje nuevo exigiría
migrar la base cada vez, y tú pediste ejes ad hoc por proyecto. Van como filas en
`etiqueta`, que es genérica: cualquier eje, sin tocar el esquema.

```sql
PRAGMA journal_mode = WAL;      -- la GUI puede leer mientras la CLI escribe
PRAGMA foreign_keys = ON;       -- hay que activarlo en CADA conexión

CREATE TABLE esquema_version (version INTEGER NOT NULL);

-- ───────────────────────── El acervo ─────────────────────────

CREATE TABLE referencia (
    id              TEXT PRIMARY KEY,        -- R0001, estable entre cosechas
    doi             TEXT UNIQUE,             -- normalizado; NULL si no hay
    clave_titulo    TEXT NOT NULL,           -- texto.clave_alfanumerica(), dedup sin DOI
    titulo          TEXT NOT NULL,
    anio            TEXT NOT NULL DEFAULT 'NR',   -- TEXT: admite el literal "NR"
    idioma          TEXT NOT NULL DEFAULT 'NR',
    revista         TEXT NOT NULL DEFAULT 'NR',
    volumen         TEXT NOT NULL DEFAULT 'NR',
    numero          TEXT NOT NULL DEFAULT 'NR',
    paginas         TEXT NOT NULL DEFAULT 'NR',
    tipo            TEXT NOT NULL DEFAULT 'NR',
    citas           TEXT NOT NULL DEFAULT 'NR',
    resumen         TEXT NOT NULL DEFAULT 'NR',
    oa_url          TEXT NOT NULL DEFAULT 'NR',
    oa_estado       TEXT NOT NULL DEFAULT 'NR',
    alta            TEXT NOT NULL,           -- ISO 8601, primera vez que entró
    visto           TEXT NOT NULL            -- última vez que una cosecha lo trajo
);
CREATE INDEX idx_ref_clave  ON referencia(clave_titulo);
CREATE INDEX idx_ref_anio   ON referencia(anio);

CREATE TABLE autor (
    referencia_id TEXT NOT NULL REFERENCES referencia(id) ON DELETE CASCADE,
    orden         INTEGER NOT NULL,          -- el orden importa para citar
    nombre        TEXT NOT NULL,
    PRIMARY KEY (referencia_id, orden)
);
CREATE INDEX idx_autor_nombre ON autor(nombre);

-- ──────────────── Procedencia: de dónde salió cada cosa ────────────────

CREATE TABLE revision (
    nombre        TEXT PRIMARY KEY,          -- "demo", "humedales"
    protocolo     TEXT NOT NULL,             -- ruta del .json
    protocolo_sha TEXT NOT NULL,             -- si cambia el protocolo, se nota
    creada        TEXT NOT NULL
);

CREATE TABLE ecuacion (                      -- espejo de search_log.csv (regla 3)
    id          INTEGER PRIMARY KEY,
    revision    TEXT NOT NULL REFERENCES revision(nombre) ON DELETE CASCADE,
    fuente      TEXT NOT NULL,               -- openalex | crossref | pubmed | arxiv
    literal     TEXT NOT NULL,               -- la ecuación TAL CUAL se envió
    url         TEXT NOT NULL,               -- la URL completa
    eje         TEXT,                        -- qué dimensión barría, si barría alguna
    valor_eje   TEXT,                        -- "México", "Brasil"…
    resultados  INTEGER NOT NULL,
    fecha       TEXT NOT NULL
);
CREATE INDEX idx_ec_hueco ON ecuacion(revision, resultados);

CREATE TABLE procedencia (                   -- qué ecuación trajo qué referencia
    referencia_id TEXT NOT NULL REFERENCES referencia(id) ON DELETE CASCADE,
    ecuacion_id   INTEGER NOT NULL REFERENCES ecuacion(id) ON DELETE CASCADE,
    PRIMARY KEY (referencia_id, ecuacion_id)
);

-- ──────────────── Cribado: espejo de decisiones.json (regla 4) ────────────────

CREATE TABLE decision (
    revision      TEXT NOT NULL REFERENCES revision(nombre) ON DELETE CASCADE,
    referencia_id TEXT NOT NULL REFERENCES referencia(id)   ON DELETE CASCADE,
    estado        TEXT NOT NULL CHECK (estado IN ('incluido','excluido','dudoso')),
    motivo        TEXT NOT NULL,
    origen        TEXT NOT NULL CHECK (origen IN ('regla','modelo','humano')),
    fecha         TEXT NOT NULL,
    PRIMARY KEY (revision, referencia_id)
);

-- ──────────────── Clasificación cruzada: ejes ad hoc ────────────────

CREATE TABLE dimension (
    revision    TEXT NOT NULL REFERENCES revision(nombre) ON DELETE CASCADE,
    nombre      TEXT NOT NULL,               -- "region", "clima", "escala"
    tipo        TEXT NOT NULL CHECK (tipo IN ('determinista','derivado','modelo')),
    descripcion TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (revision, nombre)
);

CREATE TABLE etiqueta (
    revision      TEXT NOT NULL,
    referencia_id TEXT NOT NULL REFERENCES referencia(id) ON DELETE CASCADE,
    dimension     TEXT NOT NULL,
    valor         TEXT NOT NULL,             -- "NR" si no se pudo determinar
    origen        TEXT NOT NULL CHECK (origen IN ('termino','tabla','modelo','humano')),
    verificado    INTEGER NOT NULL DEFAULT 0 CHECK (verificado IN (0,1)),
    fecha         TEXT NOT NULL,
    PRIMARY KEY (revision, referencia_id, dimension, valor),
    FOREIGN KEY (revision, dimension) REFERENCES dimension(revision, nombre) ON DELETE CASCADE
);
CREATE INDEX idx_etiq_cruce ON etiqueta(revision, dimension, valor);

CREATE TABLE anotacion (                     -- la nota de relevancia del modelo
    revision      TEXT NOT NULL,
    referencia_id TEXT NOT NULL REFERENCES referencia(id) ON DELETE CASCADE,
    texto         TEXT NOT NULL,             -- 1-2 líneas
    modelo        TEXT NOT NULL,             -- qué modelo la escribió
    fecha         TEXT NOT NULL,
    PRIMARY KEY (revision, referencia_id)
);

-- ──────────────── Honestidad: los huecos (requisito 7) ────────────────

CREATE TABLE hueco (
    revision    TEXT NOT NULL REFERENCES revision(nombre) ON DELETE CASCADE,
    dimension   TEXT NOT NULL,
    valor       TEXT NOT NULL,               -- "Bolivia"
    ecuaciones  INTEGER NOT NULL,            -- cuántas se lanzaron
    resultados  INTEGER NOT NULL,            -- cuántos volvieron (0 = hueco)
    fecha       TEXT NOT NULL,
    PRIMARY KEY (revision, dimension, valor)
);

-- ──────────────── Búsqueda de texto ────────────────

CREATE VIRTUAL TABLE referencia_fts USING fts5(
    titulo, resumen, content='referencia', content_rowid='rowid'
);
```

### Notas sobre decisiones del esquema

- **`anio` y `citas` son `TEXT`, no `INTEGER`.** Parece un error y no lo es: la
  regla 2 obliga a escribir el literal `"NR"` cuando el dato no vino. Un
  `INTEGER NULL` volvería a introducir la ambigüedad entre "no se sabe" y "cero"
  que `"NR"` existe para eliminar. El coste es ordenar por año con un `CAST`.
- **`"NR"` *es* la marca de "sin verificar" que pediste.** No hace falta una
  columna aparte: ya es la convención del proyecto y está en AGENTS.md regla 2.
- **`etiqueta.origen`** distingue si un eje lo asignó una coincidencia de término
  (gratis y auditable), una tabla de equivalencias, el modelo local (falible), o
  tú a mano. Sin eso no se puede saber cuánto pesa una tabla cruzada.
- **Sin tablas `STRICT`.** Requieren SQLite ≥ 3.37 y no vale la pena arriesgar
  que falle en una máquina con Python empaquetado más viejo. Los `CHECK` cubren
  lo importante.
- **Deduplicación al dar de alta**: DOI normalizado primero, `clave_titulo`
  después. Reusa `dedup.normalizar_doi()` y `texto.clave_alfanumerica()` tal
  cual — no se escribe lógica de dedup nueva. Los casi duplicados que se escapen
  los sigue atrapando `embeddings.casi_duplicados()`.

---

## 4. Dimensiones de clasificación configurables

Se añaden al protocolo JSON. Tres tipos, y la diferencia entre ellos es
exactamente la diferencia entre gastar tokens y no gastarlos:

```jsonc
"dimensiones": {
  "region": {
    "tipo": "determinista",          // detección por término: gratis, auditable
    "terminos": {
      "México":  ["México", "Mexico", "mexicano", "SLP", "Potosí"],
      "Brasil":  ["Brasil", "Brazil", "brasileño"],
      "Perú":    ["Perú", "Peru", "peruano"]
    }
  },
  "clima": {
    "tipo": "derivado",              // tabla de equivalencias: gratis, no alucinable
    "de": "region",
    "mapa": { "México": "semiárido", "Brasil": "tropical", "Perú": "andino" }
  },
  "escala": {
    "tipo": "modelo",                // única que cuesta una llamada a Ollama
    "opciones": ["laboratorio", "piloto", "escala real", "NR"]
  }
}
```

**Una corrección al encargo, y creo que te conviene.** Pusiste `país→clima` como
ejemplo de lo que haría el modelo. No debería: es una tabla de equivalencias.
Pasarlo por un modelo de 4 B lo vuelve más lento, más caro y *alucinable* — y un
clima mal asignado contamina la tabla cruzada en silencio. Con `tipo: derivado`
la asignación es determinista, reproducible y la puedes corregir editando el
protocolo. Al modelo solo se le pregunta lo que de verdad exige leer el resumen,
como la escala del experimento.

El orden de resolución sería: `determinista` → `derivado` → `modelo` (solo lo que
quedó en `NR`). En una revisión de 2.000 registros eso suele dejar al modelo
trabajando sobre unos pocos cientos en vez de sobre todo el corpus.

---

## 5. El barrido por región

Hoy `protocolo.consulta` es un objeto único (`eje` + `cruce`). Se amplía para
admitir **una lista**, manteniendo compatibilidad con los protocolos ya escritos:

```jsonc
"consulta": [
  { "eje": "P2_humedal", "cruce": ["anaerobic", "UASB", "septic tank"] },
  { "eje": "P2_humedal", "cruce_dimension": "region" }   // barrido explícito
]
```

`cruce_dimension` toma los valores de la dimensión y lanza una ecuación por cada
uno. Cada ecuación se registra en `ecuacion` con su `eje` y `valor_eje`, y de ahí
sale el requisito 7 casi solo: **toda combinación con `resultados = 0` se escribe
en `hueco`** y aparece en el informe con nombre y apellido:

```markdown
## Huecos encontrados

La búsqueda se lanzó explícitamente para estas regiones y **no devolvió ningún
resultado relevante**. Esto es un hallazgo, no una omisión:

| Región   | Ecuaciones lanzadas | Resultados |
|----------|--------------------:|-----------:|
| Bolivia  |                   4 |          0 |
| Paraguay |                   4 |          0 |
```

---

## 6. Del tema en lenguaje natural al protocolo

`python -m tatewari proponer "..."` produce un **borrador** que tú editas. Dos
salvaguardas, ambas necesarias:

1. **El modelo propone términos de búsqueda, nunca metadatos.** Sugerir que
   «humedal construido» es sinónimo de «constructed wetland» es una tarea de
   lenguaje legítima. Inventar un DOI no lo es. La regla 2 se mantiene intacta
   porque aquí no se genera ningún dato bibliográfico.
2. **El borrador pasa por `validar_protocolo()` antes de poder usarse**, y sale a
   un archivo que tú revisas. Nunca se cosecha directo desde lo que dijo el
   modelo.

Detalle de los 4 GB: generar el protocolo entero de un tirón es una respuesta
larga para `qwen3:4b` y sale mal. Se genera **un bloque por llamada** (una para
el bloque de población, otra para el de intervención…), que es exactamente el
patrón de contexto corto que ya usa `cribado_modelo.py`.

---

## 7. Las APIs: cuáles, por qué, y cuáles necesitan clave

### Las que ya están y no necesitan nada

| API | Clave | Por qué está |
|-----|-------|--------------|
| **OpenAlex** | ❌ No | Fuente primaria. ~250 M de obras, filtros estructurados por año/idioma/tipo, y su `mailto` te mete en la cola educada. Ya configurado en tu `.env` |
| **Crossref** | ❌ No | Segunda opinión. Cubre bien lo que tiene DOI y a veces trae resumen donde OpenAlex no |
| **Unpaywall** | ❌ No (exige correo) | Localiza la versión en acceso abierto legal de un DOI. Ya configurado |

### Las que propongo añadir

| API | Clave | Por qué |
|-----|-------|---------|
| **PubMed / PMC** (E-utilities) | ⚠️ **Opcional, y es la única que te pediría** | Ya está permitida por AGENTS.md regla 5 pero no implementada. Indispensable en cuanto el tema roce lo biomédico — y "coliformes fecales en efluente" lo roza |
| **arXiv** | ❌ No | Permitida por regla 5, no implementada. Barata de añadir. Útil para ingeniería y materiales (tu caso de BTC) |

**La única clave que tendrías que conseguir es la de NCBI, y es opcional.** Sin
ella, E-utilities te da 3 peticiones/segundo; con ella, 10. Es gratuita, se saca
en unos minutos desde una cuenta NCBI, y valdría la pena si haces cosechas
grandes. Iría como `TATEWARI_NCBI_API_KEY` en el `.env`, y el código funciona sin
ella sin quejarse.

### Las dos que pediste y que requieren una decisión tuya

Aquí me detengo en vez de improvisar, porque AGENTS.md dice que ningún encargo
posterior puede relajar sus reglas.

**Semantic Scholar** — la pediste, pero **no está en la lista blanca de la regla
5**, que enumera taxativamente: OpenAlex, Crossref, Unpaywall, arXiv y PMC. Es
una API legal y abierta, así que la objeción no es de fondo: es que la regla es
una lista cerrada y añadirla exige que tú edites AGENTS.md primero. Aparte, un
dato práctico: sin clave, el límite es un cupo *compartido entre todos los
usuarios anónimos* y en la práctica devuelve 429 constantemente; la clave
gratuita se pide por formulario y la aprobación tarda. Mi lectura es que aporta
poco sobre OpenAlex + Crossref para justificar ambas cosas.

**SerpAPI como respaldo de Google Scholar** — pediste que lo evaluara. Mi
recomendación es **no**, por tres razones acumuladas: (a) la regla 5 prohíbe
raspar Google Scholar, y un intermediario de pago que hace el raspado por ti
cumple la letra pero no el espíritu; (b) son unos ~$75 USD/mes por un volumen
modesto de búsquedas, contra cero de OpenAlex; (c) Scholar no da metadatos
estructurados — daría exactamente el tipo de dato incompleto que la regla 2
existe para evitar. La cobertura que buscas sale más barata añadiendo PubMed y
arXiv.

### Un hueco real de cobertura que conviene que sepas

Tus temas son mexicanos y rurales: PTAR, biodigestores, BTC, agroecología. Buena
parte de esa literatura está en español en **SciELO, Redalyc y repositorios
institucionales** (el de la UASLP, sin ir más lejos). OpenAlex indexa SciELO solo
parcialmente, así que hay literatura latinoamericana pertinente que este sistema
**no va a encontrar**, por bien configurado que esté.

No lo meto en la propuesta porque también exigiría modificar la regla 5, y
prefiero que sea una decisión tuya y no un añadido silencioso. Si te interesa, la
vía limpia es **DOAJ** (API libre, sin clave, buena cobertura de revistas
iberoamericanas en acceso abierto) y posiblemente **LA Referencia** vía OAI-PMH.
Dilo y lo evalúo en serio.

---

## 8. Salidas

**Informe Markdown** (`informe.py`), reconstruible en cualquier momento desde la
base sin perder anotaciones, porque la base es quien las guarda:

```markdown
# <título del protocolo>
Generado: 2026-09-17 · 412 referencias · 38 incluidas · 12 dudosas

## Flujo PRISMA            ← reusa prisma.diagrama()
## Síntesis por <dimensión 1>
## Tabla cruzada: región × clima
| Referencia | Región | Clima     | Escala      |
## Huecos encontrados      ← requisito 7
## Referencias             ← con el "NR" visible donde falte el dato
```

**Export** (`exportar.py`): `.bib` y `.ris`. Tres detalles que importan:

- Los campos en `"NR"` **se omiten del registro BibTeX** en vez de exportarse
  como la cadena literal `NR`, que ensuciaría Zotero. Pero el informe Markdown sí
  los muestra: es donde la ausencia tiene que verse.
- Claves de cita estables y legibles: `garcia2021humedal`, derivadas del primer
  autor + año + primera palabra útil del título.
- Escapado de acentos y de `{}` en BibTeX, y UTF-8 explícito en todo `open()`
  (regla 8).

Y una salvaguarda que ya exige el README: `fixtures/demo.json` es sintético y no
debe exportarse a un gestor bibliográfico. El exportador debe **negarse** a
exportar una revisión marcada como fixture.

---

## 9. Orden de construcción

Cuatro encargos, cada uno con sus pruebas sin red (regla 6), cada uno utilizable
por sí solo:

| # | Encargo | Entrega | Depende de |
|---|---------|---------|-----------|
| 1 | **Biblioteca** | `esquema.sql`, `biblioteca.py`, `biblioteca importar/buscar/reconstruir` | — |
| 2 | **Salidas** | `informe.py`, `exportar.py`, `.bib`/`.ris`, informe Markdown | 1 |
| 3 | **Dimensiones** | `dimensiones.py`, `consulta` como lista, tablas cruzadas, `hueco` | 1, 2 |
| 4 | **Fuentes y entrada** | `fuentes/pubmed.py`, `fuentes/arxiv.py`, `propuesta.py` | 1 |

Empezar por la biblioteca no es casual: los otros tres escriben o leen de ella, y
hacerla primero evita construir dos veces el acceso a datos. Al terminar el
encargo 2 ya tendrías el ciclo completo que pediste — cosechar, cribar, informe y
`.bib` — aunque sin ejes ad hoc todavía.

---

## 10. Lo que necesito que decidas

1. **¿La capa doble de la §1 te convence**, o quieres SQLite como almacén único
   aunque implique reescribir `cosecha`/`cribado`/`auditoria` y sus pruebas?
2. **¿Autorizas editar AGENTS.md regla 5** para añadir fuentes? Y si sí, ¿cuáles:
   Semantic Scholar, DOAJ, ambas, ninguna?
3. **¿Sacas la clave de NCBI?** No es bloqueante; sin ella PubMed va más lento.
4. **¿Arranco por el encargo 1**, o prefieres otro orden?

---

## Apéndice — una discrepancia menor

Describiste Tatewari como una app de escritorio PySide6. En el repositorio **no
hay nada de PySide6 ni PyQt**: es una CLI (`python -m tatewari`), y ni
`pyproject.toml` ni `requirements.txt` mencionan una GUI. Puede que la interfaz
viva en otro sitio o esté por hacerse.

No cambia nada de esta propuesta — el esquema en WAL y los módulos sin estado
sirven igual a una CLI que a una GUI — pero si hay una capa PySide6 en algún
lado, dímelo y reviso que `biblioteca.py` encaje con cómo lee los datos.
