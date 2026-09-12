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

**Andamiaje y contrato de datos.** Lo que ya funciona:

- Carga de configuración desde `.env` con valores por defecto.
- Carga y validación del protocolo de búsqueda en JSON, con errores en español
  que señalan el campo exacto.
- Un protocolo real de ejemplo y un fixture de registros sintéticos.
- Una CLI con `version` y `protocolo validar`.

Lo que **todavía no existe**, y llega en encargos posteriores: cosecha en las
APIs, deduplicación, cribado, llamadas a Ollama, embeddings y exportación.
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
cada bloque y cuántas ecuaciones de búsqueda se lanzarán. Códigos de salida:
`0` correcto, `1` protocolo inválido, `2` archivo no encontrado.

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
  modelo.py               Cliente de Ollama (vacío, pendiente)
  cli.py                  Línea de órdenes
  __main__.py             python -m tatewari
protocolos/humedales.json Protocolo real de ejemplo
fixtures/demo.json        14 registros sintéticos para las pruebas
tests/                    pytest, sin red
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

47 pruebas, todas **sin red** (AGENTS.md, regla 6). Ninguna toca una API real:
todo sale de `protocolos/` y de `fixtures/`.

---

## Pendiente de verificar

Este encargo no ha llamado a ninguna API académica, así que lo siguiente está
escrito **según la documentación oficial de cada servicio y no comprobado
contra la API en vivo**. Hay que confirmarlo cuando se construya la cosecha:

1. **Unpaywall exige el correo.** Parámetro `email` obligatorio; las peticiones
   sin él se rechazan. Falta confirmar el código de error exacto y si admite
   `User-Agent` como alternativa.
2. **OpenAlex y Crossref: cola educada.** Identificarse con un correo
   (`mailto` en la petición o en el `User-Agent`) da mejor servicio. Faltan por
   confirmar los límites de tasa concretos de cada cola.
3. **La forma del registro cosechado.** Los diez campos de `fixtures/demo.json`
   (`doi`, `titulo`, `anio`, `idioma`, `revista`, `autores`, `resumen`, `tipo`,
   `citas`, `oa_url`) son un contrato **de diseño**. Hay que contrastarlo con
   respuestas reales de OpenAlex y Crossref, sobre todo:
   - OpenAlex devuelve el resumen como índice invertido, no como texto
     corrido: habrá que reconstruirlo.
   - El idioma no siempre viene, y cuando viene no siempre es fiable.
   - `tipo` usa vocabularios distintos en cada fuente y habrá que mapearlos.

Cuando algo de esto se compruebe contra la API real, se corrige aquí y se borra
de esta lista. Mientras tanto, nada de estos puntos debe darse por seguro.
