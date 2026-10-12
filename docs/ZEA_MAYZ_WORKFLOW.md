# ZEA MAYZ: de los documentos al libro

ZEA MAYZ es la capa de divulgación científica sobre Knowledge Studio. Su regla:
**la narrativa puede simplificar, comparar e inventar personajes, pero no puede
añadir un solo hecho científico que no esté en un concepto aprobado por una
persona.**

Vive en `src/tatewari/zea_mayz/`, separada del núcleo: Knowledge Studio no
depende de ella, y se podría quitar sin tocar nada más.

---

## El flujo completo

```
 documentos ──▶ conocimiento ──▶ aprobación ──▶ narrativa ──▶ storyboard ──▶ publicación
 (01_MATERIA)   (02_CONCEPTOS)   (una persona)   (05_GUION)   (06_STORYBOARD)  (09_LIBRO)
      │               │                │              │               │              │
  procesar       DRAFT/REVIEW      APPROVED       divulgar        viñetas y     maquetación
                                                  + validar     ilustraciones    (futuro)
                                                                (08_ILUSTRACIONES)
```

| Etapa | Quién | Orden | Sale |
|---|---|---|---|
| 1. Documentos | persona | copiar a `01_MATERIA` | originales |
| 2. Conocimiento | modelo + reglas | `conocimiento procesar` / `materia` | notas en `DRAFT`/`REVIEW` |
| 3. Aprobación | **persona** | `conocimiento estado … APPROVED --autor` | base aprobada |
| 4. Narrativa | modelo de síntesis | `zea-mayz divulgar` | guion en `05_GUION` |
| 5. Validación | reglas | automática y `zea-mayz validar` | sección «Validación científica» |
| 6. Storyboard | modelo + persona | (sale con el guion) | `06_STORYBOARD`, `08_ILUSTRACIONES` |
| 7. Publicación | persona | — | `09_LIBRO` (maquetación, futuro) |

### 1–2. Documentos y conocimiento

Ver [KNOWLEDGE_STUDIO.md](KNOWLEDGE_STUDIO.md). Lo que interesa aquí: cada
concepto sabe qué afirmaciones están **comprobadas contra su fuente** (cita
literal encontrada en el documento) y cuáles son interpretación del modelo.

### 3. Aprobación: el paso que no se automatiza

Nada entra en la narrativa sin pasar por una persona. Aprobar es leer la nota
contra el documento, corregir lo que haga falta y decirlo con nombre:

```bash
python -m tatewari conocimiento conceptos --estado DRAFT
```

```bash
python -m tatewari conocimiento estado "Horizonte A" APPROVED --autor "Tu nombre"
```

El modelo no puede aprobar: un autor vacío o `modelo:…` se rechaza.

### 4. Narrativa

```bash
python -m tatewari zea-mayz divulgar --tema "el suelo" --publico "lectores de 10 a 14 años" --capitulos 1
```

O con conceptos concretos:

```bash
python -m tatewari zea-mayz divulgar --concepto "El suelo" --concepto Horizonte
```

Qué recibe el modelo de síntesis (`divulgacion.construir_prompt`):

- **solo** conceptos `APPROVED` o `PUBLISHED` (hasta 10);
- de cada uno, **solo** las afirmaciones comprobadas contra la fuente: el
  resumen y las inferencias del modelo no entran;
- la instrucción de no añadir hechos, cifras, fechas ni nombres, y de declarar
  cada afirmación científica con los conceptos que la respaldan.

La respuesta se valida contra un esquema JSON (capítulos → escenas →
narración, personajes, diálogos, afirmaciones, recuadro, viñetas, ilustración).
Si no sirve, un reintento; si tampoco, no se escribe nada.

Salen tres archivos, todos en `DRAFT` y enlazados entre sí:

| Carpeta | Archivo | Contenido |
|---|---|---|
| `05_GUION` | `Guion - …` | capítulos, escenas, diálogos, afirmaciones con su base, recuadros científicos |
| `06_STORYBOARD` | `Storyboard - …` | tabla de viñetas por escena |
| `08_ILUSTRACIONES` | `Ilustraciones - …` | qué debe mostrar cada imagen y en qué concepto se apoya |

