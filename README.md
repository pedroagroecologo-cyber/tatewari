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
> `dudoso`, así que hoy el 88 % acabaría en revisión humana, que es tanto como
> no cribar. Hay que decidir qué hacer antes del encargo de cribado. La cosecha
> ya informa del porcentaje en cada lote para que el dato esté a la vista.

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
| Varios que sí cumplen | el resto |

---

## Pruebas

```bash
python -m pytest
```

162 pruebas, todas **sin red** (AGENTS.md, regla 6). Ninguna toca una API real:
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

### Sigue sin comprobar

1. **La cola educada.** Falta medir si `mailto` sube los 1000 créditos. Se ve
   en la cabecera `x-ratelimit-limit` de la primera cosecha con correo puesto.
2. **El vocabulario de tipos.** La tabla de `fuentes/crossref.py` cubre lo que
   apareció en la captura. Lo que no esté se deja tal cual vino, nunca se
   adivina, pero falta ver qué tipos salen de verdad en este dominio.
3. **El idioma.** No siempre viene y no siempre es fiable. Se copia tal cual, o
   `"NR"`. Falta medir cuánto llega vacío.
4. **Qué hacer con el 88 % sin resumen.** Es la decisión pendiente más
   importante, y hay que tomarla antes del encargo de cribado.

Cuando algo de esto se compruebe, se corrige aquí y se borra de la lista.
