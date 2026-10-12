"""Validación científica de un borrador narrativo.

Comprueba, sobre el **Markdown** del borrador (y no sobre lo que devolvió el
modelo), tres cosas:

1. Cada afirmación científica (``- **Afirmación:** … · **Base:** [[…]]``) lleva
   al menos un enlace, y **todos** sus enlaces son notas en ``APPROVED`` o
   ``PUBLISHED``. Una afirmación apoyada en un borrador no está respaldada.
2. Cada recuadro científico lleva su línea de base, con las mismas condiciones.
3. Cada cifra que aparece en la narración, los diálogos o los recuadros aparece
   también en el texto de alguna nota aprobada. Una cifra que no está en la base
   es la forma más típica de alterar un hecho sin que se note.

Se valida el Markdown a propósito: así sirve igual para el borrador recién
generado que para el que una persona ha editado a mano después.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..conocimiento.habilidades import registrar
from ..conocimiento.markdown import enlaces_de, leer_nota
from ..conocimiento.objetos import ESTADOS_PROTEGIDOS
from ..conocimiento.vault import Nota, Vault
from ..texto import normalizar

__all__ = [
    "ValidacionNarrativa",
    "validar_borrador",
    "validar_archivo",
    "notas_aprobadas",
]

_AFIRMACION = re.compile(r"^\s*-\s*\*\*Afirmaci[oó]n:\*\*\s*(.+?)\s*·\s*\*\*Base:\*\*(.*)$")
_RECUADRO = re.compile(r"^>\s*\[!note\]\s*Recuadro cient[ií]fico", re.I)
_BASE_RECUADRO = re.compile(r"^>\s*\*\*Base:\*\*(.*)$")
_CIFRA = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")
_SECCION_VALIDACION = re.compile(r"^##\s+Validación científica", re.M)


@dataclass
class ValidacionNarrativa:
    afirmaciones: int = 0
    respaldadas: int = 0
    sin_respaldo: list[tuple[str, str]] = field(default_factory=list)
    recuadros: int = 0
    recuadros_sin_respaldo: list[tuple[str, str]] = field(default_factory=list)
    cifras_sin_respaldo: list[str] = field(default_factory=list)

    @property
    def valida(self) -> bool:
        return not (self.sin_respaldo or self.recuadros_sin_respaldo or self.cifras_sin_respaldo)

    def resumen(self) -> str:
        lineas = [
            f"Afirmaciones científicas : {self.afirmaciones} "
            f"({self.respaldadas} con base aprobada)",
            f"Sin respaldo             : {len(self.sin_respaldo)}",
            f"Recuadros científicos    : {self.recuadros} "
            f"({len(self.recuadros_sin_respaldo)} sin base aprobada)",
            f"Cifras sin respaldo      : {len(self.cifras_sin_respaldo)}",
            f"Resultado                : {'válido' if self.valida else 'REVISAR: hay afirmaciones sin base aprobada'}",
        ]
        for texto, motivo in self.sin_respaldo:
            lineas.append(f"  ✗ «{texto[:90]}» — {motivo}")
        for titulo, motivo in self.recuadros_sin_respaldo:
            lineas.append(f"  ✗ recuadro «{titulo[:60]}» — {motivo}")
        for cifra in self.cifras_sin_respaldo:
            lineas.append(f"  ✗ cifra «{cifra}» no aparece en ninguna nota aprobada")
        return "\n".join(lineas)

    def markdown(self) -> str:
        """La sección que se añade al final del borrador."""
        lineas = ["## Validación científica", "", "```", self.resumen(), "```"]
        if not self.valida:
            lineas += [
                "",
                "> [!danger] Este borrador tiene contenido sin respaldo en la base aprobada.",
                "> No se publica hasta corregirlo: o se enlaza a un concepto APPROVED, o se quita.",
            ]
        return "\n".join(lineas) + "\n"


def notas_aprobadas(vault: Vault) -> dict[str, Nota]:
    """Nombre de nota (en minúsculas) -> nota, de las APPROVED y PUBLISHED."""
    return {
        n.nombre.casefold(): n
        for n in vault.notas(recargar=True)
        if n.estado in ESTADOS_PROTEGIDOS and n.tipo not in ("fuente", "propuesta", "indice")
    }


def _motivo_base(enlaces: list[str], aprobadas: dict[str, Nota], vault: Vault) -> str:
    """Por qué una base no respalda, o cadena vacía si sí respalda."""
    if not enlaces:
        return "no enlaza ningún concepto"
    for destino in enlaces:
        nombre = Path(destino).name.casefold()
        if nombre in aprobadas:
            continue
        nota = vault.buscar(destino)
        if nota is None:
            return f"[[{destino}]] no existe en el Vault"
        if nota.estado not in ESTADOS_PROTEGIDOS:
            return f"[[{destino}]] está en {nota.estado}, no aprobada"
    return ""


def validar_borrador(texto: str, vault: Vault) -> ValidacionNarrativa:
    """Valida el Markdown de un borrador contra la base aprobada del Vault."""
    resultado = ValidacionNarrativa()
    aprobadas = notas_aprobadas(vault)
    corpus = normalizar(" ".join(_contenido(n) for n in aprobadas.values()))
    cifras_base = set(_CIFRA.findall(corpus))

    _, cuerpo, _ = leer_nota(texto)
    # La sección de validación anterior no cuenta: se rehace.
    cuerpo = _SECCION_VALIDACION.split(cuerpo)[0]
    lineas = cuerpo.split("\n")

    titulo_recuadro: str | None = None
    cifras_vistas: set[str] = set()
    for linea in lineas:
        afirmacion = _AFIRMACION.match(linea)
        if afirmacion:
            resultado.afirmaciones += 1
            texto_afirmacion = afirmacion.group(1)
            base_cruda = afirmacion.group(2)
            motivo = _motivo_base(enlaces_de(base_cruda), aprobadas, vault)
            if motivo == "no enlaza ningún concepto" and "no está en la base aprobada" in base_cruda:
                citado = re.search(r"«([^»]+)»", base_cruda)
                motivo = (
                    f"se apoya en «{citado.group(1)}», que no está aprobado"
                    if citado
                    else "se apoya en un concepto que no está aprobado"
                )
            if motivo:
                resultado.sin_respaldo.append((texto_afirmacion, motivo))
            else:
                resultado.respaldadas += 1
            _cifras(texto_afirmacion, cifras_base, cifras_vistas, resultado)
            continue

        if _RECUADRO.match(linea):
            resultado.recuadros += 1
            titulo_recuadro = linea.split(":", 1)[-1].strip() or "sin título"
            continue
        if titulo_recuadro is not None:
            if not linea.startswith(">"):
                resultado.recuadros_sin_respaldo.append((titulo_recuadro, "no tiene línea de base"))
                titulo_recuadro = None
            else:
                base = _BASE_RECUADRO.match(linea)
                if base:
                    motivo = _motivo_base(enlaces_de(base.group(1)), aprobadas, vault)
                    if motivo:
                        resultado.recuadros_sin_respaldo.append((titulo_recuadro, motivo))
                    titulo_recuadro = None
                    continue
                _cifras(linea, cifras_base, cifras_vistas, resultado)
                continue

        if linea.lstrip().startswith("#") or "**Base:**" in linea:
            continue  # los títulos numeran capítulos y escenas, no dan datos
        _cifras(linea, cifras_base, cifras_vistas, resultado)

    if titulo_recuadro is not None:
        resultado.recuadros_sin_respaldo.append((titulo_recuadro, "no tiene línea de base"))
    return resultado


def _contenido(nota: Nota) -> str:
    """Lo que una nota aprobada **afirma**, sin sus metadatos.

    De una nota de Tatewari, sus definiciones, detalles y citas: ni la confianza,
    ni las fechas, ni el bloque de datos, que tienen cifras que no son hechos. De
    una nota escrita a mano, su cuerpo sin comentarios ni avisos de estado.
    """
    objeto = nota.objeto()
    if objeto is not None:
        partes = []
        for afirmacion in (*objeto.definiciones, *objeto.detalles):
            partes.append(afirmacion.texto)
            partes.append(afirmacion.cita)
        return " ".join(p for p in partes if p and p != "NR")
    cuerpo = re.sub(r"%%.*?%%", " ", nota.cuerpo, flags=re.S)
    return "\n".join(l for l in cuerpo.split("\n") if not l.startswith("> [!info]"))


def _cifras(texto: str, base: set[str], vistas: set[str], resultado: ValidacionNarrativa) -> None:
    sin_enlaces = re.sub(r"\[\[[^\]]*\]\]", " ", texto)
    for cifra in _CIFRA.findall(sin_enlaces):
        if cifra not in base and cifra not in vistas:
            vistas.add(cifra)
            resultado.cifras_sin_respaldo.append(cifra)


def validar_archivo(ruta: Path | str, vault: Vault) -> ValidacionNarrativa:
    """Valida un borrador ya escrito en el Vault."""
    ruta = Path(ruta)
    if not ruta.is_file():
        raise FileNotFoundError(f"No existe el borrador: {ruta}")
    return validar_borrador(ruta.read_text(encoding="utf-8"), vault)


registrar(
    "divulgacion_validar",
    "Comprueba que cada afirmación, recuadro y cifra de un borrador narrativo tenga "
    "base en conceptos APPROVED.",
    validar_archivo,
)
