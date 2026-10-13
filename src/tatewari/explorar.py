"""Explorar por significado antes de cosechar: ¿qué se le escapa a tu protocolo?

La cosecha busca **palabras exactas**: es reproducible, pero solo encuentra lo
que el protocolo sabe nombrar. Un sinónimo que falta («compressed earth
*bricks*» además de *blocks*) deja fuera artículos sin que nadie se entere.

OpenAlex tiene una búsqueda **por significado** (``search.semantic``): se le
describe el tema con palabras normales, en español o en inglés, y devuelve los
trabajos más parecidos, hasta 50. Este módulo la usa para **auditar el
protocolo antes de la cosecha grande**:

1. Busca por significado.
2. Para cada resultado, mira si la cosecha lo encontraría (algún término del
   eje y del cruce en el título o el resumen) y qué decidiría el cribado.
3. Junta las frases que se repiten en los títulos de los que se escapan: son
   candidatas a sinónimos que le faltan al protocolo.

No sustituye a la cosecha: 50 resultados «parecidos» no son una revisión
sistemática, y la búsqueda semántica no se puede repetir con exactitud. Sirve
para descubrir lo que no sabías nombrar. La URL de la consulta se imprime, para
dejar constancia.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import quote

from .cribado import decidir
from .fuentes import NR
from .fuentes.openalex import normalizar_obra
from .texto import contiene, normalizar

__all__ = [
    "BASE",
    "MAXIMO",
    "Hallado",
    "Exploracion",
    "construir_url",
    "la_cosecharia",
    "explorar",
    "frases_frecuentes",
]

BASE = "https://api.openalex.org/works"
#: Lo más que devuelve la búsqueda semántica de OpenAlex.
MAXIMO = 50

_PALABRAS_VACIAS = set(
    """a an and are as at be by for from in into is of on or the to with using
    via its their this that these those study studies analysis effect effects
    evaluation case review based new use under between towards toward
    de del la las el los en y o con para por un una sobre su sus al como entre
    estudio analisis efecto efectos evaluacion caso revision uso""".split()
)


def construir_url(
    texto: str,
    por_pagina: int = 25,
    anios: tuple[int, int] | None = None,
    tipos: Iterable[str] = (),
    correo: str = "",
    idiomas: Iterable[str] = (),
) -> str:
    """La URL literal de la búsqueda semántica, con los filtros que admite.

    OpenAlex solo admite algunos filtros con ``search.semantic``: año, tipo e
    idioma sí; ``from_publication_date``, no (responde 400).
    """
    filtros = []
    if anios:
        filtros.append(f"publication_year:{anios[0]}-{anios[1]}")
    tipos = [t for t in tipos if t]
    if tipos:
        filtros.append("type:" + "|".join(tipos))
    idiomas = [i for i in idiomas if i]
    if idiomas:
        filtros.append("language:" + "|".join(idiomas))
    url = (
        f"{BASE}?search.semantic={quote(texto.strip())}"
        f"&per-page={max(1, min(MAXIMO, por_pagina))}"
    )
    if filtros:
        url += "&filter=" + quote(",".join(filtros), safe=":|,-")
    if correo:
        url += f"&mailto={quote(correo, safe='@')}"
    return url


def la_cosecharia(registro: dict[str, Any], protocolo: Any) -> bool:
    """¿Lo encontrarían las ecuaciones del protocolo? Aproximado, sin red.

    Una ecuación es «término del eje» Y «término del cruce» en el título o el
    resumen. Aquí se comprueba con la misma tolerancia a plurales y guiones del
    cribado; OpenAlex además aplica su propia lematización, así que esto puede
    quedarse corto, nunca pasarse de largo.
    """
    consulta = getattr(protocolo, "consulta", None)
    if consulta is None:
        return False
    texto = f"{registro.get('titulo') or ''} {registro.get('resumen') or ''}"
    eje = protocolo.terminos_de(consulta.eje)
    if not any(contiene(texto, termino) for termino in eje):
        return False
    if not consulta.cruce:
        return True
    return any(contiene(texto, termino) for termino in consulta.cruce)


@dataclass
class Hallado:
    registro: dict[str, Any]
    relevancia: float | None = None
    cosechado: bool | None = None
    decision: str = NR
    motivo: str = NR

    def linea(self) -> str:
        anio = self.registro.get("anio") or NR
        titulo = str(self.registro.get("titulo") or NR)
        doi = self.registro.get("doi") or NR
        marcas = ""
        if self.cosechado is not None:
            busqueda = "la busca" if self.cosechado else "NO la busca"
            marcas = f"[{busqueda} · cribado: {self.decision}] "
        return f"{marcas}{anio}  {titulo[:110]}  (DOI: {doi})"


@dataclass
class Exploracion:
    texto: str
    url: str
    hallados: list[Hallado] = field(default_factory=list)
    sugerencias: list[tuple[str, int]] = field(default_factory=list)

    @property
    def escapados(self) -> list[Hallado]:
        return [h for h in self.hallados if h.cosechado is False]


def _sin_cubrir(frase: str, terminos: list[str]) -> bool:
    return not any(contiene(frase, termino) or contiene(termino, frase) for termino in terminos)


def frases_frecuentes(
    titulos: Iterable[str], terminos: Iterable[str], minimo: int = 2, maximo: int = 10
) -> list[tuple[str, int]]:
    """Pares y tríos de palabras repetidos en `titulos` que el protocolo no tiene.

    Se cuenta cada frase una vez por título. Lo que aparece en varios títulos de
    los que se escapan es candidato a sinónimo; decide la persona.
    """
    terminos = [t for t in terminos if t]
    cuenta: Counter[str] = Counter()
    for titulo in titulos:
        palabras = [p for p in re.split(r"[^0-9a-z]+", normalizar(titulo)) if p]
        vistas = set()
        for largo in (3, 2):
            for inicio in range(len(palabras) - largo + 1):
                trozo = palabras[inicio : inicio + largo]
                if trozo[0] in _PALABRAS_VACIAS or trozo[-1] in _PALABRAS_VACIAS:
                    continue
                if any(p.isdigit() for p in trozo):
                    continue
                vistas.add(" ".join(trozo))
        cuenta.update(vistas)
    # Orden fijo: más títulos primero; a igualdad, la frase más larga (la más
    # específica) y luego el alfabeto. Sin esto el empate depende del azar de
    # los conjuntos de Python y la salida cambia entre corridas.
    candidatas = sorted(
        (
            (frase, veces)
            for frase, veces in cuenta.items()
            if veces >= minimo and _sin_cubrir(frase, terminos)
        ),
        key=lambda par: (-par[1], -len(par[0].split()), par[0]),
    )
    # Si un trío ya está, su par contenido sobra cuando aparece las mismas veces.
    finales: list[tuple[str, int]] = []
    for frase, veces in candidatas:
        if any(frase in otra and veces == v for otra, v in finales):
            continue
        finales.append((frase, veces))
    return finales[:maximo]


def explorar(
    texto: str,
    cliente: Any,
    protocolo: Any = None,
    por_pagina: int = 25,
    correo: str = "",
) -> Exploracion:
    """Busca `texto` por significado y, si hay protocolo, lo audita."""
    anios = None
    tipos: list[str] = []
    idiomas: list[str] = []
    if protocolo is not None:
        anios = tuple(protocolo.ventana)
        tipos = list(protocolo.tipos)
        idiomas = list(protocolo.idiomas)
    url = construir_url(texto, por_pagina, anios, tipos, correo, idiomas)
    respuesta = cliente.obtener_json(url)
    exploracion = Exploracion(texto=texto, url=url)
    for obra in respuesta.get("results") or []:
        registro = normalizar_obra(obra)
        hallado = Hallado(registro=registro, relevancia=obra.get("relevance_score"))
        if protocolo is not None:
            hallado.cosechado = la_cosecharia(registro, protocolo)
            decision = decidir(registro, protocolo)
            hallado.decision = decision.decision
            hallado.motivo = decision.motivo
        exploracion.hallados.append(hallado)
    if protocolo is not None:
        terminos = [t for lista in protocolo.bloques.values() for t in lista]
        terminos += [t for lista in protocolo.grupos.values() for t in lista]
        terminos += list(protocolo.consulta.cruce) if protocolo.consulta else []
        exploracion.sugerencias = frases_frecuentes(
            (str(h.registro.get("titulo") or "") for h in exploracion.escapados), terminos
        )
    return exploracion
