"""Validación del Vault: lo que hay que mirar antes de fiarse de la base.

No arregla nada. Dice qué está mal (errores) y qué conviene revisar (avisos):

Errores
    - Una nota de Tatewari con un estado que no existe.
    - Una nota de conocimiento sin ninguna fuente.
Avisos
    - Una nota APPROVED o PUBLISHED sin ninguna definición comprobada contra su
      fuente: alguien aprobó algo que no tiene respaldo literal.
    - Dos notas que se llaman igual o comparten alias: probable duplicado.
    - Enlaces ``[[...]]`` a notas que no existen. Obsidian los muestra como
      pendientes, y no son un error, pero conviene saber cuántos hay.
    - Notas con conflictos entre fuentes sin resolver.
    - Notas de Tatewari editadas a mano: ya no se actualizarán solas.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .objetos import ESTADOS, ESTADOS_PROTEGIDOS
from .vault import Nota, Vault

__all__ = ["ResultadoValidacion", "validar_vault"]


@dataclass
class ResultadoValidacion:
    notas: int = 0
    gestionadas: int = 0
    por_estado: Counter = field(default_factory=Counter)
    por_tipo: Counter = field(default_factory=Counter)
    errores: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    pendientes: dict[str, list[str]] = field(default_factory=dict)
    duplicados: list[tuple[str, str]] = field(default_factory=list)
    con_conflictos: list[str] = field(default_factory=list)
    editadas: list[str] = field(default_factory=list)

    @property
    def valida(self) -> bool:
        return not self.errores

    def resumen(self) -> str:
        estados = ", ".join(f"{self.por_estado[e]} {e}" for e in ESTADOS if self.por_estado[e])
        lineas = [
            f"Notas en el Vault       : {self.notas} ({self.gestionadas} de Tatewari)",
            f"Por estado              : {estados or 'ninguna'}",
            f"Errores                 : {len(self.errores)}",
            f"Avisos                  : {len(self.avisos)}",
            f"Enlaces pendientes      : {len(self.pendientes)}",
            f"Posibles duplicados     : {len(self.duplicados)}",
            f"Notas con conflictos    : {len(self.con_conflictos)}",
            f"Editadas a mano         : {len(self.editadas)}",
        ]
        return "\n".join(lineas)


def _es_conocimiento(nota: Nota) -> bool:
    return nota.gestionada and nota.tipo not in ("fuente", "propuesta", "indice")


def validar_vault(vault: Vault) -> ResultadoValidacion:
    """obsidian_validate: revisa todas las notas del Vault sin tocar ninguna."""
    resultado = ResultadoValidacion()
    notas = vault.notas(recargar=True)
    resultado.notas = len(notas)

    por_clave: dict[str, str] = {}
    for nota in notas:
        if nota.gestionada:
            resultado.gestionadas += 1
            resultado.por_tipo[nota.tipo] += 1
            if nota.estado not in ESTADOS:
                resultado.errores.append(f"[[{nota.nombre}]]: estado desconocido «{nota.estado}».")
            else:
                resultado.por_estado[nota.estado] += 1

        if _es_conocimiento(nota):
            fuentes = nota.frontmatter.get("fuentes") or []
            if not fuentes:
                resultado.errores.append(f"[[{nota.nombre}]]: no tiene ninguna fuente.")
            objeto = nota.objeto()
            if nota.estado in ESTADOS_PROTEGIDOS and objeto and not objeto.verificado:
                resultado.avisos.append(
                    f"[[{nota.nombre}]] está en {nota.estado} pero ninguna definición se "
                    f"comprobó contra el texto de su fuente."
                )
            if nota.conflictos:
                resultado.con_conflictos.append(nota.nombre)
            if not nota.intacta:
                resultado.editadas.append(nota.nombre)

        if nota.tipo in ("propuesta", "indice", "fuente"):
            continue
        for clave in nota.claves:
            otra = por_clave.get(clave)
            if otra and otra != nota.nombre:
                par = tuple(sorted((otra, nota.nombre)))
                if par not in resultado.duplicados:
                    resultado.duplicados.append(par)
            else:
                por_clave[clave] = nota.nombre

    resultado.pendientes = vault.enlaces_pendientes()
    for a, b in resultado.duplicados:
        resultado.avisos.append(f"[[{a}]] y [[{b}]] comparten nombre o alias: ¿son la misma nota?")
    for nombre in resultado.con_conflictos:
        resultado.avisos.append(f"[[{nombre}]] tiene conflictos entre fuentes sin resolver.")
    if resultado.pendientes:
        resultado.avisos.append(
            f"{len(resultado.pendientes)} enlaces apuntan a notas que todavía no existen."
        )
    return resultado
