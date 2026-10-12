# Arquitectura de Tatewari

Tatewari es una aplicación de línea de órdenes en Python 3.12, sin servidor y
sin base de datos obligatoria. Todo el razonamiento corre en Ollama local
(AGENTS.md, regla 1). Tiene dos subsistemas que comparten infraestructura y no
dependen el uno del otro.

```
                      python -m tatewari …   (cli.py)
                 ┌──────────────┴──────────────────────┐
                 │                                     │
     Revisión sistemática                    Knowledge Studio   (cli_conocimiento.py)
     protocolo → cosecha → cribado           conocimiento/  ──▶  zea_mayz/
     → modelo → auditoría → texto            documentos → Vault    divulgación
     completo → exportación                  de Obsidian           desde lo aprobado
                 │                                     │
                 └──────────────┬──────────────────────┘
                     Infraestructura compartida
     config.py (.env) · modelo.py (Ollama) · http.py · texto.py (normalización)
```

## Infraestructura compartida

| Módulo | Qué da |
|---|---|
| `config.py` | valores por defecto → `.env` → variables de entorno |
| `http.py` | cliente con tiempo de espera, reintentos y errores en español |
| `modelo.py` | `ClienteOllama`, elección del modelo que entra en la VRAM, `think: false` |
| `cribado_modelo.py` | `extraer_json_si`: rescata un JSON de una respuesta con texto alrededor |
| `texto.py` | normalización sin acentos, claves alfanuméricas |

## Revisión sistemática

Ver el [README](../README.md): protocolo, cosecha en OpenAlex y Crossref,
deduplicación, cribado determinista, segunda vuelta con modelo local,
auditoría, Unpaywall, exportación, embeddings y biblioteca. Cada paso escribe
en `revisiones/<nombre>/` y es reanudable.

## Knowledge Studio

Ver [KNOWLEDGE_STUDIO.md](KNOWLEDGE_STUDIO.md). En resumen:

```
conocimiento/
  ingesta.py        tipo real, tamaño, huella
  extraccion.py     PDF (PyMuPDF), DOCX, PPTX, MD, TXT → fragmentos con ubicación
  normalizacion.py  limpieza y troceado que conserva la ubicación
  analisis.py       el único paso con modelo
  objetos.py        esquema, estados, verificación de citas
  vinculos.py       crear / actualizar / proponer, conflictos
  markdown.py       notas y plantillas
  vault.py          el Vault: estructura, lectura, escritura, estados
  rutas.py          la jaula: solo se escribe en el Vault y en datos
  enrutador.py      qué modelo hace cada tarea
  habilidades.py    registro de habilidades (skills)
  orquestador.py    encadena habilidades; intención en español
  validacion.py     validación del Vault
  reporte.py        reporte de procesamiento
zea_mayz/
  divulgacion.py    borrador narrativo desde conceptos APPROVED
  validacion.py     cada afirmación, recuadro y cifra contra la base aprobada
  interfaces.py     generador de ilustraciones y maquetador (sin implementar)
```

### Habilidades y orquestador

Antes de Knowledge Studio no había orquestador ni sistema de skills: cada orden
llamaba a funciones. Se añadió lo mínimo compatible con eso:

- `habilidades.py` es una tabla nombre → función con dos marcas, `usa_modelo` y
  `escribe`. Las registradas: `document_ingest`, `document_extract`,
  `knowledge_extract`, `knowledge_link`, `obsidian_create_note`,
  `obsidian_update_note`, `obsidian_search`, `obsidian_validate`,
  `knowledge_report`, y desde ZEA MAYZ `divulgacion_cientifica` y
  `divulgacion_validar`.
- `Orquestador` las usa por nombre y deja traza de cuáles usó en cada
  procesamiento (sale en el reporte). Las acciones de alto nivel (procesar
  documento, analizar materia, crear base, actualizar, conceptos, conflictos,
  reporte) son métodos suyos.

La revisión sistemática **no** pasa por el orquestador: no hacía falta y
cambiarla habría sido un riesgo sin beneficio.

### Límites de escritura

Knowledge Studio escribe solo a través de `rutas.Jaula`, que autoriza el Vault
y la carpeta de datos, resuelve rutas reales antes de escribir y prohíbe
`.obsidian`, `.git` y `.trash`. El modelo nunca elige una ruta: propone un
título, y `nombre_de_nota` lo convierte en un nombre de archivo seguro.

### Fuente de verdad

El Vault. Cada nota lleva su objeto completo en un comentario de Obsidian y una
huella de su cuerpo; no hay índice aparte que se pueda desincronizar.

## Interfaz gráfica

`interfaz/` sirve una página local (`tatewari interfaz`) con la disposición de
un gestor de referencias: colecciones, elementos y ficha. No añade lógica
propia: `servicio.py` llama al mismo `Cribado` que `decidir` y al mismo
`Orquestador` y `Vault` que `conocimiento`.

- **Servidor**: `http.server` de la biblioteca estándar, solo en `127.0.0.1`,
  sin `SO_REUSEADDR` (en Windows dejaría a dos servidores compartir puerto).
- **Seguridad**: clave aleatoria por arranque, que llega a la página en el
  fragmento de la dirección y viaja en la cabecera `X-Tatewari-Clave`; se
  comprueban `Host` y `Origin`; la página tiene una política de contenido que
  solo admite sus propios archivos, y construye el DOM sin `innerHTML`.
- **Trabajos**: los que escriben en el Vault van a una cola de un solo hilo;
  precargar el modelo va aparte, para que una tarjeta ocupada no bloquee nada.
- **Sin dependencias ni CDN**: HTML, CSS y JavaScript propios, empaquetados
  como `package-data`. Funciona sin internet.

No usa código de Zotero (AGPL, escrito para correr dentro de Firefox): solo su
disposición en tres paneles.

## Pruebas

`pytest`, sin red y sin Ollama: un `SesionOllamaFalsa` responde como Ollama
(incluidas respuestas inválidas y caídas), y los documentos DOCX, PPTX y PDF de
prueba se fabrican en cada prueba. `tests/test_repositorio.py` vigila las reglas
del proyecto: codificación, finales de línea, que no haya SDK de la nube, que
cada orden del README exista.
