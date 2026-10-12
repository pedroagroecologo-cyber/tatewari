-- Esquema de la biblioteca acumulativa de Tatewari.
--
-- Lo lee `biblioteca.py` al abrir una base nueva. Va en un archivo aparte y no
-- incrustado en el código porque un esquema se lee mucho más de lo que se
-- escribe, y aquí se puede mirar entero de una vez.
--
-- Dos ideas gobiernan el diseño:
--
-- 1. **Las dimensiones de clasificación no son columnas.** Si `region` y
--    `clima` fueran columnas, añadir un eje nuevo exigiría migrar la base. Van
--    como filas en `etiqueta`, que es genérica: cualquier eje, sin tocar esto.
--
-- 2. **Los identificadores de la biblioteca son suyos.** Una revisión numera
--    R0001, R0002… y otra revisión vuelve a empezar por R0001 hablando de otro
--    artículo. Si la biblioteca reusara esos números, dos revisiones se
--    pisarían. Aquí cada referencia tiene su `B00001`, y `equivalencia` guarda
--    a qué identificador local corresponde en cada revisión. Así el rastro
--    PRISMA de cada revisión sigue siendo válido tal como está.
--
-- Los PRAGMA no están aquí: `journal_mode` se graba en el archivo una vez y
-- `foreign_keys` hay que activarlo en cada conexión, así que ambos viven en
-- `biblioteca.py`, que es quien conecta.

CREATE TABLE IF NOT EXISTS esquema_version (
    version INTEGER NOT NULL
);

-- ─────────────────────────────── El acervo ───────────────────────────────

-- Una fila por artículo único de toda la biblioteca.
--
-- `anio` y `citas` son TEXT y no INTEGER a propósito: la regla 2 de AGENTS.md
-- obliga a escribir el literal "NR" cuando el dato no vino, y un INTEGER NULL
-- reintroduciría la ambigüedad entre «no se sabe» y «cero» que "NR" existe para
-- eliminar. El precio es ordenar por año con un CAST, y se paga con gusto.
CREATE TABLE IF NOT EXISTS referencia (
    id            TEXT PRIMARY KEY,              -- B00001, propio de la biblioteca
    doi           TEXT UNIQUE,                   -- normalizado; NULL si no hay
    clave_titulo  TEXT NOT NULL,                 -- dedup cuando no hay DOI
    titulo        TEXT NOT NULL DEFAULT 'NR',
    anio          TEXT NOT NULL DEFAULT 'NR',
    idioma        TEXT NOT NULL DEFAULT 'NR',
    revista       TEXT NOT NULL DEFAULT 'NR',
    volumen       TEXT NOT NULL DEFAULT 'NR',
    numero        TEXT NOT NULL DEFAULT 'NR',
    paginas       TEXT NOT NULL DEFAULT 'NR',
    tipo          TEXT NOT NULL DEFAULT 'NR',
    citas         TEXT NOT NULL DEFAULT 'NR',
    resumen       TEXT NOT NULL DEFAULT 'NR',
    oa_url        TEXT NOT NULL DEFAULT 'NR',
    oa_estado     TEXT NOT NULL DEFAULT 'NR',
    alta          TEXT NOT NULL,                 -- ISO 8601, primera vez que entró
    visto         TEXT NOT NULL                  -- última vez que una cosecha lo trajo
);

CREATE INDEX IF NOT EXISTS idx_ref_clave ON referencia(clave_titulo);
CREATE INDEX IF NOT EXISTS idx_ref_anio  ON referencia(anio);

-- El orden de los autores importa para citar, así que va explícito y no
-- confiado al orden de inserción.
CREATE TABLE IF NOT EXISTS autor (
    referencia_id TEXT    NOT NULL REFERENCES referencia(id) ON DELETE CASCADE,
    orden         INTEGER NOT NULL,
    nombre        TEXT    NOT NULL,
    PRIMARY KEY (referencia_id, orden)
);

CREATE INDEX IF NOT EXISTS idx_autor_nombre ON autor(nombre);

-- ──────────────────────── Procedencia y trazabilidad ────────────────────────

CREATE TABLE IF NOT EXISTS revision (
    nombre        TEXT PRIMARY KEY,
    protocolo     TEXT NOT NULL DEFAULT 'NR',    -- ruta del .json
    protocolo_sha TEXT NOT NULL DEFAULT 'NR',    -- si cambia el protocolo, se nota
    carpeta       TEXT NOT NULL DEFAULT 'NR',
    sintetica     INTEGER NOT NULL DEFAULT 0 CHECK (sintetica IN (0, 1)),
    importada     TEXT NOT NULL
);

-- El puente entre el R0001 de una revisión y el B00001 de la biblioteca.
CREATE TABLE IF NOT EXISTS equivalencia (
    revision      TEXT NOT NULL REFERENCES revision(nombre)  ON DELETE CASCADE,
    id_local      TEXT NOT NULL,                 -- R0001 dentro de esa revisión
    referencia_id TEXT NOT NULL REFERENCES referencia(id)    ON DELETE CASCADE,
    PRIMARY KEY (revision, id_local)
);

