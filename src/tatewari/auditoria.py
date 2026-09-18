"""Auditoría por muestreo de las exclusiones automáticas.

Esto es lo que hace honesto al cribado automático. El filtro determinista se
equivoca poco pero se equivoca, y un modelo de 3B corriendo en una tarjeta de
4 GB se equivoca **lo suficiente** como para que no se le pueda confiar el
descarte final. Si nadie mira nunca lo que se descartó, la revisión está
afirmando algo que no ha comprobado.

De ahí la regla 4 de AGENTS.md: las exclusiones automáticas se auditan por
muestreo, y la auditoría **queda registrada**. Por eso este módulo no solo saca
la muestra: también la escribe en `auditoria.json`, con la semilla, la fecha y el
tamaño de la población. Una auditoría que no se puede repetir no sirve de nada,
y con la semilla apuntada, cualquiera puede reconstruir exactamente la misma
muestra.

Por qué `random.sample` y no ordenar con una clave aleatoria
------------------------------------------------------------

El atajo de ``sorted(poblacion, key=lambda _: random.random())`` parece un
barajado y no lo es del todo:

- Gasta un ``O(n log n)`` y una clave por elemento para algo que se resuelve en
  ``O(k)``.
- Si dos claves salen iguales —pasa, y más en cuanto la población crece—, el
  desempate lo decide el orden original, así que el resultado no es uniforme.
- Y cuando alguien lo escribe con ``key=random.random`` (sin el ``lambda``) o
  reutiliza la clave, el sesgo deja de ser teórico.

`random.sample` hace un muestreo sin reemplazo de verdad —selección parcial al
estilo Fisher-Yates, sin tocar la lista original— y no admite ese error. Es la
que se usa aquí.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence, TypeVar

__all__ = [
    "MUESTRA_POR_DEFECTO",
    "NOMBRE_AUDITORIA",
    "Muestra",
    "ErrorAuditoria",
    "muestra_aleatoria",
    "registrar_auditoria",
    "leer_auditorias",
]


class ErrorAuditoria(Exception):
    """El historial de auditorías no se puede leer, y no se va a sobreescribir."""

#: Cuántas exclusiones se revisan por defecto. Veinte se leen en un rato y ya
#: dan para ver si el filtro está descartando algo que no debía.
MUESTRA_POR_DEFECTO = 20

NOMBRE_AUDITORIA = "auditoria.json"

T = TypeVar("T")


@dataclass
class Muestra:
    """Una muestra aleatoria, con lo necesario para repetirla igual."""

    elementos: list[Any] = field(default_factory=list)
    poblacion: int = 0
    semilla: int = 0
    fecha: str = ""

    @property
    def cuantos(self) -> int:
        return len(self.elementos)

    @property
    def es_completa(self) -> bool:
        """¿La muestra es toda la población? Entonces no hay nada que muestrear."""
        return self.cuantos >= self.poblacion

    def resumen(self) -> str:
        """Texto para la CLI."""
        if self.poblacion == 0:
            return "No hay exclusiones que auditar."
        if self.es_completa:
            return (
                f"Auditoría de las {self.poblacion} exclusiones: son pocas, así "
                f"que se revisan todas.\nSemilla {self.semilla}."
            )
        porcentaje = 100 * self.cuantos / self.poblacion
        return (
            f"Auditoría por muestreo: {self.cuantos} de {self.poblacion} "
            f"exclusiones ({porcentaje:.0f} %).\n"
            f"Semilla {self.semilla}: con ella se reconstruye esta misma muestra."
        )


def muestra_aleatoria(
    poblacion: Iterable[T],
    cuantos: int = MUESTRA_POR_DEFECTO,
    semilla: int | None = None,
    fecha: str | None = None,
) -> Muestra:
    """Saca `cuantos` elementos al azar, sin reemplazo y sin sesgo.

    Si la población es más pequeña que la muestra pedida, se devuelve entera: es
    lo que se quiere, no un error. Y si `cuantos` es 0 o menos, la muestra sale
    vacía, no la población completa.

    `semilla` se guarda siempre, se pase o no: sin ella la auditoría no se puede
    repetir, y una auditoría irrepetible no es una auditoría. Cuando no se pasa,
    se genera una y se apunta.
    """
    elementos = list(poblacion)
    if semilla is None:
        # Una semilla cualquiera, pero **apuntada**. Es la diferencia entre
        # «salieron estos veinte» y «salieron estos veinte y así se comprueba».
        semilla = random.randrange(1, 2**31 - 1)

    azar = random.Random(semilla)
    cuantos = max(0, cuantos)
    tomados = min(cuantos, len(elementos))

    return Muestra(
        elementos=azar.sample(elementos, tomados),
        poblacion=len(elementos),
        semilla=semilla,
        fecha=fecha or datetime.now().isoformat(timespec="seconds"),
    )


def registrar_auditoria(
    ruta: Path | str,
    muestra: Muestra,
    identificadores: Sequence[str],
    revision: str = "NR",
    modo: str = "auditoria",
) -> Path:
    """Añade esta auditoría a `auditoria.json`, sin borrar las anteriores.

    Se guardan la fecha, la semilla, el tamaño de la población y **los
    identificadores** que salieron. Con eso, la revisión puede declarar en su
    informe cuántas exclusiones se auditaron y cuáles, que es justo lo que pide
    la regla 4 de AGENTS.md. Las rondas anteriores no se tocan: el historial de
    lo que ya se revisó es parte del rastro.
    """
    ruta = Path(ruta)
    anteriores = leer_auditorias(ruta)
    anteriores.append(
        {
            "revision": revision,
            "modo": modo,
            "fecha": muestra.fecha,
            "semilla": muestra.semilla,
            "poblacion": muestra.poblacion,
            "muestra": list(identificadores),
        }
    )
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as manejador:
        json.dump(anteriores, manejador, ensure_ascii=False, indent=2)
        manejador.write("\n")
    return ruta


def leer_auditorias(ruta: Path | str) -> list[dict[str, Any]]:
    """Las auditorías ya registradas. Lista vacía si el archivo no existe.

    Si el archivo existe pero está roto, **falla**. Podría devolver una lista
    vacía y seguir, pero entonces la siguiente auditoría escribiría encima y se
    llevaría por delante el historial de todo lo que ya se había revisado. Un
    rastro de auditoría no se borra en silencio: mejor plantarse y que alguien
    mire el archivo.
    """
    ruta = Path(ruta)
    if not ruta.is_file():
        return []
    with open(ruta, encoding="utf-8") as manejador:
        try:
            datos = json.load(manejador)
        except json.JSONDecodeError as error:
            raise ErrorAuditoria(
                f"El historial de auditorías {ruta} no es JSON válido: línea "
                f"{error.lineno}, columna {error.colno}: {error.msg}.\n"
                f"No se toca para no perder lo que ya hubiera registrado. "
                f"Arréglalo o muévelo a otro sitio antes de volver a auditar."
            ) from error
    if not isinstance(datos, list):
        raise ErrorAuditoria(
            f"El historial de auditorías {ruta} debería ser una lista de rondas "
            f"y no lo es. No se toca para no perder lo que hubiera."
        )
    return datos
