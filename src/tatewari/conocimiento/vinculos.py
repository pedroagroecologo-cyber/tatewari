"""Vínculos: qué hacer con cada objeto frente a lo que ya hay en el Vault.

Para cada objeto nuevo se decide una de tres acciones:

``crear``
    No hay ninguna nota con ese nombre ni alias.
``actualizar``
    Hay una nota de Tatewari en DRAFT o REVIEW que nadie ha tocado: se funde lo
    nuevo con lo que había.
``proponer``
    Hay una nota, pero es de una persona, está aprobada o se editó a mano. No se
    toca: la propuesta va a la bandeja de entrada.

Además se buscan **posibles duplicados** con nombre distinto (el mismo concepto
llamado de dos formas) comparando el contenido, y **conflictos**: dos fuentes que
definen lo mismo de forma distinta. Los duplicados se señalan; los conflictos se
anotan con las dos versiones. Ninguno de los dos se resuelve en automático.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from ..texto import normalizar
from .documento import NR
from .objetos import Afirmacion, ObjetoConocimiento, ahora, anadir_a
from .vault import Nota, Vault

__all__ = [
    "Accion",
    "planificar",
    "fundir_con_nota",
    "detectar_conflictos",
    "similitud",
    "UMBRAL_DUPLICADO",
    "UMBRAL_CONFLICTO",
]

#: A partir de aquí, dos definiciones con nombre distinto parecen el mismo concepto.
UMBRAL_DUPLICADO = 0.55

#: Por debajo de esto, dos definiciones del mismo concepto dicen cosas distintas.
UMBRAL_CONFLICTO = 0.25

_VACIAS = {
    "el", "la", "los", "las", "de", "del", "y", "o", "en", "un", "una", "que", "es",
    "se", "por", "para", "con", "al", "a", "su", "sus", "lo", "como", "the", "of",
    "and", "in", "is", "to",
}
_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")


def _palabras(texto: str) -> set[str]:
    return {p for p in re.findall(r"\w+", normalizar(texto)) if len(p) > 2 and p not in _VACIAS}


def similitud(uno: str, otro: str) -> float:
    """Jaccard de palabras con contenido. 0 = nada en común, 1 = mismas palabras."""
    a, b = _palabras(uno), _palabras(otro)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class Accion:
    """Lo que se va a hacer con un objeto."""

    objeto: ObjetoConocimiento
    tipo: str  # crear | actualizar | proponer
    nota: Nota | None = None
    motivo: str = ""
    posibles_duplicados: list[str] = field(default_factory=list)


def _texto_definiciones(afirmaciones: Iterable[Afirmacion]) -> str:
    return " ".join(a.texto for a in afirmaciones)


def detectar_conflictos(
    existentes: list[Afirmacion], nuevas: list[Afirmacion]
) -> list[dict]:
    """Definiciones de documentos distintos que no dicen lo mismo.

    Se marca conflicto cuando dos definiciones **comprobadas contra su fuente**, de
    documentos distintos, apenas comparten palabras, o cuando dan cifras
    distintas. Las inferencias del modelo no generan conflictos: no son fuentes.
    """
    conflictos = []
    for nueva in nuevas:
        if not nueva.es_de_la_fuente:
            continue
        for vieja in existentes:
            if not vieja.es_de_la_fuente or vieja.documento == nueva.documento:
                continue
            cifras_viejas = set(_NUMERO.findall(vieja.texto))
            cifras_nuevas = set(_NUMERO.findall(nueva.texto))
            cifras_distintas = bool(cifras_viejas and cifras_nuevas and cifras_viejas != cifras_nuevas)
            if cifras_distintas or similitud(vieja.texto, nueva.texto) < UMBRAL_CONFLICTO:
                conflictos.append(
                    {
                        "campo": "definicion",
                        "descripcion": (
                            "Las fuentes dan cifras distintas"
                            if cifras_distintas
                            else "Las fuentes definen esto de forma distinta"
                        ),
                        "versiones": [
                            {"texto": vieja.texto, "documento": vieja.documento, "ubicacion": vieja.ubicacion},
                            {"texto": nueva.texto, "documento": nueva.documento, "ubicacion": nueva.ubicacion},
                        ],
                        "detectado": ahora(),
                    }
                )
    return conflictos


def fundir_con_nota(nota: Nota, nuevo: ObjetoConocimiento) -> ObjetoConocimiento:
    """El objeto de la nota con lo nuevo añadido. Conserva ambas fuentes siempre.

    Si aparece un conflicto, el objeto pasa a REVIEW: una persona tiene que mirar
    las dos versiones. La fecha de creación y el identificador se conservan.
    """
    base = nota.objeto()
    if base is None:
        return nuevo
    conflictos = detectar_conflictos(base.definiciones, nuevo.definiciones)
    fundido = anadir_a(base, nuevo)
    fundido.creado = base.creado
    fundido.id = base.id
    # El nombre visible sigue siendo el de la nota; el del documento nuevo, alias.
    if nuevo.titulo != base.titulo and nuevo.titulo not in fundido.alias:
        fundido.alias.append(nuevo.titulo)
    existentes = {(c.get("descripcion"), str(c.get("versiones"))) for c in base.conflictos}
    fundido.conflictos = list(base.conflictos) + [
        c for c in conflictos if (c["descripcion"], str(c["versiones"])) not in existentes
    ]
    if fundido.conflictos:
        fundido.estado = "REVIEW"
    fundido.actualizado = ahora()
    return fundido


def _dentro_de(ruta, carpeta) -> bool:
    try:
        ruta.relative_to(carpeta)
        return True
    except ValueError:
        return False


def planificar(objetos: list[ObjetoConocimiento], vault: Vault) -> list[Accion]:
    """knowledge_link: decide crear, actualizar o proponer para cada objeto."""
    acciones = []
    materia = vault.carpeta("materia")
    # Los documentos originales de la materia no son notas de conocimiento: un
    # apunte en Markdown se parecería a todo lo que se extrajo de él.
    notas = [n for n in vault.notas() if not _dentro_de(n.ruta, materia)]
    for objeto in objetos:
        nota = vault.buscar(objeto.titulo, objeto.alias)
        if nota is None:
            accion = Accion(objeto=objeto, tipo="crear")
            # ¿El mismo concepto con otro nombre? Se compara contenido.
            definicion = _texto_definiciones(objeto.definiciones) or objeto.resumen
            if definicion and definicion != NR:
                for otra in notas:
                    if otra.tipo in ("fuente", "propuesta", "indice"):
                        continue
                    comparable = _texto_definiciones(otra.objeto().definiciones) if otra.datos else otra.texto_plano[:1500]
                    if comparable and similitud(definicion, comparable) >= UMBRAL_DUPLICADO:
                        accion.posibles_duplicados.append(otra.nombre)
                if accion.posibles_duplicados:
                    objeto.estado = "REVIEW"
            acciones.append(accion)
            continue

        motivo = vault.motivo_para_no_tocar(nota)
        if motivo:
            acciones.append(Accion(objeto=objeto, tipo="proponer", nota=nota, motivo=motivo))
        else:
            acciones.append(
                Accion(objeto=fundir_con_nota(nota, objeto), tipo="actualizar", nota=nota)
            )
    return acciones
