"""Fuente secundaria: Crossref.

Documentación: https://api.crossref.org (API REST pública de Crossref)

Se usa como segunda opinión sobre OpenAlex: cubre bien lo que tiene DOI y a
veces trae resumen donde OpenAlex no lo tiene. La búsqueda va por
``query.bibliographic``, que es el campo pensado para buscar por una cadena
bibliográfica libre.

El correo va en ``mailto``, igual que en OpenAlex: identificarse mete las
peticiones en la cola educada.

La forma del registro de salida es la misma que la de OpenAlex y la del
fixture. Dos diferencias que hay que tener presentes:

- **El resumen viene en JATS**, con etiquetas XML dentro (``<jats:p>``). Se
  limpian las etiquetas y se deshacen las entidades; no se reescribe el texto.
- **El vocabulario de tipos es distinto.** Crossref dice ``journal-article``
  donde OpenAlex dice ``article``. Se traduce con un diccionario explícito y
  corto; lo que no esté en él se deja **tal cual vino**, nunca se adivina.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from ..protocolo import Protocolo
from . import NR, entero_o_nr, limpiar_termino, lista_o_nr, registro_en_blanco, texto_o_nr

__all__ = [
    "BASE",
    "NOMBRE",
    "FILAS_MAXIMO",
    "CURSOR_INICIAL",
    "TIPOS",
    "ResultadoBusqueda",
    "construir_url",
    "normalizar_item",
    "limpiar_jats",
    "buscar",
]

NOMBRE = "Crossref"
BASE = "https://api.crossref.org/works"

FILAS_MAXIMO = 100
CURSOR_INICIAL = "*"

#: Traducción de tipos de Crossref al vocabulario de OpenAlex, que es el que
#: usan los protocolos. Lo que no esté aquí se deja como venga.
TIPOS = {
    "journal-article": "article",
    "proceedings-article": "article",
    "posted-content": "preprint",
    "book-chapter": "book-chapter",
    "monograph": "book",
}

_SEGUROS_FILTRO = ":,"
_ETIQUETAS = re.compile(r"<[^>]+>")
_ESPACIOS = re.compile(r"\s+")


def limpiar_jats(valor: Any) -> str:
    """Quita las etiquetas JATS del resumen y deshace las entidades HTML.

    No reescribe nada: solo desnuda el texto que ya venía.
    """
    texto = texto_o_nr(valor)
    if texto == NR:
        return NR
    texto = _ETIQUETAS.sub(" ", texto)
    texto = html.unescape(texto)
    texto = _ESPACIOS.sub(" ", texto).strip()
    return texto or NR


def construir_url(
    ecuacion: str,
    protocolo: Protocolo,
    correo: str,
    cursor: str = CURSOR_INICIAL,
    filas: int = FILAS_MAXIMO,
) -> str:
    """Arma la URL literal de una consulta a Crossref.

    Igual que en OpenAlex, se construye a mano para que los espacios queden
    como ``%20`` y no como ``+``.
    """
    filas = max(1, min(int(filas), FILAS_MAXIMO))
    consulta = limpiar_termino(ecuacion)

    filtros = []
    inicio, fin = protocolo.ventana
    if inicio:
        filtros.append(f"from-pub-date:{inicio}-01-01")
    if fin:
        filtros.append(f"until-pub-date:{fin}-12-31")

    parametros = [
        ("query.bibliographic", quote(consulta, safe="")),
        ("rows", str(filas)),
        ("cursor", quote(cursor, safe="*")),
    ]
    if filtros:
        parametros.insert(1, ("filter", quote(",".join(filtros), safe=_SEGUROS_FILTRO)))
    if correo:
        parametros.append(("mailto", quote(correo, safe="@")))

    cadena = "&".join(f"{clave}={valor}" for clave, valor in parametros)
    return f"{BASE}?{cadena}"


def _primer_texto(valor: Any) -> str:
    """Crossref devuelve título y revista como lista; nos quedamos con el primero."""
    if isinstance(valor, (list, tuple)):
        return texto_o_nr(valor[0]) if valor else NR
    return texto_o_nr(valor)


def _anio_de_fecha(item: dict) -> int | str:
    """Año de publicación, mirando los campos de fecha por orden de fiabilidad."""
    for clave in ("issued", "published-print", "published-online", "created"):
        partes = (item.get(clave) or {}).get("date-parts")
        if isinstance(partes, list) and partes and isinstance(partes[0], list) and partes[0]:
            anio = entero_o_nr(partes[0][0])
            if anio != NR:
                return anio
    return NR


def _autores(item: dict) -> list[str]:
    nombres = []
    for autor in item.get("author") or []:
        if not isinstance(autor, dict):
            continue
        apellido = (autor.get("family") or "").strip()
        nombre = (autor.get("given") or "").strip()
        if apellido and nombre:
            nombres.append(f"{apellido}, {nombre}")
        elif apellido or nombre:
            nombres.append(apellido or nombre)
        elif autor.get("name"):
            nombres.append(str(autor["name"]).strip())
    return lista_o_nr(nombres)


def normalizar_item(item: Any) -> dict[str, Any]:
    """Convierte un elemento de Crossref al registro común de Tatewari."""
    registro = registro_en_blanco()
    if not isinstance(item, dict):
        return registro

    doi = texto_o_nr(item.get("DOI"))
    registro["doi"] = doi.lower() if doi != NR else NR
    registro["titulo"] = _primer_texto(item.get("title"))
    registro["anio"] = _anio_de_fecha(item)
    registro["idioma"] = texto_o_nr(item.get("language"))
    registro["revista"] = _primer_texto(item.get("container-title"))
    registro["autores"] = _autores(item)
    registro["resumen"] = limpiar_jats(item.get("abstract"))

    tipo = texto_o_nr(item.get("type"))
    registro["tipo"] = TIPOS.get(tipo, tipo)

    registro["citas"] = entero_o_nr(item.get("is-referenced-by-count"))

    # Crossref no dice de forma fiable si hay versión abierta: eso lo resuelve
    # Unpaywall en su propio paso. Aquí queda "NR", no una URL adivinada.
    registro["oa_url"] = NR

    registro["volumen"] = texto_o_nr(item.get("volume"))
    registro["numero"] = texto_o_nr(item.get("issue"))
    paginas = texto_o_nr(item.get("page"))
    registro["paginas"] = paginas.replace("-", "–") if paginas != NR else NR

    return registro


@dataclass
class ResultadoBusqueda:
    """Lo que devuelve una ecuación en Crossref."""

    ecuacion: str
    registros: list[dict[str, Any]] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    paginas: int = 0
    total_declarado: int | str = NR

    @property
    def url_literal(self) -> str:
        return self.urls[0] if self.urls else NR


def buscar(
    ecuacion: str,
    protocolo: Protocolo,
    cliente: Any,
    correo: str,
    max_paginas: int = 5,
    filas: int = FILAS_MAXIMO,
) -> ResultadoBusqueda:
    """Lanza una ecuación contra Crossref, paginando por cursor profundo."""
    resultado = ResultadoBusqueda(ecuacion=ecuacion)
    cursor: str | None = CURSOR_INICIAL

    for _ in range(max(1, int(max_paginas))):
        if not cursor:
            break

        url = construir_url(ecuacion, protocolo, correo, cursor=cursor, filas=filas)
        resultado.urls.append(url)

        datos = cliente.obtener_json(url)
        resultado.paginas += 1

        mensaje = datos.get("message") if isinstance(datos, dict) else None
        mensaje = mensaje if isinstance(mensaje, dict) else {}

        items = mensaje.get("items") or []
        resultado.registros.extend(normalizar_item(item) for item in items)

        if resultado.total_declarado == NR:
            resultado.total_declarado = entero_o_nr(mensaje.get("total-results"))

        cursor = mensaje.get("next-cursor")
        if not items:
            break

    return resultado
