"""La interfaz gráfica de Tatewari: una biblioteca de tres paneles en el navegador.

Se inspira en la disposición de Zotero (colecciones a la izquierda, elementos en
el centro, ficha a la derecha), pero no usa su código: Zotero es AGPL y
Tatewari es MIT, y además está escrito para correr dentro de Firefox.

Todo corre en esta máquina:

- `servicio.py` sabe qué hay en las revisiones y en el Vault y hace los cambios,
  sin saber nada de HTTP. Es lo que se prueba.
- `servidor.py` lo sirve en ``127.0.0.1`` con una clave por sesión, y ejecuta
  los trabajos largos (procesar un documento, divulgar) de uno en uno.
- `estatico/` es la página: HTML, CSS y JavaScript sin dependencias ni CDN, para
  que funcione sin internet.
"""
