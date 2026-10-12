"""Knowledge Studio: de documentos académicos a una base de conocimiento en Obsidian.

El recorrido, y qué pieza hace cada paso:

    documento
      → ingesta          (`ingesta`)        detecta el tipo, metadatos, copia al Vault
      → extracción       (`extraccion`)     texto por página, diapositiva o sección
      → normalización    (`normalizacion`)  limpia y trocea sin perder la ubicación
      → análisis Qwen    (`analisis`)       el modelo local propone objetos
      → objetos          (`objetos`)        se validan contra el esquema y las citas
      → vínculos         (`vinculos`)       duplicados, notas existentes, conflictos
      → Markdown         (`markdown`)       notas con plantilla y enlaces [[...]]
      → Vault            (`vault`)          escritura dentro de la jaula de rutas
      → validación       (`validacion`)     enlaces, estados, fuentes
      → reporte          (`reporte`)        qué pasó, legible

La extracción es **determinista** y la interpretación es del **modelo**, y las dos
cosas no se mezclan: cada afirmación de una nota dice si sale del documento (con
su cita literal y su página) o si es una inferencia del modelo.

El orquestador (`orquestador`) encadena los pasos usando las habilidades
registradas en `habilidades`. El modelo nunca decide rutas de archivo: los
nombres se derivan de forma determinista y toda escritura pasa por `rutas`.
"""
