"""Interfaz de línea de órdenes de Tatewari.

Por ahora solo dos subórdenes:

    python -m tatewari version
    python -m tatewari protocolo validar protocolos/humedales.json

La cosecha, la deduplicación, el cribado y la exportación llegan en encargos
posteriores; cada una añadirá su propia subórden aquí.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .protocolo import ErrorProtocolo, cargar_protocolo

__all__ = ["main", "construir_parser"]

# Códigos de salida, para que un script pueda distinguir qué falló.
SALIDA_OK = 0
SALIDA_PROTOCOLO_INVALIDO = 1
SALIDA_ARCHIVO_NO_ENCONTRADO = 2


class _FormateadorEspanol(argparse.HelpFormatter):
    """Traduce al español el encabezado de uso que argparse escribe en inglés."""

    def add_usage(self, usage, actions, groups, prefix=None):  # noqa: D102
        super().add_usage(usage, actions, groups, prefix="Uso: ")


def _preparar_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Pone en español los títulos de sección y la ayuda de `-h`."""
    parser._positionals.title = "Argumentos"
    parser._optionals.title = "Opciones"
    parser.add_argument(
        "-h",
        "--help",
        action="help",
        help="Muestra esta ayuda y termina.",
    )
    return parser


def construir_parser() -> argparse.ArgumentParser:
    """Arma el analizador de argumentos completo."""
    parser = argparse.ArgumentParser(
        prog="tatewari",
        description=(
            "Tatewari: agente local de revisión sistemática de literatura "
            "científica (PRISMA 2020). Se ejecuta por completo en esta máquina."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(parser)
    parser.add_argument(
        "--version",
        action="version",
        version=f"Tatewari {__version__}",
        help="Muestra la versión y termina.",
    )

    subordenes = parser.add_subparsers(dest="orden", metavar="ORDEN")

    version = subordenes.add_parser(
        "version",
        help="Muestra la versión de Tatewari.",
        description="Muestra la versión de Tatewari.",
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(version)
    version.set_defaults(funcion=_orden_version)

    protocolo = subordenes.add_parser(
        "protocolo",
        help="Trabaja con protocolos de búsqueda.",
        description="Trabaja con protocolos de búsqueda en JSON.",
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(protocolo)
    # Sin acción, "protocolo" enseña su propia ayuda en vez de la general.
    protocolo.set_defaults(funcion=_orden_ayuda, parser_propio=protocolo)
    acciones_protocolo = protocolo.add_subparsers(dest="accion", metavar="ACCIÓN")

    validar = acciones_protocolo.add_parser(
        "validar",
        help="Valida un protocolo y muestra su resumen.",
        description=(
            "Valida un protocolo de búsqueda contra el esquema y muestra un "
            "resumen legible. No sale a la red."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(validar)
    validar.add_argument(
        "ruta",
        metavar="RUTA",
        type=Path,
        help="Ruta al archivo JSON del protocolo.",
    )
    validar.set_defaults(funcion=_orden_protocolo_validar)

    return parser


def _orden_ayuda(args: argparse.Namespace) -> int:
    args.parser_propio.print_help()
    return SALIDA_OK


def _orden_version(args: argparse.Namespace) -> int:
    print(f"Tatewari {__version__}")
    return SALIDA_OK


def _orden_protocolo_validar(args: argparse.Namespace) -> int:
    try:
        protocolo = cargar_protocolo(args.ruta)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return SALIDA_ARCHIVO_NO_ENCONTRADO
    except ErrorProtocolo as error:
        print(error, file=sys.stderr)
        return SALIDA_PROTOCOLO_INVALIDO

    print(f"Protocolo válido: {args.ruta}")
    print()
    print(protocolo.resumen())
    return SALIDA_OK


def _forzar_utf8() -> None:
    """Escribe en UTF-8 aunque la consola de Windows diga otra cosa.

    Sin esto, redirigir la salida a un archivo en Windows usa la página de
    códigos local y rompe los acentos. `errors="replace"` evita que un carácter
    raro tumbe el programa entero.
    """
    for flujo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(flujo, "reconfigure", None)
        if reconfigurar is None:
            continue
        try:
            reconfigurar(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada. Devuelve el código de salida."""
    _forzar_utf8()
    parser = construir_parser()
    args = parser.parse_args(argv)

    if getattr(args, "funcion", None) is None:
        parser.print_help()
        return SALIDA_OK

    return args.funcion(args)
