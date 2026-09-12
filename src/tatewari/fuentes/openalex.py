"""Fuente primaria: OpenAlex.

Documentación: https://docs.openalex.org

Cómo se arman las consultas
---------------------------

OpenAlex **no acepta una booleana anidada arbitraria** dentro de un solo
filtro. El protocolo sí la tiene: un bloque eje con muchos términos, cruzado
con una lista de términos. Así que el AND/OR del protocolo se reproduce
desplegándolo: una consulta por cada par (término del eje × término del cruce),
con la forma

    "humedal artificial" AND "anaerobic"

Cada término va entre comillas para que OpenAlex lo busque como frase y no como
palabras sueltas.

Errores que ya costaron tiempo y que este módulo evita
-----------------------------------------------------

1. **Idioma.** Es ``language:es|en``, con códigos ISO. **No** es
   ``language:languages/en``: esa es la forma de identificador de entidad y la
   API devuelve error.
2. **Tipo.** Es ``type:article|review``. **No** es ``type:types/article``.
3. **Comas.** Dentro de ``filter=`` la coma separa un filtro del siguiente, así
   que ningún término puede llevar una coma dentro. Se limpian antes de armar
   la consulta (ver `limpiar_termino`).
4. **Codificación.** El valor del filtro se codifica con *percent-encoding*
   explícito: los espacios tienen que quedar como ``%20``. Si se deja que la
   librería arme la cadena de consulta, los convierte en ``+`` y OpenAlex no
   los interpreta como espacio. Por eso aquí se construye la URL entera a mano
   y nunca se usa ``params=``.
5. **Booleanos en mayúsculas.** ``AND``, ``OR``, ``NOT``. En minúsculas se
   buscan como palabras.

Resumen
-------

OpenAlex no devuelve el resumen como texto corrido, sino como
``abstract_inverted_index``: un diccionario de palabra → lista de posiciones.
Una palabra puede aparecer en **varias** posiciones, así que hay que colocarlas
todas por índice y unir. Ordenar por la primera aparición de cada palabra da un
texto distinto y mal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from ..protocolo import Protocolo
from . import NR, entero_o_nr, limpiar_termino, lista_o_nr, registro_en_blanco, texto_o_nr

__all__ = [
    "BASE",
    "NOMBRE",
    "POR_PAGINA_MAXIMO",
    "CURSOR_INICIAL",
    "ResultadoBusqueda",
    "construir_ecuaciones",
    "construir_filtro",
    "construir_url",
    "reconstruir_resumen",
    "normalizar_obra",
    "buscar",
]

NOMBRE = "OpenAlex"
BASE = "https://api.openalex.org/works"

POR_PAGINA_MAXIMO = 200
CURSOR_INICIAL = "*"

#: Caracteres que se dejan sin codificar dentro del valor de ``filter``.
#: La coma separa filtros, los dos puntos separan nombre y valor, y la barra
#: vertical es el OR. Todo lo demás se codifica, incluidos los espacios (%20)
#: y las comillas (%22).
_SEGUROS_FILTRO = ":,|"


# ---------------------------------------------------------------------------
# Construcción de consultas
# ---------------------------------------------------------------------------


def construir_ecuaciones(protocolo: Protocolo) -> list[str]:
    """Despliega el protocolo en una lista de ecuaciones literales.

    Una por cada par (término del bloque eje × término de ``consulta.cruce``).
    Si el protocolo no trae ``consulta``, no hay nada que buscar.
    """
    if protocolo.consulta is None:
        return []

    terminos_eje = [limpiar_termino(t) for t in protocolo.terminos_de(protocolo.consulta.eje)]
    terminos_cruce = [limpiar_termino(t) for t in protocolo.consulta.cruce]

    terminos_eje = [t for t in terminos_eje if t]
    terminos_cruce = [t for t in terminos_cruce if t]

    if not terminos_cruce:
        # Sin cruce, una ecuación por término del eje.
        return [f'"{eje}"' for eje in terminos_eje]

    return [
        f'"{eje}" AND "{cruce}"'
        for eje in terminos_eje
        for cruce in terminos_cruce
    ]


def construir_filtro(ecuacion: str, protocolo: Protocolo) -> str:
    """Arma el valor de ``filter=`` **sin codificar**, tal como lo lee OpenAlex.

    Es la cadena que se guarda en la bitácora como ecuación literal ampliada:
    incluye la ventana temporal, los idiomas y los tipos, que son parte de la
    búsqueda aunque no se vean en la ecuación.
    """
    partes = [f"title_and_abstract.search:{ecuacion}"]

    inicio, fin = protocolo.ventana
    if inicio:
        partes.append(f"from_publication_date:{inicio}-01-01")
    if fin:
        partes.append(f"to_publication_date:{fin}-12-31")

    if protocolo.idiomas:
        # Códigos ISO separados por barra vertical: language:es|en.
        # Nunca language:languages/en, que es la forma de entidad y falla.
        partes.append("language:" + "|".join(protocolo.idiomas))

    if protocolo.tipos:
        # type:article|review. Nunca type:types/article.
        partes.append("type:" + "|".join(protocolo.tipos))

    return ",".join(partes)


def construir_url(
    ecuacion: str,
    protocolo: Protocolo,
    correo: str,
    cursor: str = CURSOR_INICIAL,
    por_pagina: int = POR_PAGINA_MAXIMO,
) -> str:
    """Arma la URL completa y literal de una consulta.

    Se construye a mano, carácter a carácter, en vez de dejársela a `requests`:
    hace falta que los espacios del filtro queden como ``%20`` y no como ``+``.

    El `correo` va en ``mailto`` para entrar en la cola educada de OpenAlex,
    que responde más rápido y con menos cortes que la anónima.
    """
    por_pagina = max(1, min(int(por_pagina), POR_PAGINA_MAXIMO))
    filtro = construir_filtro(ecuacion, protocolo)

    parametros = [
        ("filter", quote(filtro, safe=_SEGUROS_FILTRO)),
        ("per-page", str(por_pagina)),
        ("cursor", quote(cursor, safe="*")),
    ]
    if correo:
        parametros.append(("mailto", quote(correo, safe="@")))

    cadena = "&".join(f"{clave}={valor}" for clave, valor in parametros)
    return f"{BASE}?{cadena}"


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------


def reconstruir_resumen(indice: Any) -> str:
    """Rehace el resumen desde ``abstract_inverted_index``.

    El índice es ``{palabra: [posiciones]}`` y una palabra puede aparecer en
    **varias** posiciones. Hay que colocar cada aparición en su hueco y unir en
    orden de posición; ordenar las palabras por su primera aparición produce un
    texto distinto y mal.

    Devuelve ``"NR"`` si no hay índice: un resumen ausente se marca, no se
    inventa (AGENTS.md, regla 2).
    """
    if not isinstance(indice, dict) or not indice:
        return NR

    posiciones: dict[int, str] = {}
    for palabra, indices in indice.items():
        if not isinstance(indices, (list, tuple)):
            continue
        for posicion in indices:
            if isinstance(posicion, bool) or not isinstance(posicion, int):
                continue
            posiciones[posicion] = str(palabra)

    if not posiciones:
        return NR

    return " ".join(posiciones[clave] for clave in sorted(posiciones))


def _doi_limpio(valor: Any) -> str:
    """Deja el DOI desnudo: sin el prefijo de resolución y en minúsculas."""
    texto = texto_o_nr(valor)
    if texto == NR:
        return NR
    texto = texto.strip().lower()
    for prefijo in ("https://doi.org/", "http://doi.org/", "doi:"):
        if texto.startswith(prefijo):
            texto = texto[len(prefijo) :]
    return texto or NR


def _sin_nulos(valor: Any, *claves: str) -> Any:
    """Recorre un camino de claves tolerando nulos por el camino."""
    actual = valor
    for clave in claves:
        if not isinstance(actual, dict):
            return None
        actual = actual.get(clave)
    return actual


def normalizar_obra(obra: Any) -> dict[str, Any]:
    """Convierte una obra de OpenAlex al registro común de Tatewari."""
    registro = registro_en_blanco()
    if not isinstance(obra, dict):
        return registro

    registro["doi"] = _doi_limpio(obra.get("doi"))
    registro["titulo"] = texto_o_nr(obra.get("title") or obra.get("display_name"))
    registro["anio"] = entero_o_nr(obra.get("publication_year"))
    registro["idioma"] = texto_o_nr(obra.get("language"))
    registro["revista"] = texto_o_nr(
        _sin_nulos(obra, "primary_location", "source", "display_name")
    )

    autorias = obra.get("authorships") or []
    nombres = []
    for autoria in autorias:
        nombre = _sin_nulos(autoria, "author", "display_name")
        if nombre:
            nombres.append(nombre)
    registro["autores"] = lista_o_nr(nombres)

    registro["resumen"] = reconstruir_resumen(obra.get("abstract_inverted_index"))
    registro["tipo"] = texto_o_nr(obra.get("type"))
    registro["citas"] = entero_o_nr(obra.get("cited_by_count"))

    oa_url = (
        _sin_nulos(obra, "best_oa_location", "pdf_url")
        or _sin_nulos(obra, "best_oa_location", "landing_page_url")
        or _sin_nulos(obra, "open_access", "oa_url")
    )
    registro["oa_url"] = texto_o_nr(oa_url)

    return registro


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------


@dataclass
class ResultadoBusqueda:
    """Lo que devuelve una ecuación: registros, rastro y cuentas."""

    ecuacion: str
    registros: list[dict[str, Any]] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    paginas: int = 0
    total_declarado: int | str = NR

    @property
    def url_literal(self) -> str:
        """La primera URL, la que se guarda en la bitácora (AGENTS.md, regla 3)."""
        return self.urls[0] if self.urls else NR


def buscar(
    ecuacion: str,
    protocolo: Protocolo,
    cliente: Any,
    correo: str,
    max_paginas: int = 5,
    por_pagina: int = POR_PAGINA_MAXIMO,
) -> ResultadoBusqueda:
    """Lanza una ecuación contra OpenAlex y pagina por cursor.

    El cursor arranca en ``*`` y se continúa con ``meta.next_cursor`` hasta que
    venga vacío o se llegue al tope de páginas. `cliente` es cualquier objeto
    con `obtener_json(url)`, para que las pruebas lo sustituyan sin red.
    """
    resultado = ResultadoBusqueda(ecuacion=ecuacion)
    cursor: str | None = CURSOR_INICIAL

    for _ in range(max(1, int(max_paginas))):
        if not cursor:
            break

        url = construir_url(
            ecuacion, protocolo, correo, cursor=cursor, por_pagina=por_pagina
        )
        resultado.urls.append(url)

        datos = cliente.obtener_json(url)
        resultado.paginas += 1

        obras = datos.get("results") if isinstance(datos, dict) else None
        obras = obras or []
        resultado.registros.extend(normalizar_obra(obra) for obra in obras)

        meta = datos.get("meta") if isinstance(datos, dict) else None
        meta = meta if isinstance(meta, dict) else {}
        if resultado.total_declarado == NR:
            resultado.total_declarado = entero_o_nr(meta.get("count"))

        cursor = meta.get("next_cursor")
        if not obras:
            break

    return resultado
