"""Diagrama de flujo PRISMA 2020, en texto plano.

PRISMA pide que la revisión publique cuántos registros entraron, cuántos se
fueron por duplicados y cuántos se descartaron **y por qué**. Ese recuento es lo
que permite a otra persona repetir la revisión y comprobar que le salen los
mismos números; sin él, la revisión no es sistemática.

Este módulo no sabe nada de cribado ni de protocolos: recibe los números ya
contados en un `Flujo` y los formatea. Así se puede probar el formato sin montar
un cribado entero, y `cribado` puede importarlo sin que haya importaciones
circulares.

Los motivos de exclusión se listan **de mayor a menor**, que es como se lee un
diagrama PRISMA: lo primero que se quiere ver es por qué se cayó la mayoría. A
igual número, se ordenan alfabéticamente, para que dos ejecuciones con los
mismos datos den exactamente el mismo texto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

__all__ = ["Flujo", "diagrama", "ANCHO"]

#: Ancho total de una línea del diagrama, contando los puntos de relleno.
ANCHO = 68

NR = "NR"


@dataclass
class Flujo:
    """Los números de un diagrama PRISMA.

    `conteos` va de decisión (``incluir``, ``dudoso``, ``excluir``) a cantidad, y
    `motivos` de motivo de exclusión a cantidad. `manuales` es cuántas
    decisiones vinieron de una persona o del modelo local en vez del filtro: no
    cambia el flujo, pero quien lea el diagrama tiene que saber que ahí no
    decidió solo el filtro.
    """

    revision: str
    protocolo: str = NR
    fecha: str = NR
    identificados: int = 0
    duplicados_eliminados: int = 0
    conteos: Mapping[str, int] = field(default_factory=dict)
    motivos: Mapping[str, int] = field(default_factory=dict)
    manuales: int = 0

    @property
    def cribados(self) -> int:
        """Registros únicos que llegaron al cribado."""
        return self.identificados - self.duplicados_eliminados


def _linea(etiqueta: str, valor: int, sangria: int = 2) -> str:
    """Una línea «etiqueta ..... valor», alineada a la derecha en `ANCHO`.

    Si la etiqueta es tan larga que no cabe ni un punto de relleno, se deja un
    espacio y el número: más vale una línea fea que una línea cortada.
    """
    izquierda = " " * sangria + etiqueta
    derecha = str(valor)
    # Los dos que se restan son los espacios que rodean a los puntos.
    relleno = ANCHO - len(izquierda) - len(derecha) - 2
    if relleno <= 0:
        return f"{izquierda} {derecha}"
    return f"{izquierda} {'.' * relleno} {derecha}"


def diagrama(flujo: Flujo) -> str:
    """Devuelve el diagrama PRISMA de `flujo` como texto plano en español."""
    incluir = int(flujo.conteos.get("incluir", 0))
    dudoso = int(flujo.conteos.get("dudoso", 0))
    excluir = int(flujo.conteos.get("excluir", 0))

    lineas = [
        "Diagrama de flujo PRISMA 2020",
        "=" * ANCHO,
        f"Revisión  : {flujo.revision}",
        f"Protocolo : {flujo.protocolo}",
        f"Fecha     : {flujo.fecha}",
        "",
        "IDENTIFICACIÓN",
        _linea("Registros identificados en las búsquedas", flujo.identificados),
        _linea("Duplicados eliminados", flujo.duplicados_eliminados),
        "",
        "CRIBADO",
        _linea("Registros cribados", flujo.cribados),
        _linea("Incluir", incluir, sangria=4),
        _linea("Dudoso (pasan a revisión humana)", dudoso, sangria=4),
        _linea("Excluir", excluir, sangria=4),
    ]

    if flujo.motivos:
        lineas.append("")
        lineas.append("  Motivos de exclusión, de mayor a menor:")
        ordenados = sorted(flujo.motivos.items(), key=lambda par: (-par[1], par[0]))
        for motivo, cuantos in ordenados:
            lineas.append(_linea(motivo, cuantos, sangria=4))

    if flujo.manuales:
        lineas.append("")
        lineas.append(
            _linea("Decisiones que no tomó el filtro (persona o modelo)", flujo.manuales)
        )

    lineas.append("")
    if dudoso == 1:
        lineas.append(
            "El registro dudoso NO está descartado: pasa a revisión humana."
        )
        lineas.append(
            "El cribado automático propone, no decide (AGENTS.md, regla 4)."
        )
    elif dudoso:
        lineas.append(
            f"Los {dudoso} registros dudosos NO están descartados: pasan a revisión"
        )
        lineas.append(
            "humana. El cribado automático propone, no decide (AGENTS.md, regla 4)."
        )
    else:
        lineas.append(
            "No quedan registros dudosos. El cribado automático propone, no decide:"
        )
        lineas.append(
            "las exclusiones automáticas se auditan por muestreo (AGENTS.md, regla 4)."
        )
    if excluir == 1:
        lineas.append("La exclusión lleva su motivo en cribado.csv, en su fila.")
    elif excluir:
        lineas.append(
            f"Las {excluir} exclusiones llevan su motivo en cribado.csv, una por fila."
        )

    return "\n".join(lineas)
