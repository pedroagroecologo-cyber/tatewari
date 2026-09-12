# AGENTS.md — Reglas de Tatewari

Estas reglas rigen **todos** los encargos del proyecto. Ningún encargo posterior
puede relajarlas: si una tarea parece exigir romper una regla, la respuesta
correcta es detenerse y avisar, no improvisar una excepción.

---

## 1. Ejecución 100 % local

El único modelo de lenguaje es **Ollama**, en la máquina del usuario
(`http://localhost:11434` por defecto).

Está **prohibido** que el código llame a un modelo en la nube: nada de OpenAI,
Anthropic, Gemini, Cohere, Mistral alojado ni servicios equivalentes. No se
añaden sus SDK a las dependencias, ni se leen sus claves de entorno, ni se deja
un "por si acaso" comentado.

## 2. No se inventa ningún dato

Si falta un DOI, un autor, un año, un resumen o una cifra, se escribe la cadena
literal **`"NR"`** (no reportado).

Nunca un valor plausible, nunca un promedio, nunca una estimación disfrazada de
dato. Un `"NR"` visible es información; un dato inventado es una falsificación
que sobrevive a la revisión y acaba citada.

## 3. Toda ecuación de búsqueda se guarda literal

Cada consulta lanzada contra cada fuente se registra en la bitácora **tal cual
se envió**, junto con su URL completa, la fecha y el número de resultados.

Sin la cadena literal la búsqueda no es reproducible, y una revisión sistemática
que no se puede reproducir no es sistemática.

## 4. El cribado automático nunca descarta solo

El cribado automático **propone**, no decide:

- Los registros dudosos van siempre a **revisión humana**.
- Las exclusiones automáticas se **auditan por muestreo**, y la auditoría queda
  registrada.
- Toda exclusión lleva un motivo explícito y trazable.

## 5. Solo fuentes legales y abiertas

Permitido: **OpenAlex, Crossref, Unpaywall, arXiv, PMC**.

Prohibido: **Sci-Hub**, raspar **Google Scholar**, raspar **ResearchGate**,
y cualquier técnica para **eludir un muro de pago**. Si un texto completo no
está disponible legalmente, se marca como no disponible y se sigue adelante.

## 6. Las pruebas corren sin red

`pytest` debe pasar en verde con la máquina desconectada.

Ninguna prueba toca una API real: se usan los *fixtures* locales de `fixtures/`.
El código de red se prueba con dobles, nunca contra el servicio en vivo.

## 7. Todo el texto de cara al usuario va en español

Mensajes de la CLI, errores de validación, informes y documentación: en español.
Los identificadores del código pueden ser los que convengan, pero lo que lee la
persona usuaria está en español.

## 8. Windows primero

- Toda llamada a `open()` lleva **`encoding="utf-8"` explícito**. Sin él,
  Windows usa la página de códigos local y rompe los acentos.
- Las rutas se construyen con **`pathlib`**, nunca concatenando cadenas con `/`.
- No se usan comandos de shell propios de Unix (`ls`, `rm`, `grep`, tuberías de
  `sh`) desde el código.
- Los archivos de texto se escriben con saltos de línea LF; `.gitattributes`
  fuerza CRLF solo en `*.bat`, `*.cmd` y `*.ps1`.
