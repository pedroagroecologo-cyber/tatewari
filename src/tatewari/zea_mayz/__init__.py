"""ZEA MAYZ: divulgación científica a partir de conocimiento aprobado.

Una capa **encima** de Knowledge Studio y desacoplada de él. El núcleo no sabe
que esta capa existe; ella solo lee del Vault las notas en ``APPROVED`` o
``PUBLISHED`` y escribe borradores narrativos en sus propias carpetas.

La regla que la define: **la narrativa puede simplificar y explicar, pero no
alterar los hechos científicos**. Por eso:

- solo recibe conocimiento aprobado por una persona;
- cada afirmación científica del borrador tiene que llevar al menos un concepto
  aprobado que la respalde, y eso se comprueba (`validacion`);
- las cifras del borrador tienen que aparecer en la base aprobada;
- lo que produce es siempre un **borrador** (``DRAFT``), separado del
  conocimiento fuente, marcado como tal, y nunca entra en ``02_CONCEPTOS``.

Todavía no genera imágenes ni maqueta el libro. `interfaces` define los
contratos para añadirlo después sin tocar lo demás.
"""

from . import divulgacion, interfaces, validacion  # noqa: F401 - registran habilidades

__all__ = ["divulgacion", "interfaces", "validacion"]
