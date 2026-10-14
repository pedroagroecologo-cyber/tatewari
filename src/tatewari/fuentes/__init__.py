"""Fuentes bibliográficas legales y abiertas.

Solo se consultan las fuentes que permite AGENTS.md (regla 5): **OpenAlex,
Crossref, Unpaywall, arXiv y PMC**. Nada de Sci-Hub, nada de raspar Google
Scholar o ResearchGate, nada de eludir un muro de pago.

Todas las fuentes devuelven registros con la **misma forma**, la de
`fixtures/demo.json`:

    doi, titulo, anio, idioma, revista, autores, resumen, tipo, citas, oa_url

Lo que la fuente no dé se escribe `"NR"`, nunca un valor plausible
(AGENTS.md, regla 2). `autores` es una lista; cuando no hay ninguno conocido,
es `["NR"]`.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "NR",
    "CAMPOS_REGISTRO",
    "limpiar_termino",
    "texto_o_nr",
    "entero_o_nr",
    "lista_o_nr",
    "registro_en_blanco",
]

NR = "NR"

CAMPOS_REGISTRO = (
    "doi",
    "titulo",
    "anio",
    "idioma",
    "revista",
    "autores",
    "resumen",
    "tipo",
    "citas",
    "oa_url",
    # Datos bibliográficos para armar la cita en APA, Vancouver y demás.
    "volumen",
    "numero",
    "paginas",
)

_ESPACIOS = re.compile(r"\s+")


def limpiar_termino(termino: str) -> str:
    """Deja un término listo para meterlo en el valor de un filtro.

    Quita tres caracteres que romperían la consulta:

    - la **coma**, porque dentro de `filter=` separa un filtro del siguiente,
      así que un término con coma parte la consulta en dos filtros inválidos;
    - la **barra vertical**, porque dentro del valor de un filtro es el `OR`;
    - la **comilla doble**, porque el término se envuelve en comillas para
      buscarlo como frase y una comilla interna cerraría la frase antes de
      tiempo.

    Además colapsa los espacios repetidos. No traduce, no corrige ortografía y
    no añade nada: solo quita lo que rompería la sintaxis.
    """
    limpio = termino.replace(",", " ").replace("|", " ").replace('"', " ")
    return _ESPACIOS.sub(" ", limpio).strip()


def texto_o_nr(valor: Any) -> str:
    """Devuelve el texto limpio, o `"NR"` si no hay nada aprovechable."""
    if valor is None:
        return NR
    texto = str(valor).strip()
    return texto if texto else NR


def entero_o_nr(valor: Any) -> int | str:
    """Devuelve el entero, o `"NR"` si falta o no es un número."""
    if isinstance(valor, bool) or valor is None:
        return NR
    if isinstance(valor, int):
        return valor
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return NR


def lista_o_nr(valores: Any) -> list[str]:
    """Devuelve la lista de textos, o `["NR"]` si viene vacía."""
    if not valores:
        return [NR]
    limpios = [texto_o_nr(v) for v in valores]
    limpios = [v for v in limpios if v != NR]
    return limpios or [NR]


def registro_en_blanco() -> dict[str, Any]:
    """Registro con todos los campos en `"NR"`, para rellenar lo que se sepa."""
    registro: dict[str, Any] = {campo: NR for campo in CAMPOS_REGISTRO}
    registro["autores"] = [NR]
    return registro
