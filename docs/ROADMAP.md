# Hoja de ruta

Lo hecho está en el [README](../README.md). Aquí, lo que falta, por orden de
utilidad.

## Knowledge Studio

- **OCR** para PDF escaneados e imágenes, local (Tesseract u otro motor sin
  nube). Hoy se detecta la página sin texto y se avisa. Encaja en
  `extraccion.py` como otro extractor que devuelve fragmentos con `p. N`.
- **Deduplicación semántica** con los embeddings locales que Tatewari ya tiene
  (`nomic-embed-text`), en lugar de solo Jaccard entre definiciones.
- **Revisión cómoda de propuestas**: hoy son notas en `00_INBOX/propuestas` que
  se copian a mano. Una orden que muestre la diferencia y la aplique tras
  confirmación.
- **Procesamiento incremental de documentos largos**: guardar el avance por
  trozo para poder cortar y reanudar, como la cosecha.
- **`.doc` y `.ppt` antiguos**, vía conversión local si hay LibreOffice.

## ZEA MAYZ

- **Validación de diálogos y narración**: hoy solo se validan las afirmaciones
  declaradas, los recuadros y las cifras. Una segunda pasada que marque frases
  con aspecto de afirmación científica fuera de esas líneas.
- **Generador de ilustraciones local** que implemente
  `interfaces.GeneradorIlustraciones`.
- **Maquetación** a `09_LIBRO` que implemente `interfaces.Maquetador`.
- **Personajes y territorio persistentes**: fichas en `03_PERSONAJES` y
  `04_TERRITORIO` que la narrativa reutilice entre capítulos.

## Revisión sistemática

- Extracción de datos de los textos completos incluidos, con la misma
  verificación de citas de Knowledge Studio.
- Puente entre ambos: pasar los artículos incluidos de una revisión a
  `01_MATERIA` para construir su base de conocimiento.
