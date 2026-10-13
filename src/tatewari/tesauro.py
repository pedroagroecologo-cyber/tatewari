"""Tesauros abiertos: sinónimos y traducciones para escribir el protocolo.

El protocolo es lo que más pesa en una revisión: un sinónimo que falta deja
fuera artículos sin que nadie se entere. El caso que motivó este módulo fue un
protocolo de bloques de tierra compactada escrito por un chat gratuito: no
listó «compressed earth brick», y un artículo de 2024 que solo usa esa forma
se quedó fuera. Esa variante estaba en Wikidata desde antes.

Fuentes
-------

- **AGROVOC** (FAO): tesauro multilingüe de agricultura, agua, suelo,
  alimentación y medio ambiente. Bueno para «constructed wetlands»,
  «microalgae», «soil stabilization»; flojo en materiales de construcción.
  API de Skosmos: https://agrovoc.fao.org/browse/rest/v1/
- **Wikidata**: base de conocimiento abierta con etiquetas y alias en muchos
  idiomas. Cubre lo que AGROVOC no: «compressed earth block» trae «pressed
  earth block», «compressed soil brick», «Bloque de tierra comprimida»…
  API: https://www.wikidata.org/w/api.php

Las dos son gratuitas, sin clave y de licencia abierta (AGENTS.md, regla 5).

Qué hace y qué no
-----------------

**Sugiere; nunca escribe en el protocolo.** Un tesauro dice cómo se llama un
concepto, no cómo lo escriben los autores de tu campo: AGROVOC traduce
«constructed wetlands» como «zona húmeda construida», cuando los artículos
mexicanos dicen «humedal artificial». Elegir qué términos entran sigue siendo
trabajo de la persona.

Las siglas se marcan aparte: Wikidata da «BTC» como alias de *bloque de tierra
comprimida*, y en OpenAlex «BTC» trae sobre todo artículos de Bitcoin.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import quote

from .http import ErrorHttp

__all__ = [
    "AGROVOC",
    "WIKIDATA",
    "FUENTES",
    "IDIOMAS",
    "Concepto",
    "Consulta",
    "es_sigla",
    "url_busqueda_agrovoc",
    "url_concepto_agrovoc",
    "url_busqueda_wikidata",
    "url_entidades_wikidata",
    "concepto_de_agrovoc",
    "conceptos_de_wikidata",
    "buscar",
    "terminos_sugeridos",
]

AGROVOC = "agrovoc"
WIKIDATA = "wikidata"
FUENTES = (AGROVOC, WIKIDATA)

#: Idiomas que se piden y se muestran: los del protocolo.
IDIOMAS = ("en", "es")

BASE_AGROVOC = "https://agrovoc.fao.org/browse/rest/v1/agrovoc"
BASE_WIKIDATA = "https://www.wikidata.org/w/api.php"
PAGINA_WIKIDATA = "https://www.wikidata.org/wiki/"

#: Palabras que, en la descripción de Wikidata, delatan una obra y no un
#: concepto: una tesis o un libro titulados igual que tu término no son un
#: sinónimo. Se comparan como subcadena, en minúsculas.
_OBRAS = (
    "article",
    "thesis",
    "dissertation",
    "edition",
    "book",
    "journal",
    "paper",
    "wikimedia",
    "artículo",
    "tesis",
    "libro",
)

#: Una «etiqueta» con más palabras que esto es un título, no un término.
MAX_PALABRAS = 8

_SIGLA = re.compile(r"^[A-Z0-9]{2,6}s?$")


def es_sigla(termino: str) -> bool:
    """¿Es `termino` una sigla («BTC», «CEB», «UASB», «AgNPs» no)?

    Se marca para avisar, no para descartar: hay siglas inequívocas en su
    campo. Pero hay que comprobarlas antes de meterlas al protocolo.
    """
    return bool(_SIGLA.match(termino.strip()))


@dataclass(frozen=True)
class Concepto:
    """Un concepto de un tesauro, con sus nombres en cada idioma.

    En `etiquetas`, la primera forma de cada idioma es la preferida y el resto
    son alternativas. `relacionados` son nombres de conceptos vecinos (más
    amplios, más estrechos o relacionados), útiles para afinar el alcance.
    """

    fuente: str
    uri: str
    etiquetas: dict[str, tuple[str, ...]]
    descripcion: str = ""
    relacionados: tuple[str, ...] = ()

    @property
    def nombre(self) -> str:
        for idioma in IDIOMAS:
            if self.etiquetas.get(idioma):
                return self.etiquetas[idioma][0]
        return self.uri

    @property
    def enlace(self) -> str:
        if self.fuente == WIKIDATA:
            return PAGINA_WIKIDATA + self.uri
        return self.uri


@dataclass
class Consulta:
    """Lo que devolvió una búsqueda en los tesauros, con sus avisos."""

    termino: str
    conceptos: list[Concepto] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# AGROVOC
# ---------------------------------------------------------------------------


def url_busqueda_agrovoc(termino: str, idioma: str, maximo: int) -> str:
    """Búsqueda por etiqueta, con comodín final para encontrar el plural."""
    return (
        f"{BASE_AGROVOC}/search?query={quote(termino.strip())}*"
        f"&lang={idioma}&maxhits={maximo}"
    )


def url_concepto_agrovoc(uri: str) -> str:
    return f"{BASE_AGROVOC}/data?uri={quote(uri, safe='')}&format=application/json"


def _como_lista(valor: Any) -> list:
    if valor is None:
        return []
    return valor if isinstance(valor, list) else [valor]


def _etiquetas_skos(nodo: dict, campo: str) -> dict[str, list[str]]:
    salida: dict[str, list[str]] = {}
    for etiqueta in _como_lista(nodo.get(campo)):
        if not isinstance(etiqueta, dict):
            continue
        idioma, valor = etiqueta.get("lang"), etiqueta.get("value")
        if idioma in IDIOMAS and isinstance(valor, str) and valor.strip():
            salida.setdefault(idioma, []).append(valor.strip())
    return salida


def _uris(nodo: dict, campo: str) -> list[str]:
    salida = []
    for vecino in _como_lista(nodo.get(campo)):
        uri = vecino.get("uri") if isinstance(vecino, dict) else vecino
        if isinstance(uri, str):
            salida.append(uri)
    return salida


def concepto_de_agrovoc(datos: dict, uri: str) -> Concepto | None:
    """Arma un `Concepto` a partir de la respuesta de ``/data`` de Skosmos.

    La respuesta es un grafo JSON-LD: el concepto pedido y sus vecinos vienen
    como nodos sueltos. De los vecinos solo se toma su nombre preferido.
    """
    nodos = {n.get("uri"): n for n in _como_lista(datos.get("graph")) if isinstance(n, dict)}
    nodo = nodos.get(uri)
    if nodo is None:
        return None
    preferidas = _etiquetas_skos(nodo, "prefLabel")
    alternativas = _etiquetas_skos(nodo, "altLabel")
    etiquetas = {
        idioma: tuple(dict.fromkeys(preferidas.get(idioma, []) + alternativas.get(idioma, [])))
        for idioma in IDIOMAS
        if preferidas.get(idioma) or alternativas.get(idioma)
    }
    relacionados: list[str] = []
    for campo in ("broader", "narrower", "related"):
        for vecino in _uris(nodo, campo):
            nombres = _etiquetas_skos(nodos.get(vecino, {}), "prefLabel")
            for idioma in IDIOMAS:
                if nombres.get(idioma):
                    relacionados.append(nombres[idioma][0])
                    break
    return Concepto(
        fuente=AGROVOC,
        uri=uri,
        etiquetas=etiquetas,
        relacionados=tuple(dict.fromkeys(relacionados)),
    )


def _buscar_agrovoc(cliente, termino: str, maximo: int) -> list[Concepto]:
    uris: list[str] = []
    for idioma in IDIOMAS:
        respuesta = cliente.obtener_json(url_busqueda_agrovoc(termino, idioma, maximo))
        for resultado in _como_lista(respuesta.get("results")):
            uri = resultado.get("uri") if isinstance(resultado, dict) else None
            if isinstance(uri, str) and uri not in uris:
                uris.append(uri)
    conceptos = []
    for uri in uris[:maximo]:
        concepto = concepto_de_agrovoc(cliente.obtener_json(url_concepto_agrovoc(uri)), uri)
        if concepto is not None:
            conceptos.append(concepto)
    return conceptos


# ---------------------------------------------------------------------------
# Wikidata
# ---------------------------------------------------------------------------


def url_busqueda_wikidata(termino: str, idioma: str, maximo: int) -> str:
    return (
        f"{BASE_WIKIDATA}?action=wbsearchentities&search={quote(termino.strip())}"
        f"&language={idioma}&uselang={idioma}&type=item&limit={maximo}&format=json"
    )


def url_entidades_wikidata(identificadores: Iterable[str]) -> str:
    ids = "|".join(identificadores)
    idiomas = "|".join(IDIOMAS)
    return (
        f"{BASE_WIKIDATA}?action=wbgetentities&ids={quote(ids, safe='|')}"
        f"&props=labels%7Caliases%7Cdescriptions&languages={quote(idiomas, safe='|')}"
        f"&format=json"
    )


def _descartada(descripcion: str) -> bool:
    """¿La descripción dice que es una obra (tesis, libro, artículo…)?"""
    minusculas = descripcion.lower()
    return any(palabra in minusculas for palabra in _OBRAS)


def _es_termino(forma: str) -> bool:
    return 0 < len(forma.split()) <= MAX_PALABRAS


def conceptos_de_wikidata(datos: dict) -> list[Concepto]:
    """Arma los `Concepto` de una respuesta de ``wbgetentities``."""
    conceptos = []
    entidades = datos.get("entities") or {}
    for identificador, entidad in entidades.items():
        if not isinstance(entidad, dict) or "missing" in entidad:
            continue
        descripciones = entidad.get("descriptions") or {}
        descripcion = ""
        for idioma in IDIOMAS:
            valor = (descripciones.get(idioma) or {}).get("value")
            if isinstance(valor, str):
                descripcion = valor
                break
        if _descartada(descripcion):
            continue
        etiquetas: dict[str, tuple[str, ...]] = {}
        for idioma in IDIOMAS:
            formas = []
            principal = ((entidad.get("labels") or {}).get(idioma) or {}).get("value")
            if isinstance(principal, str) and principal.strip():
                formas.append(principal.strip())
            for alias in (entidad.get("aliases") or {}).get(idioma) or []:
                valor = alias.get("value") if isinstance(alias, dict) else None
                if isinstance(valor, str) and valor.strip():
                    formas.append(valor.strip())
            if formas:
                etiquetas[idioma] = tuple(dict.fromkeys(formas))
        if etiquetas:
            conceptos.append(
                Concepto(
                    fuente=WIKIDATA,
                    uri=identificador,
                    etiquetas=etiquetas,
                    descripcion=descripcion,
                )
            )
    return conceptos


def _buscar_wikidata(cliente, termino: str, maximo: int) -> list[Concepto]:
    ids: list[str] = []
    for idioma in IDIOMAS:
        respuesta = cliente.obtener_json(url_busqueda_wikidata(termino, idioma, maximo))
        for resultado in _como_lista(respuesta.get("search")):
            if not isinstance(resultado, dict):
                continue
            if _descartada(str(resultado.get("description", ""))):
                continue
            identificador = resultado.get("id")
            if isinstance(identificador, str) and identificador not in ids:
                ids.append(identificador)
    if not ids:
        return []
    datos = cliente.obtener_json(url_entidades_wikidata(ids[:maximo]))
    orden = {identificador: indice for indice, identificador in enumerate(ids)}
    return sorted(conceptos_de_wikidata(datos), key=lambda c: orden.get(c.uri, 99))


# ---------------------------------------------------------------------------
# Todo junto
# ---------------------------------------------------------------------------

_BUSCADORES = {AGROVOC: _buscar_agrovoc, WIKIDATA: _buscar_wikidata}
_NOMBRES = {AGROVOC: "AGROVOC", WIKIDATA: "Wikidata"}


def buscar(
    termino: str,
    cliente,
    fuentes: Iterable[str] = FUENTES,
    maximo: int = 3,
) -> Consulta:
    """Busca `termino` en los tesauros y devuelve sus conceptos.

    Si una fuente falla, se anota el aviso y se sigue con la otra: un tesauro
    caído no debe impedir ver lo que dice el otro.
    """
    consulta = Consulta(termino=termino)
    for fuente in fuentes:
        try:
            hallados = _BUSCADORES[fuente](cliente, termino, maximo)
        except ErrorHttp as error:
            consulta.avisos.append(f"{_NOMBRES[fuente]} no respondió: {error}")
            continue
        if not hallados:
            consulta.avisos.append(f"{_NOMBRES[fuente]}: sin coincidencias.")
        consulta.conceptos.extend(hallados)
    return consulta


def terminos_sugeridos(consulta: Consulta) -> tuple[list[str], list[str]]:
    """Términos para copiar al protocolo y siglas para revisar a mano.

    Devuelve dos listas sin repetidos (sin importar mayúsculas): las frases,
    en el orden en que aparecieron, y aparte las siglas.
    """
    frases: dict[str, str] = {}
    siglas: dict[str, str] = {}
    for concepto in consulta.conceptos:
        for idioma in IDIOMAS:
            for forma in concepto.etiquetas.get(idioma, ()):
                if not _es_termino(forma):
                    continue
                destino = siglas if es_sigla(forma) else frases
                destino.setdefault(forma.casefold(), forma if es_sigla(forma) else forma.lower())
    return list(frases.values()), list(siglas.values())