En el guion, cada afirmación científica se escribe así:

```markdown
- **Afirmación:** El horizonte A mide de 10 a 30 cm. · **Base:** [[Horizonte A]]
```

y cada recuadro científico, así:

```markdown
> [!note] Recuadro científico: ¿Qué es el suelo?
> Minerales, materia orgánica, agua y aire.
> **Base:** [[El suelo]]
```

### 5. Validación científica

`validacion.validar_borrador` lee el Markdown del guion y comprueba:

| Qué | Regla |
|---|---|
| Cada afirmación | su **Base** enlaza al menos un concepto, y todos están `APPROVED`/`PUBLISHED` |
| Cada recuadro científico | tiene línea de **Base** y está aprobada |
| Cada cifra del texto | aparece en las afirmaciones o citas de algún concepto aprobado |

El resultado se añade al final del guion. Si algo falla, un aviso
`[!danger]` dice que el borrador no se publica hasta corregirlo.

Como el guion se edita a mano, la validación se repite cuando se quiera:

```bash
python -m tatewari zea-mayz validar "05_GUION/Guion - El secreto del suelo (2026-09-17 2246).md"
```

Para arreglar una afirmación sin base hay dos caminos: quitarla, o aprobar el
concepto que la respalda (después de revisarlo contra su fuente).

**Límite importante:** la validación comprueba las afirmaciones **declaradas**,
los recuadros y las cifras. Una afirmación científica metida en un diálogo o en
la narración sin cifras no se detecta. En la prueba real con `qwen3:4b`, un
personaje dijo que el horizonte A «ayuda a las plantas a crecer más rápido», y
eso no está en la base. La lectura humana del guion sigue siendo necesaria.

### 6. Storyboard e ilustraciones

El storyboard y las especificaciones de ilustración son **encargos**, no
imágenes: qué se ve, qué texto va en la viñeta, qué elementos deben aparecer y
en qué concepto aprobado se apoya lo científico de cada imagen.

Las interfaces para generar imágenes y para maquetar están definidas en
`zea_mayz/interfaces.py` (`GeneradorIlustraciones`, `Maquetador`) pero **no
implementadas**: sus versiones actuales (`SinGenerador`, `SinMaquetador`)
lanzan `NoDisponible` con una explicación. Así, quien las implemente sabe qué
recibe y qué devuelve, y nada finge que existe.

### 7. Publicación

`09_LIBRO` queda reservado para la maquetación. Un concepto usado en un libro
publicado puede pasar a `PUBLISHED`:

```bash
python -m tatewari conocimiento estado "El suelo" PUBLISHED --autor "Tu nombre"
```

---

## Prueba real

Con el curso ficticio de edafología del repositorio, tres conceptos aprobados
(«El suelo», «Horizonte», «Meteorización») y `qwen3:4b` en una RTX 3050 de 4 GB:

```
Modelo de síntesis : modelo:qwen3:4b
Base aprobada      : 3 conceptos (Horizonte, El suelo, Meteorización)

VALIDACIÓN CIENTÍFICA
Afirmaciones científicas : 3 (3 con base aprobada)
Sin respaldo             : 0
Recuadros científicos    : 2 (0 sin base aprobada)
Cifras sin respaldo      : 0
Resultado                : válido
```

Unos 90 segundos. El guion «El secreto del suelo mágico» tiene tres personajes,
cita literalmente las definiciones aprobadas y enlaza cada afirmación a su
concepto; también trae la frase de diálogo sin respaldo descrita arriba.

## Habilidades

| Habilidad | Qué hace |
|---|---|
| `divulgacion_cientifica` | borrador narrativo desde conceptos aprobados, ya validado |
| `divulgacion_validar` | valida un borrador existente |

Se registran al importar `tatewari.zea_mayz` y aparecen en:

```bash
python -m tatewari conocimiento habilidades
```
