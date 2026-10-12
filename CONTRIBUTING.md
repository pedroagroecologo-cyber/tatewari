# Cómo contribuir a Tatewari · Reto Tatewari 2026

Tatewari es software libre (licencia MIT, ver `LICENSE`). Cualquier persona puede proponer mejoras.
Este documento explica cómo, y las reglas del **Reto Tatewari 2026**.

## Reglas para toda contribución

1. Respeta las reglas de [AGENTS.md](AGENTS.md): ejecución local, **nada de datos inventados**, ecuaciones
   de búsqueda literales, el cribado automático nunca descarta solo, solo fuentes legales y abiertas,
   pruebas sin red, todo el texto en español.
2. Si tocas código, **todas las pruebas deben pasar** (`python -m pytest -q`) y lo nuevo trae sus pruebas,
   sin red.
3. **Declara cómo usaste la IA**: qué hizo el modelo, qué hiciste tú y qué verificaste.
4. Toda contribución se publica bajo la licencia MIT del proyecto.
5. Nunca subas claves, contraseñas, tu `.env` ni libros o artículos con derechos de autor.

Se entrega por *pull request* en GitHub. Si nunca has usado GitHub, puedes entregar una carpeta
comprimida; nadie queda fuera por eso.

---

# Reto Tatewari 2026

**Premio:** un año de suscripción a Claude Pro.
**Plazo:** del 16 de octubre al **31 de diciembre de 2026**. El fallo se da en enero de 2027.
**Pueden participar:** estudiantes de la maestría.
**Jurado:** profesoras y profesores de la maestría: [nombres por confirmar].
**Organiza y patrocina:** Inge, quien mantiene Tatewari y por eso **no participa** en el reto ni forma
parte del jurado. Integrar una contribución al repositorio y elegir al ganador son decisiones separadas.
**Entrega de referencia:** el organizador puede presentar una entrega **fuera de concurso**. Se evalúa y
se comenta como las demás y sirve de ejemplo, pero no compite por el premio.

Cada participante elige **uno** de los cuatro retos. Tres de los cuatro no requieren saber programar.

## Reto A · Revisión sistemática completa (vía investigación)

Una revisión PRISMA real sobre el tema de tu tesis, hecha de punta a punta con Tatewari.

**Criterios de aceptación (todos):**
- Cosecha completa: todas las ecuaciones del protocolo ejecutadas.
- Al menos **300 registros cribados**, con **todos los dudosos decididos a mano** y su motivo.
- Extracción de datos de al menos **20 artículos incluidos** y una síntesis de 1 a 2 cuartillas.
- **Prueba de sensibilidad:** antes de buscar, registras en el repositorio 10 artículos clave que ya
  conocías (con DOI). Reportas cuántos encontró Tatewari; si faltó alguno, explicas por qué y cómo
  corregiste el protocolo.
- El jurado clona tu entrega y **reproduce el mismo diagrama PRISMA en menos de una hora**.

## Reto B · ¿Qué tan bien criba la IA? (vía experimental)

Un estudio de métodos con datos reales.

**Criterios de aceptación (todos):**
- Un **estándar de oro** de al menos **150 registros** etiquetados (incluir / excluir) por dos personas
  de forma independiente, con su acuerdo medido (kappa de Cohen).
- **Sensibilidad y especificidad** del cribado por reglas y del cribado con modelo local
  (`--modelo-local`), con al menos **dos modelos** distintos.
- Datos y script en el repositorio; resultados reproducibles.
- Una conclusión honesta, aunque sea «no funciona», con calidad suficiente para una nota metodológica.

## Reto C · Una capacidad nueva de punta a punta (vía ingeniería, con IA)

Una de estas funciones, completa:
- `tatewari proponer`: de una ficha de contexto a un protocolo válido, con modelo local;
- una fuente nueva (PubMed o arXiv) con deduplicación entre fuentes;
- un reporte Markdown con tablas cruzadas y «huecos» (lo que se buscó y no se encontró).

**Criterios de aceptación (todos):**
- Pruebas nuevas sin red, y **todas las pruebas existentes pasan**.
- Funciona en Linux y en Windows.
- Documentación de uso en el README.
- Evaluación en al menos **10 temas de tesis distintos**, con resultados reportados.
- Un documento que **explique la arquitectura** de lo que hiciste: qué piezas tocaste y cómo se conectan.
  Programar con ayuda de IA está permitido y se espera; lo que se evalúa es que entiendas el sistema.

## Reto D · Tatewari fuera del aula (vía apropiación)

Llevar Tatewari a personas que no son de la clase.

**Criterios de aceptación (todos):**
- Al menos **5 personas externas** (otro posgrado, un laboratorio, una dependencia, una organización
  local) lo instalan y completan una búsqueda real con tu guía.
- Registro de cada sesión: tiempo, errores, dónde se atoró cada quien.
- La guía de instalación y uso **mejorada con esa evidencia**, en el repositorio, con un antes y después
  medible.

## Cómo se decide

1. **Umbral:** solo son elegibles las entregas que cumplen **todos** los criterios de aceptación de su reto.
2. **Rúbrica** (sobre las elegibles):

   | Criterio | Puntos |
   |---|---|
   | Rigor y verificación | 35 |
   | Utilidad real para quien hace una tesis | 25 |
   | Reproducibilidad | 20 |
   | Reflexión: arquitectura del sistema y uso de la IA | 20 |

3. **Descalificación inmediata:** cualquier dato, referencia o resultado inventado.
4. **Si ninguna entrega es elegible**, el premio puede declararse desierto o entregarse en menor medida
   a la mejor entrega parcial, a criterio del jurado.
5. **Entrega:** a más tardar el 31 de diciembre de 2026, por *pull request* (o carpeta comprimida), con un
   informe de 3 a 5 cuartillas.

Es un concurso de habilidad evaluado con rúbrica, no un sorteo.
