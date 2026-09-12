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

## Estado

**Andamiaje, contrato de datos y cosecha.** Lo que ya funciona:

- Carga de configuración desde `.env` con valores por defecto.
- Carga y validación del protocolo de búsqueda en JSON, con errores en español
  que señalan el campo exacto.
- Cosecha reanudable en OpenAlex y Crossref, con bitácora y modos sin red.
- Resolución de acceso abierto por DOI en Unpaywall.
- Un protocolo real de ejemplo y un fixture de registros sintéticos.
- Una CLI con `version`, `protocolo validar` y `cosechar`.

Lo que **todavía no existe**, y llega en encargos posteriores: deduplicación,
cribado, llamadas a Ollama, embeddings y exportación.
`src/tatewari/modelo.py` está vacío a propósito.

---

## Instalación

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

---

## Uso

```bash
python -m tatewari version
```

```bash
python -m tatewari protocolo validar protocolos/humedales.json
```

La validación imprime el título, la ventana temporal, cuántos términos tiene
cada bloque y cuántas ecuaciones de búsqueda se lanzarán.

Ver las consultas **sin gastar red**, para pegarlas en el navegador y
comprobarlas antes de lanzarlas:

```bash
python -m tatewari cosechar demo --protocolo protocolos/humedales.json --seco
```

Cosechar de verdad, en lotes de 8 ecuaciones:

```bash
python -m tatewari cosechar demo --protocolo protocolos/humedales.json
```

Códigos de salida: `0` correcto, `1` protocolo inválido, `2` archivo no
encontrado, `3` problema de configuración, `4` la cosecha no pudo arrancar.

---

## Configuración

Copia `.env.example` a `.env` y ajústalo. El `.env` no se versiona.

| Variable | Por defecto | Para qué |
|---|---|---|
| `TATEWARI_MAILTO` | *(vacío)* | Correo de contacto para las APIs académicas |
| `TATEWARI_OLLAMA` | `http://localhost:11434` | Ollama local, el único modelo del proyecto |
| `TATEWARI_DATOS` | `./revisiones` | Carpeta de salida (no se versiona) |

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
  fuentes/
    openalex.py           Fuente primaria
    crossref.py           Fuente secundaria
    unpaywall.py          Acceso abierto por DOI
  modelo.py               Cliente de Ollama (vacío, pendiente)
  cli.py                  Línea de órdenes
  __main__.py             python -m tatewari
protocolos/humedales.json Protocolo real de ejemplo
fixtures/demo.json        14 registros sintéticos para las pruebas
tests/                    pytest, sin red
tests/respuestas/         Respuestas de ejemplo de las APIs, para las pruebas
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

### Modos sin red

| Modo | Qué hace |
|---|---|
| `--seco` | No pide nada. Imprime las ecuaciones con su URL literal para pegarlas en el navegador |
| `--fixture RUTA` | Sirve un archivo local como respuesta, en vez de la API |

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

### Cinco errores que ya costaron tiempo

Cada uno tiene su prueba en `tests/test_urls.py`, para que no vuelvan.

| Mal | Bien | Por qué |
|---|---|---|
| `language:languages/en` | `language:es\|en` | La primera es la forma de identificador de entidad y la API devuelve error |
| `type:types/article` | `type:article\|review` | Lo mismo |
| Término con coma dentro | Coma eliminada | Dentro de `filter=` la coma separa un filtro del siguiente: partiría la consulta |
| Espacios como `+` | Espacios como `%20` | Si la cadena de consulta la arma la librería, mete `+` y OpenAlex no lo lee como espacio |
| `and`, `or` | `AND`, `OR`, `NOT` | En minúsculas se buscan como palabras |

Por el cuarto, la URL se construye **a mano** en `fuentes/openalex.py` y nunca
se usa el parámetro `params=` de `requests`.

### El resumen viene del revés

OpenAlex no devuelve el resumen como texto corrido, sino como
`abstract_inverted_index`: un diccionario de palabra → lista de posiciones. Una
palabra puede aparecer en **varias** posiciones, así que hay que colocar cada
aparición en su hueco y unir por posición. Ordenar las palabras por su primera
aparición da un texto distinto y mal: se pierden todas las repeticiones.

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
| Varios que sí cumplen | el resto |

---

## Pruebas

```bash
python -m pytest
```

138 pruebas, todas **sin red** (AGENTS.md, regla 6). Ninguna toca una API real:
salen de `protocolos/`, de `fixtures/` y de `tests/respuestas/`, que guarda
respuestas de ejemplo de OpenAlex, Crossref y Unpaywall con la forma que
documenta cada servicio. El código de red se prueba con un cliente falso; los
reintentos, con un reloj falso, así que la suite tarda menos de un segundo.

La construcción de URLs se prueba **sin simular nada**: se compara la cadena
generada contra la forma documentada, carácter a carácter.

---

## Pendiente de verificar

**Ninguna prueba ha llamado nunca a una API real**, ni debe hacerlo
(AGENTS.md, regla 6). Todo lo que sigue está escrito **según la documentación
oficial de cada servicio y no comprobado contra la API en vivo**. La primera
cosecha de verdad es el momento de confirmarlo, y de corregir aquí lo que salga
distinto.

1. **Unpaywall exige el correo.** Se manda como `?email=...`. Falta confirmar
   el código de error exacto cuando no va, y si admite `User-Agent` como
   alternativa.
2. **OpenAlex y Crossref: cola educada.** El correo va en `mailto`. Faltan por
   confirmar los límites de tasa concretos de cada cola, para ajustar la espera
   entre reintentos de `http.py`.
3. **El filtro de búsqueda de OpenAlex.** Se usa
   `title_and_abstract.search:`. Falta comprobar en vivo si busca la frase
   entrecomillada como frase exacta y si el `AND` dentro del valor se
   interpreta como se espera. **Esto es lo más importante de la lista**: si el
   `AND` no se comportara como un `AND`, las 40 ecuaciones estarían mal y no
   habría forma de notarlo desde aquí. Por eso existe `--seco`: pega una de
   esas URL en el navegador antes de lanzar la cosecha entera.
4. **La forma de las respuestas.** Los archivos de `tests/respuestas/` están
   escritos según la documentación, no capturados de la API. Cuando llegue la
   primera respuesta real conviene compararlas y ajustar lo que difiera.
5. **El vocabulario de tipos.** Crossref dice `journal-article` donde OpenAlex
   dice `article`. La tabla de traducción de `fuentes/crossref.py` es corta y
   explícita, y lo que no está en ella se deja tal cual vino. Falta ver qué
   tipos aparecen de verdad en este dominio.
6. **El idioma.** No siempre viene, y cuando viene no siempre es fiable. De
   momento se copia tal cual, o `"NR"`.

Cuando algo de esto se compruebe contra la API real, se corrige aquí y se borra
de esta lista. Mientras tanto, nada de estos puntos debe darse por seguro.