CREATE INDEX IF NOT EXISTS idx_equiv_ref ON equivalencia(referencia_id);

-- Espejo consultable de `search_log.csv` (AGENTS.md, regla 3). El CSV sigue
-- siendo la evidencia; esto solo permite preguntarle cosas.
CREATE TABLE IF NOT EXISTS ecuacion (
    id         INTEGER PRIMARY KEY,
    revision   TEXT    NOT NULL REFERENCES revision(nombre) ON DELETE CASCADE,
    numero     INTEGER NOT NULL,
    fuente     TEXT    NOT NULL DEFAULT 'NR',
    literal    TEXT    NOT NULL,                 -- la ecuación TAL CUAL se envió
    url        TEXT    NOT NULL DEFAULT 'NR',
    eje        TEXT    NOT NULL DEFAULT 'NR',    -- qué dimensión barría, si barría
    valor_eje  TEXT    NOT NULL DEFAULT 'NR',
    resultados INTEGER NOT NULL DEFAULT 0,
    fecha      TEXT    NOT NULL DEFAULT 'NR',
    UNIQUE (revision, numero, fuente)
);

CREATE INDEX IF NOT EXISTS idx_ec_hueco ON ecuacion(revision, resultados);

-- ────────────────────────────── El cribado ──────────────────────────────

-- Espejo de `decisiones.json` y de la columna de decisión de `cribado.csv`
-- (AGENTS.md, regla 4). `origen` distingue quién decidió: sin eso no se puede
-- saber cuánto pesa una inclusión.
CREATE TABLE IF NOT EXISTS decision (
    revision      TEXT NOT NULL REFERENCES revision(nombre) ON DELETE CASCADE,
    referencia_id TEXT NOT NULL REFERENCES referencia(id)   ON DELETE CASCADE,
    estado        TEXT NOT NULL CHECK (estado IN ('incluido', 'excluido', 'dudoso')),
    motivo        TEXT NOT NULL DEFAULT 'NR',
    origen        TEXT NOT NULL CHECK (origen IN ('regla', 'modelo', 'humano')),
    regla         TEXT NOT NULL DEFAULT 'NR',
    fecha         TEXT NOT NULL DEFAULT 'NR',
    PRIMARY KEY (revision, referencia_id)
);

CREATE INDEX IF NOT EXISTS idx_dec_estado ON decision(revision, estado);

-- ─────────────────── Clasificación cruzada: ejes ad hoc ───────────────────

CREATE TABLE IF NOT EXISTS dimension (
    revision    TEXT NOT NULL REFERENCES revision(nombre) ON DELETE CASCADE,
    nombre      TEXT NOT NULL,
    tipo        TEXT NOT NULL CHECK (tipo IN ('determinista', 'derivado', 'modelo')),
    descripcion TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (revision, nombre)
);

-- Una fila por (referencia, eje, valor). Un artículo puede estar en varias
-- regiones, así que el valor forma parte de la clave en vez de sobrescribir.
CREATE TABLE IF NOT EXISTS etiqueta (
    revision      TEXT NOT NULL,
    referencia_id TEXT NOT NULL REFERENCES referencia(id) ON DELETE CASCADE,
    dimension     TEXT NOT NULL,
    valor         TEXT NOT NULL,                 -- "NR" si no se pudo determinar
    origen        TEXT NOT NULL CHECK (origen IN ('termino', 'tabla', 'modelo', 'humano')),
    verificado    INTEGER NOT NULL DEFAULT 0 CHECK (verificado IN (0, 1)),
    fecha         TEXT NOT NULL DEFAULT 'NR',
    PRIMARY KEY (revision, referencia_id, dimension, valor),
    FOREIGN KEY (revision, dimension)
        REFERENCES dimension(revision, nombre) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_etiq_cruce ON etiqueta(revision, dimension, valor);

-- La nota de relevancia de una o dos líneas que escribe el modelo local.
CREATE TABLE IF NOT EXISTS anotacion (
    revision      TEXT NOT NULL REFERENCES revision(nombre) ON DELETE CASCADE,
    referencia_id TEXT NOT NULL REFERENCES referencia(id)   ON DELETE CASCADE,
    texto         TEXT NOT NULL,
    modelo        TEXT NOT NULL DEFAULT 'NR',
    fecha         TEXT NOT NULL DEFAULT 'NR',
    PRIMARY KEY (revision, referencia_id)
);

-- ─────────────────────── Honestidad: lo que salió vacío ───────────────────────

-- Una búsqueda que se lanzó y no devolvió nada es un hallazgo, no una omisión.
-- Se guarda para que el informe lo pueda decir con nombre y apellido.
CREATE TABLE IF NOT EXISTS hueco (
    revision   TEXT    NOT NULL REFERENCES revision(nombre) ON DELETE CASCADE,
    dimension  TEXT    NOT NULL,                 -- "ecuacion" mientras no haya ejes
    valor      TEXT    NOT NULL,
    ecuaciones INTEGER NOT NULL DEFAULT 0,
    resultados INTEGER NOT NULL DEFAULT 0,
    fecha      TEXT    NOT NULL DEFAULT 'NR',
    PRIMARY KEY (revision, dimension, valor)
);
