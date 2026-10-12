"""Normalización y troceado: texto limpio en trozos del tamaño del modelo.

Limpiar
-------

Lo que sale de un PDF viene con costuras: palabras partidas al final de línea
(«remo-\\nción»), guiones blandos invisibles, espacios duplicados, y la misma
cabecera o el mismo pie repetido en cada página. Todo eso estorba al modelo y a
la verificación de citas. `normalizar_documento` lo quita:

- une las palabras partidas por guion al final de línea, solo entre letras;
- quita guiones blandos y caracteres de control;
- colapsa espacios y líneas en blanco repetidas;
- en documentos de tres páginas o más, quita las líneas que se repiten en la
  mayoría de las páginas: cabeceras, pies y números de página.

Lo que **no** hace: corregir ortografía, traducir, reordenar. El texto sigue
siendo el del documento, porque después se le van a buscar citas literales.

Trocear
-------

Un modelo local con 4096 tokens de contexto no puede leer un libro de una vez.
`trocear` agrupa fragmentos consecutivos hasta un máximo de caracteres, y parte
los que no caben por sus párrafos. Cada `Trozo` conserva la lista de fragmentos
de los que sale, así que la ubicación de lo que el modelo encuentre dentro se
puede reconstruir exactamente.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field, replace

from .documento import Documento, Fragmento

__all__ = [
    "normalizar_texto",
    "normalizar_documento",
    "Trozo",
    "trocear",
    "MAXIMO_TROZO",
]

#: Caracteres por trozo. Con el prompt, las instrucciones y la respuesta, cabe
#: con holgura en 4096 tokens, que es el `num_ctx` que usa Tatewari.
MAXIMO_TROZO = 2600

_PARTIDA = re.compile(r"(?<=[^\W\d_])-\n(?=[^\W\d_])")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ESPACIOS = re.compile(r"[ \t  ]+")
_VACIAS = re.compile(r"\n{3,}")
_SOLO_NUMERO = re.compile(r"^\s*(p[áa]g(ina)?\.?\s*)?\d{1,4}(\s*(/|de)\s*\d{1,4})?\s*$", re.I)


def normalizar_texto(texto: str) -> str:
    """Limpia un texto sin cambiar lo que dice."""
    limpio = unicodedata.normalize("NFC", texto.replace("\r\n", "\n").replace("\r", "\n"))
    limpio = limpio.replace("­", "")  # guion blando
    limpio = _CONTROL.sub("", limpio)
    limpio = _PARTIDA.sub("", limpio)
    lineas = [_ESPACIOS.sub(" ", linea).strip() for linea in limpio.split("\n")]
    return _VACIAS.sub("\n\n", "\n".join(lineas)).strip()


def _repetidas(fragmentos: list[Fragmento]) -> set[str]:
    """Líneas que aparecen en la mayoría de las páginas: cabeceras y pies."""
    if len(fragmentos) < 3:
        return set()
    cuenta: Counter[str] = Counter()
    for fragmento in fragmentos:
        cuenta.update({linea.strip() for linea in fragmento.texto.split("\n") if linea.strip()})
    umbral = max(3, int(len(fragmentos) * 0.6))
    return {linea for linea, veces in cuenta.items() if veces >= umbral and len(linea) < 120}


def normalizar_documento(documento: Documento) -> Documento:
    """Devuelve el documento con cada fragmento limpio. No toca el original."""
    repetidas = _repetidas(documento.fragmentos) if documento.tipo == "pdf" else set()
    nuevos: list[Fragmento] = []
    quitadas = 0
    for fragmento in documento.fragmentos:
        lineas = []
        for linea in fragmento.texto.split("\n"):
            desnuda = linea.strip()
            if desnuda in repetidas or (documento.tipo == "pdf" and _SOLO_NUMERO.match(desnuda)):
                quitadas += 1
                continue
            lineas.append(linea)
        texto = normalizar_texto("\n".join(lineas))
        if texto:
            nuevos.append(replace(fragmento, texto=texto))
    if repetidas:
        cuantas = len(repetidas)
        que = "línea repetida" if cuantas == 1 else "líneas repetidas"
        documento.avisos.append(
            f"Se quitó {cuantas} {que} en casi todas las páginas (cabecera o pie)."
            if cuantas == 1
            else f"Se quitaron {cuantas} {que} en casi todas las páginas (cabeceras o pies)."
        )
    documento.fragmentos = nuevos
    return documento


@dataclass
class Trozo:
    """Lo que se le manda al modelo de una vez, con sus fragmentos de origen."""

    indice: int
    fragmentos: list[Fragmento] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return "\n\n".join(f.texto for f in self.fragmentos)

    @property
    def ubicacion(self) -> str:
        """La ubicación del trozo entero, para cuando no se puede afinar más."""
        if not self.fragmentos:
            return "NR"
        primera = self.fragmentos[0].ubicacion
        ultima = self.fragmentos[-1].ubicacion
        return primera if primera == ultima else f"{primera} a {ultima}"


def _partir(fragmento: Fragmento, maximo: int) -> list[Fragmento]:
    """Parte un fragmento largo por párrafos. Las partes heredan la ubicación."""
    if len(fragmento.texto) <= maximo:
        return [fragmento]
    parrafos = fragmento.texto.split("\n\n")
    partes: list[str] = []
    actual = ""
    for parrafo in parrafos:
        # Un párrafo que por sí solo no cabe se parte por frases.
        piezas = [parrafo] if len(parrafo) <= maximo else re.split(r"(?<=[.!?])\s+", parrafo)
        for pieza in piezas:
            while len(pieza) > maximo:  # ni por frases: corte duro
                partes.append(pieza[:maximo])
                pieza = pieza[maximo:]
            if actual and len(actual) + len(pieza) + 2 > maximo:
                partes.append(actual)
                actual = pieza
            else:
                actual = f"{actual}\n\n{pieza}" if actual else pieza
    if actual:
        partes.append(actual)
    return [
        replace(fragmento, id=f"{fragmento.id}.{n}", texto=texto)
        for n, texto in enumerate(partes, start=1)
    ]


def trocear(documento: Documento, maximo: int = MAXIMO_TROZO) -> list[Trozo]:
    """Agrupa los fragmentos en trozos de hasta `maximo` caracteres, en orden."""
    trozos: list[Trozo] = []
    actual = Trozo(indice=1)
    largo = 0
    for fragmento in documento.fragmentos:
        for parte in _partir(fragmento, maximo):
            if actual.fragmentos and largo + len(parte.texto) + 2 > maximo:
                trozos.append(actual)
                actual = Trozo(indice=len(trozos) + 1)
                largo = 0
            actual.fragmentos.append(parte)
            largo += len(parte.texto) + 2
    if actual.fragmentos:
        trozos.append(actual)
    return trozos
