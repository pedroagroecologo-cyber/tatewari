"""Registro de habilidades: las herramientas con nombre que usa el orquestador.

Tatewari no tenía un sistema de skills antes de Knowledge Studio: sus capacidades
eran órdenes de la línea de órdenes que llamaban directamente a funciones. Este
registro es la solución mínima compatible con eso. No es un segundo mecanismo en
paralelo a nada: es una tabla de nombre → función, con dos marcas que el
orquestador respeta:

``usa_modelo``
    La habilidad habla con Ollama. Si no hay modelo, el orquestador la salta y lo
    dice, en vez de fallar todo el proceso.
``escribe``
    La habilidad modifica archivos. Solo puede hacerlo a través de una `Jaula`.

Las habilidades deterministas (ingesta, extracción, búsqueda, validación) hacen el
trabajo con archivos. El modelo solo interviene donde hace falta interpretar.

Las habilidades de la capa ZEA MAYZ se registran desde su propio paquete
(`tatewari.zea_mayz`), al importarlo: el núcleo no depende de ella.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import analisis, extraccion, ingesta, normalizacion, validacion, vinculos
from .vault import Vault

__all__ = ["Habilidad", "registrar", "habilidad", "habilidades", "ErrorHabilidad"]


class ErrorHabilidad(Exception):
    """Se pidió una habilidad que no existe."""


@dataclass(frozen=True)
class Habilidad:
    nombre: str
    descripcion: str
    funcion: Callable[..., Any]
    usa_modelo: bool = False
    escribe: bool = False


_REGISTRO: dict[str, Habilidad] = {}


def registrar(
    nombre: str, descripcion: str, funcion: Callable[..., Any],
    usa_modelo: bool = False, escribe: bool = False,
) -> Habilidad:
    """Añade una habilidad al registro. Registrar dos veces el mismo nombre falla."""
    if nombre in _REGISTRO and _REGISTRO[nombre].funcion is not funcion:
        raise ErrorHabilidad(f"Ya hay una habilidad llamada «{nombre}».")
    _REGISTRO[nombre] = Habilidad(nombre, descripcion, funcion, usa_modelo, escribe)
    return _REGISTRO[nombre]


def habilidad(nombre: str) -> Habilidad:
    try:
        return _REGISTRO[nombre]
    except KeyError as error:
        disponibles = ", ".join(sorted(_REGISTRO))
        raise ErrorHabilidad(f"No existe la habilidad «{nombre}». Hay: {disponibles}.") from error


def habilidades() -> list[Habilidad]:
    return sorted(_REGISTRO.values(), key=lambda h: h.nombre)


def _extraer_y_normalizar(aceptado: ingesta.Ingesta):
    return normalizacion.normalizar_documento(extraccion.extraer(aceptado))


registrar(
    "document_ingest",
    "Detecta el tipo del documento (por extensión y por contenido), comprueba que se "
    "pueda leer y calcula su huella.",
    ingesta.ingerir,
)
registrar(
    "document_extract",
    "Extrae el texto por página, diapositiva o sección, con su ubicación, y lo normaliza.",
    _extraer_y_normalizar,
)
registrar(
    "knowledge_extract",
    "Pasa los trozos por el modelo local y valida los objetos contra el esquema y las citas.",
    analisis.analizar_documento,
    usa_modelo=True,
)
registrar(
    "knowledge_link",
    "Decide crear, actualizar o proponer cada objeto frente al Vault; detecta "
    "duplicados y conflictos.",
    vinculos.planificar,
)
registrar(
    "obsidian_create_note",
    "Crea una nota nueva en DRAFT o REVIEW. Nunca pisa un archivo existente.",
    Vault.crear_nota,
    escribe=True,
)
registrar(
    "obsidian_update_note",
    "Funde información nueva en una nota de Tatewari que siga en DRAFT o REVIEW y "
    "nadie haya editado a mano.",
    Vault.actualizar_nota,
    escribe=True,
)
registrar(
    "obsidian_search",
    "Busca notas por nombre, alias o contenido.",
    Vault.buscar_texto,
)
registrar(
    "obsidian_validate",
    "Revisa el Vault: estados, fuentes, duplicados, conflictos y enlaces pendientes.",
    validacion.validar_vault,
)


def _reporte(*args: Any, **kwargs: Any) -> Any:
    from .reporte import reporte_vault

    return reporte_vault(*args, **kwargs)


registrar(
    "knowledge_report",
    "Redacta el reporte legible de un procesamiento o del Vault entero.",
    _reporte,
    escribe=True,
)
