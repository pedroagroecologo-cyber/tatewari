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
from .config import ErrorConfig, cargar_config
from .cosecha import FUENTES, LOTE_POR_DEFECTO, PAGINAS_POR_DEFECTO, Cosecha, ErrorCosecha
from .http import ClienteHttp
from .protocolo import ErrorProtocolo, cargar_protocolo

__all__ = ["main", "construir_parser"]

# Códigos de salida, para que un script pueda distinguir qué falló.
SALIDA_OK = 0
SALIDA_PROTOCOLO_INVALIDO = 1
SALIDA_ARCHIVO_NO_ENCONTRADO = 2
SALIDA_CONFIGURACION = 3
SALIDA_COSECHA = 4


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

    cosechar = subordenes.add_parser(
        "cosechar",
        help="Cosecha registros en las bases bibliográficas.",
        description=(
            "Cosecha registros para una revisión. Es reanudable: cada llamada "
            "procesa un lote de ecuaciones y dice cuántas faltan; volver a "
            "lanzarla continúa donde se quedó. Con --seco o --fixture no toca "
            "la red."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(cosechar)
    cosechar.add_argument(
        "revision",
        metavar="REVISIÓN",
        help="Nombre de la revisión; da nombre a la carpeta de salida.",
    )
    cosechar.add_argument(
        "--protocolo",
        metavar="RUTA",
        type=Path,
        required=True,
        help="Ruta al protocolo de búsqueda en JSON.",
    )
    cosechar.add_argument(
        "--seco",
        action="store_true",
        help=(
            "No toca la red: solo imprime las ecuaciones con su URL literal, "
            "para pegarlas en el navegador y comprobarlas antes de gastar red."
        ),
    )
    cosechar.add_argument(
        "--fixture",
        metavar="RUTA",
        type=Path,
        default=None,
        help=(
            "No toca la red: sirve un archivo local como respuesta. El lote es "
            "de una sola ecuación salvo que se indique --max-consultas."
        ),
    )
    cosechar.add_argument(
        "--max-consultas",
        metavar="N",
        type=int,
        default=None,
        dest="max_consultas",
        help=(
            f"Ecuaciones por lote (por defecto {LOTE_POR_DEFECTO}; con --seco, "
            f"todas)."
        ),
    )
    cosechar.add_argument(
        "--max-paginas",
        metavar="N",
        type=int,
        default=PAGINAS_POR_DEFECTO,
        dest="max_paginas",
        help=f"Páginas por ecuación (por defecto {PAGINAS_POR_DEFECTO}).",
    )
    cosechar.add_argument(
        "--reintentar",
        action="store_true",
        help=(
            "Vuelve a lanzar las ecuaciones que fallaron, salvo las que ya "
            "agotaron sus intentos."
        ),
    )
    cosechar.add_argument(
        "--fuente",
        choices=sorted(FUENTES),
        default="openalex",
        help="Base bibliográfica (por defecto openalex).",
    )
    cosechar.set_defaults(funcion=_orden_cosechar)

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


def _orden_cosechar(args: argparse.Namespace) -> int:
    try:
        protocolo = cargar_protocolo(args.protocolo)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return SALIDA_ARCHIVO_NO_ENCONTRADO
    except ErrorProtocolo as error:
        print(error, file=sys.stderr)
        return SALIDA_PROTOCOLO_INVALIDO

    try:
        config = cargar_config()
    except ErrorConfig as error:
        print(error, file=sys.stderr)
        return SALIDA_CONFIGURACION

    sin_red = args.seco or args.fixture is not None
    if not sin_red and not config.tiene_mailto:
        print(
            "Falta un correo de contacto en TATEWARI_MAILTO. OpenAlex y Crossref "
            "lo usan para darte respuestas más rápidas y Unpaywall lo exige. "
            "Copia .env.example a .env y pon ahí tu correo, o usa --seco para "
            "ver las ecuaciones sin salir a la red.",
            file=sys.stderr,
        )
        return SALIDA_CONFIGURACION

    cliente = None if sin_red else ClienteHttp()

    try:
        cosecha = Cosecha(
            revision=args.revision,
            protocolo=protocolo,
            config=config,
            fuente=args.fuente,
            cliente=cliente,
        )

        if args.seco:
            resumen = cosecha.plan_seco(max_consultas=args.max_consultas)
            print(resumen.resumen())
            print()
            for ecuacion in resumen.ecuaciones:
                print(f"[{ecuacion.numero:>3}] {ecuacion.texto}")
                print(f"      {ecuacion.url}")
            return SALIDA_OK

        # En modo fixture el archivo se sirve una sola vez, así que el lote es
        # de una ecuación salvo que se pida otra cosa a propósito.
        max_consultas = args.max_consultas
        if args.fixture is not None and max_consultas is None:
            max_consultas = 1

        resumen = cosecha.ejecutar(
            max_consultas=max_consultas,
            max_paginas=args.max_paginas,
            fixture=args.fixture,
            reintentar=args.reintentar,
        )
    except ErrorCosecha as error:
        print(error, file=sys.stderr)
        return SALIDA_COSECHA
    except ErrorConfig as error:
        print(error, file=sys.stderr)
        return SALIDA_CONFIGURACION

    print(resumen.resumen())
    print()
    print(f"Bitácora  : {cosecha.ruta_bitacora}")
    print(f"Registros : {cosecha.ruta_registros}")
    print(f"Estado    : {cosecha.ruta_estado}")

    if resumen.incidencias:
        print()
        print("Incidencias (quedan anotadas en la bitácora):", file=sys.stderr)
        for incidencia in resumen.incidencias:
            print(f"  - {incidencia}", file=sys.stderr)

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
