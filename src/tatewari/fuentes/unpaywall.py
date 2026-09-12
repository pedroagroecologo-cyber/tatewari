"""Unpaywall: la mejor ubicación en acceso abierto de un DOI.

Documentación: https://unpaywall.org/products/api

Unpaywall **exige** un correo de contacto en cada petición. Si no está
configurado, aquí se falla con un mensaje claro en vez de mandar una petición
que el servicio va a rechazar.

Qué pasa cuando no hay versión abierta
--------------------------------------

Se marca el registro como ``requiere_credencial_institucional`` y se sigue.
**No se intenta ninguna otra vía**: ni Sci-Hub, ni raspar la web de la
editorial, ni rodear el muro de pago (AGENTS.md, regla 5). El texto se pide por
la biblioteca de la institución, que para eso está.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from ..config import ErrorConfig
from . import NR, texto_o_nr

__all__ = [
    "BASE",
    "NOMBRE",
    "ESTADO_ABIERTO",
    "ESTADO_CERRADO",
    "ESTADO_DESCONOCIDO",
    "Ubicacion",
    "construir_url",
    "normalizar_respuesta",
    "resolver",
]

NOMBRE = "Unpaywall"
BASE = "https://api.unpaywall.org/v2"

ESTADO_ABIERTO = "abierto"
ESTADO_CERRADO = "requiere_credencial_institucional"
ESTADO_DESCONOCIDO = "desconocido"

NOTA_CERRADO = (
    "Sin versión en acceso abierto. Solicitar por la biblioteca institucional. "
    "No se intenta ninguna otra vía (AGENTS.md, regla 5)."
)


@dataclass(frozen=True)
class Ubicacion:
    """Dónde está el texto completo de un DOI, si es que está."""

    doi: str
    estado: str
    oa_url: str = NR
    version: str = NR
    licencia: str = NR
    repositorio: str = NR
    nota: str = NR

    @property
    def esta_abierto(self) -> bool:
        return self.estado == ESTADO_ABIERTO


def construir_url(doi: str, correo: str) -> str:
    """Arma la URL literal de la consulta a Unpaywall.

    Lanza `ErrorConfig` si no hay correo: Unpaywall lo exige y una petición sin
    él es una petición que ya sabemos que va a fallar.
    """
    doi_limpio = texto_o_nr(doi)
    if doi_limpio == NR:
        raise ErrorConfig(
            "No se puede consultar Unpaywall sin DOI. El registro se queda con "
            'el DOI en "NR" y sin resolver.'
        )

    if not correo or "@" not in correo:
        raise ErrorConfig(
            "Unpaywall exige un correo de contacto y TATEWARI_MAILTO está vacío "
            "o no es válido. Copia .env.example a .env y pon ahí tu correo; sin "
            "él, Unpaywall rechaza la petición."
        )

    return (
        f"{BASE}/{quote(doi_limpio, safe='/')}"
        f"?email={quote(correo, safe='@')}"
    )


def normalizar_respuesta(doi: str, datos: Any) -> Ubicacion:
    """Convierte la respuesta de Unpaywall en una `Ubicacion`."""
    if not isinstance(datos, dict):
        return Ubicacion(
            doi=doi,
            estado=ESTADO_DESCONOCIDO,
            nota="Unpaywall devolvió algo que no es un objeto JSON.",
        )

    mejor = datos.get("best_oa_location")
    if not isinstance(mejor, dict) or not mejor:
        return Ubicacion(doi=doi, estado=ESTADO_CERRADO, nota=NOTA_CERRADO)

    url = texto_o_nr(mejor.get("url_for_pdf") or mejor.get("url"))
    if url == NR:
        return Ubicacion(doi=doi, estado=ESTADO_CERRADO, nota=NOTA_CERRADO)

    return Ubicacion(
        doi=doi,
        estado=ESTADO_ABIERTO,
        oa_url=url,
        version=texto_o_nr(mejor.get("version")),
        licencia=texto_o_nr(mejor.get("license")),
        repositorio=texto_o_nr(
            mejor.get("repository_institution") or mejor.get("host_type")
        ),
    )


def resolver(doi: str, cliente: Any, correo: str) -> Ubicacion:
    """Resuelve un DOI contra Unpaywall.

    `cliente` es cualquier objeto con `obtener_json(url)`. Si Unpaywall no
    conoce el DOI (404), no es un fallo de la cosecha: se devuelve una
    `Ubicacion` desconocida y se sigue.
    """
    from ..http import ErrorHttpCliente  # import local: evita un ciclo al cargar

    url = construir_url(doi, correo)
    try:
        datos = cliente.obtener_json(url)
    except ErrorHttpCliente as error:
        return Ubicacion(
            doi=doi,
            estado=ESTADO_DESCONOCIDO,
            nota=f"Unpaywall no resolvió el DOI ({error.estado}).",
        )
    return normalizar_respuesta(doi, datos)
