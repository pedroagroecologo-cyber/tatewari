"""Interfaz de línea de órdenes de Tatewari.

Las subórdenes disponibles:

    python -m tatewari version
    python -m tatewari protocolo validar protocolos/humedales.json
    python -m tatewari cosechar demo --protocolo protocolos/humedales.json
    python -m tatewari cribar demo
    python -m tatewari cribar demo --modelo-local
    python -m tatewari pendientes demo --modo auditoria
    python -m tatewari decidir demo R0007 --decision incluir --motivo "..."
    python -m tatewari ordenar demo --pregunta "remoción de DQO en humedal"
    python -m tatewari similares demo R0007
    python -m tatewari casi-duplicados demo
    python -m tatewari texto-completo demo
    python -m tatewari exportar demo
    python -m tatewari estado demo
    python -m tatewari biblioteca importar

Y las de Knowledge Studio y ZEA MAYZ, definidas en `cli_conocimiento`:

    python -m tatewari conocimiento procesar apuntes.pdf
    python -m tatewari pedir "procesa este documento apuntes.pdf"
    python -m tatewari zea-mayz divulgar --tema "suelo"

El recorrido completo, de principio a fin, está en el README.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .auditoria import (
    MUESTRA_POR_DEFECTO,
    NOMBRE_AUDITORIA,
    ErrorAuditoria,
    muestra_aleatoria,
    registrar_auditoria,
)
from .biblioteca import (
    ErrorBiblioteca,
    abrir as abrir_biblioteca,
    reconstruir as reconstruir_biblioteca,
)
from .config import ErrorConfig, cargar_config
from .cosecha import FUENTES, LOTE_POR_DEFECTO, PAGINAS_POR_DEFECTO, Cosecha, ErrorCosecha
from .cribado import (
    DECISIONES,
    Cribado,
    DecisionManual,
    ErrorCribado,
    anadir_decisiones,
    protocolo_registrado,
)
from .cli_conocimiento import anadir_ordenes
from .interfaz.orden import anadir_orden as anadir_orden_interfaz
from .cribado_modelo import LIMITE_RESUMEN, cribar_dudosos, recortar
from .fuentes import NR
from .exportar import exportar
from .texto_completo import (
    NOMBRE_TEXTO_COMPLETO,
    aplicar_a_registros,
    guardar_resueltos,
    leer_resueltos,
    resolver_incluidos,
)
from .embeddings import (
    LOTE_POR_DEFECTO as LOTE_EMBED,
    MODELO_EMBED_POR_DEFECTO,
    NOMBRE_VECTORES,
    UMBRAL_CASI_DUPLICADO,
    Almacen,
    ClienteEmbeddings,
    ErrorEmbeddings,
    casi_duplicados,
    mas_parecidos,
    ordenar_por_parecido,
    vectorizar,
)
from .http import ClienteHttp, ErrorHttp
from .modelo import ClienteOllama, ErrorOllama
from .protocolo import ErrorProtocolo, cargar_protocolo
from .descargas import descargar_incluidos, nueva_sesion as nueva_sesion_descargas
from .explorar import MAXIMO as MAXIMO_EXPLORAR, explorar as explorar_por_significado
from .tesauro import FUENTES as FUENTES_TESAURO, buscar as buscar_en_tesauros, es_sigla, terminos_sugeridos

__all__ = ["main", "construir_parser"]

# Códigos de salida, para que un script pueda distinguir qué falló.
SALIDA_OK = 0
SALIDA_PROTOCOLO_INVALIDO = 1
SALIDA_ARCHIVO_NO_ENCONTRADO = 2
SALIDA_CONFIGURACION = 3
SALIDA_COSECHA = 4
SALIDA_CRIBADO = 5
SALIDA_MODELO = 6
SALIDA_EMBEDDINGS = 7


class _FormateadorEspanol(argparse.HelpFormatter):
    """Traduce al español el encabezado de uso que argparse escribe en inglés."""

    def add_usage(self, usage, actions, groups, prefix=None):
        """Pone «Uso: » donde argparse pondría «usage: », y solo ahí.

        Ojo con el `prefix is None`, que no es adorno: `add_subparsers` llama a
        este mismo método con el prefijo **vacío** para averiguar el `prog` de
        cada subórden. Si se le fuerza «Uso: » también en esa llamada, el `prog`
        de cada subórden acaba siendo «Uso: tatewari» y su ayuda encabeza con un
        «Uso: Uso: tatewari cribar …» que además contamina los mensajes de error.
        """
        if prefix is None:
            prefix = "Uso: "
        super().add_usage(usage, actions, groups, prefix=prefix)


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

    cribar = subordenes.add_parser(
        "cribar",
        help="Criba los registros cosechados contra las reglas del protocolo.",
        description=(
            "Deduplica los registros de una revisión y los criba contra las "
            "reglas del protocolo. El filtro es determinista y no toca la red: "
            "la misma entrada da siempre la misma salida. Con --modelo-local, "
            "además pasa los dudosos por el Ollama de esta máquina. Escribe "
            "cribado.csv y prisma.txt en la carpeta de la revisión."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(cribar)
    cribar.add_argument(
        "revision",
        metavar="REVISIÓN",
        help="Nombre de la revisión que se va a cribar.",
    )
    cribar.add_argument(
        "--protocolo",
        metavar="RUTA",
        type=Path,
        default=None,
        help=(
            "Ruta al protocolo. Si se omite, se usa el que anotó la cosecha en "
            "estado.json."
        ),
    )
    cribar.add_argument(
        "--modelo-local",
        action="store_true",
        dest="modelo_local",
        help=(
            "Pasa por el modelo local de Ollama los registros que el filtro "
            "dejó en «dudoso». Tarda segundos por registro."
        ),
    )
    cribar.add_argument(
        "--modelo",
        metavar="NOMBRE",
        default=None,
        help=(
            "Fuerza un modelo de Ollama (por ejemplo llama3.2:3b). Si se omite, "
            "se elige el que mejor entre en esta tarjeta."
        ),
    )
    cribar.set_defaults(funcion=_orden_cribar)

    pendientes = subordenes.add_parser(
        "pendientes",
        help="Lista los registros que esperan una decisión humana.",
        description=(
            "Lista registros para revisión humana, con su título, año, resumen "
            "recortado y el motivo del filtro. Con --modo auditoria saca una "
            "muestra aleatoria de las exclusiones y la deja registrada."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(pendientes)
    pendientes.add_argument(
        "revision",
        metavar="REVISIÓN",
        help="Nombre de la revisión.",
    )
    pendientes.add_argument(
        "--modo",
        choices=("dudoso", "auditoria", "incluir"),
        default="dudoso",
        help=(
            "dudoso: los que nadie ha decidido (por defecto). auditoria: muestra "
            "aleatoria de las exclusiones. incluir: los que van a entrar."
        ),
    )
    pendientes.add_argument(
        "--cuantos",
        metavar="N",
        type=int,
        default=None,
        help=(
            f"Cuántos mostrar. En --modo auditoria, {MUESTRA_POR_DEFECTO} por "
            f"defecto; en los demás, todos."
        ),
    )
    pendientes.add_argument(
        "--semilla",
        metavar="N",
        type=int,
        default=None,
        help=(
            "Semilla de la muestra de auditoría, para reconstruir una muestra "
            "anterior. Si se omite, se genera una y queda registrada."
        ),
    )
    pendientes.add_argument(
        "--registrar",
        action="store_true",
        help=(
            "Solo con --modo auditoria: apunta la ronda en auditoria.json con su "
            "semilla, para que quede registrada (AGENTS.md, regla 4). Sin esta "
            "opción, «pendientes» no escribe nada."
        ),
    )
    pendientes.add_argument(
        "--protocolo",
        metavar="RUTA",
        type=Path,
        default=None,
        help="Ruta al protocolo. Si se omite, el que anotó la cosecha.",
    )
    pendientes.set_defaults(funcion=_orden_pendientes)

    decidir = subordenes.add_parser(
        "decidir",
        help="Registra una decisión humana sobre un registro.",
        description=(
            "Registra en decisiones.json lo que una persona decidió sobre un "
            "registro. La decisión sobreescribe a la del filtro sin borrarla, y "
            "queda con su motivo, su autor y su fecha."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(decidir)
    decidir.add_argument("revision", metavar="REVISIÓN", help="Nombre de la revisión.")
    decidir.add_argument(
        "identificador",
        metavar="ID",
        help="Identificador del registro, como R0007.",
    )
    decidir.add_argument(
        "--decision",
        choices=DECISIONES,
        required=True,
        help="La decisión que se registra.",
    )
    decidir.add_argument(
        "--motivo",
        metavar="TEXTO",
        required=True,
        help="Por qué. Obligatorio: una decisión sin motivo no es auditable.",
    )
    decidir.add_argument(
        "--autor",
        metavar="NOMBRE",
        default=None,
        help=(
            "Quién decide. Si se omite, el usuario de esta máquina. Nunca se "
            "inventa un nombre."
        ),
    )
    decidir.add_argument(
        "--protocolo",
        metavar="RUTA",
        type=Path,
        default=None,
        help="Ruta al protocolo. Si se omite, el que anotó la cosecha.",
    )
    decidir.set_defaults(funcion=_orden_decidir)

    def _con_embeddings(orden: argparse.ArgumentParser) -> argparse.ArgumentParser:
        """Las opciones que comparten las tres órdenes de búsqueda por parecido."""
        orden.add_argument(
            "revision", metavar="REVISIÓN", help="Nombre de la revisión."
        )
        orden.add_argument(
            "--modelo-embed",
            metavar="NOMBRE",
            default=MODELO_EMBED_POR_DEFECTO,
            dest="modelo_embed",
            help=(
                f"Modelo de embeddings de Ollama (por defecto "
                f"{MODELO_EMBED_POR_DEFECTO}). Cambiarlo invalida la caché: los "
                f"vectores de dos modelos no son comparables."
            ),
        )
        orden.add_argument(
            "--lote",
            metavar="N",
            type=int,
            default=LOTE_EMBED,
            help=f"Registros por petición (por defecto {LOTE_EMBED}).",
        )
        orden.add_argument(
            "--protocolo",
            metavar="RUTA",
            type=Path,
            default=None,
            help="Ruta al protocolo. Si se omite, el que anotó la cosecha.",
        )
        return orden

    ordenar = subordenes.add_parser(
        "ordenar",
        help="Ordena los registros por cercanía a la pregunta de investigación.",
        description=(
            "Ordena los registros de una revisión por similitud coseno con una "
            "pregunta, para leer primero lo más cercano cuando el cribado deja "
            "cien dudosos. Es una ayuda de lectura: NO cambia ninguna decisión "
            "del cribado."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(ordenar)
    _con_embeddings(ordenar)
    ordenar.add_argument(
        "--pregunta",
        metavar="TEXTO",
        required=True,
        help="La pregunta de investigación con la que se compara.",
    )
    ordenar.add_argument(
        "--modo",
        choices=("todos", "dudoso", "incluir", "excluir"),
        default="todos",
        help="A qué registros mirar (por defecto todos).",
    )
    ordenar.add_argument(
        "--cuantos",
        metavar="N",
        type=int,
        default=20,
        help="Cuántos mostrar (por defecto 20; 0 para todos).",
    )
    ordenar.set_defaults(funcion=_orden_ordenar)

    similares = subordenes.add_parser(
        "similares",
        help="Los registros más parecidos a uno dado.",
        description=(
            "Muestra los registros más parecidos a uno dado, por similitud "
            "coseno. Es una ayuda de lectura: NO cambia ninguna decisión del "
            "cribado."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(similares)
    _con_embeddings(similares)
    similares.add_argument(
        "identificador",
        metavar="ID",
        help="Identificador del registro de referencia, como R0007.",
    )
    similares.add_argument(
        "--cuantos",
        metavar="N",
        type=int,
        default=10,
        help="Cuántos mostrar (por defecto 10).",
    )
    similares.set_defaults(funcion=_orden_similares)

    casi = subordenes.add_parser(
        "casi-duplicados",
        help="Pares casi idénticos que la deduplicación no atrapó.",
        description=(
            "Busca pares de registros con similitud por encima del umbral: el "
            "preprint y su versión publicada, o el mismo trabajo con el título "
            "retocado. Se REPORTAN para que una persona decida; no se fusionan "
            "solos."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(casi)
    _con_embeddings(casi)
    casi.add_argument(
        "--umbral",
        metavar="N",
        type=float,
        default=UMBRAL_CASI_DUPLICADO,
        help=(
            f"Similitud mínima para reportar un par (por defecto "
            f"{UMBRAL_CASI_DUPLICADO})."
        ),
    )
    casi.set_defaults(funcion=_orden_casi_duplicados)

    texto_completo = subordenes.add_parser(
        "texto-completo",
        help="Busca en Unpaywall la versión abierta legal de los incluidos.",
        description=(
            "Pregunta a Unpaywall por el DOI de cada registro incluido y guarda "
            "la URL de la versión en acceso abierto. Los que no tengan una van a "
            "por-conseguir.md: Tatewari NO elude muros de pago, esos textos se "
            "piden a la biblioteca institucional."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(texto_completo)
    texto_completo.add_argument(
        "revision", metavar="REVISIÓN", help="Nombre de la revisión."
    )
    texto_completo.add_argument(
        "--protocolo",
        metavar="RUTA",
        type=Path,
        default=None,
        help="Ruta al protocolo. Si se omite, el que anotó la cosecha.",
    )
    texto_completo.add_argument(
        "--rehacer",
        action="store_true",
        help=(
            "Vuelve a preguntar por los DOI ya resueltos. Sin esto, se "
            "reutiliza lo que ya se sabía."
        ),
    )
    texto_completo.set_defaults(funcion=_orden_texto_completo)

    descargar_orden = subordenes.add_parser(
        "descargar",
        help="Baja a la carpeta pdf/ los PDF en acceso abierto de los incluidos.",
        description=(
            "Baja el PDF legal de cada registro incluido: el enlace de Unpaywall "
            "(lanza antes «texto-completo») o, si no lo hay, el de OpenAlex. Solo "
            "guarda lo que de verdad es un PDF; si el enlace es una página web o "
            "la editorial no deja bajarlo a un programa, lo lista para abrirlo en "
            "el navegador. No elude muros de pago. Es reanudable."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(descargar_orden)
    descargar_orden.add_argument(
        "revision", metavar="REVISIÓN", help="Nombre de la revisión."
    )
    descargar_orden.add_argument(
        "--protocolo",
        metavar="RUTA",
        type=Path,
        default=None,
        help="Ruta al protocolo. Si se omite, el que anotó la cosecha.",
    )
    descargar_orden.add_argument(
        "--max",
        metavar="N",
        type=int,
        default=None,
        help="Baja solo los primeros N incluidos (para probar).",
    )
    descargar_orden.add_argument(
        "--abrir",
        action="store_true",
        help=(
            "Abre en tu navegador los que no se bajaron solos (máximo 15 por "
            "vez), para que los guardes tú."
        ),
    )
    descargar_orden.set_defaults(funcion=_orden_descargar)

    asistente_orden = subordenes.add_parser(
        "asistente",
        help="Toda la revisión paso a paso, con explicaciones y sin memorizar órdenes.",
        description=(
            "Te lleva de la configuración a las notas de Obsidian: revisa tu .env, "
            "te deja escoger el protocolo, explora el tema, cosecha hasta terminar, "
            "criba, busca y baja los textos abiertos y exporta. Explica cada paso, "
            "pregunta antes de gastar cuota y enseña la orden que corre, para que "
            "aprendas a usarla a mano. Escribe «q» para salir cuando quieras."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(asistente_orden)
    asistente_orden.add_argument(
        "--si",
        action="store_true",
        help="Acepta todas las opciones por defecto sin preguntar.",
    )
    asistente_orden.set_defaults(funcion=_orden_asistente)

    explorar_orden = subordenes.add_parser(
        "explorar",
        help="Busca por significado en OpenAlex y dice qué se le escapa a tu protocolo.",
        description=(
            "Describe tu tema con palabras normales y OpenAlex devuelve los trabajos "
            "más parecidos por significado (hasta 50). Con --protocolo, dice cuáles "
            "encontraría tu cosecha y cuáles se le escapan, y sugiere frases de sus "
            "títulos que le faltan al protocolo. Sirve para corregir el protocolo "
            "antes de la cosecha grande; no sustituye a la cosecha."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(explorar_orden)
    explorar_orden.add_argument(
        "texto", metavar="TEXTO", help='Tu tema, entre comillas: "bloques de tierra con cal".'
    )
    explorar_orden.add_argument(
        "--protocolo",
        metavar="RUTA",
        type=Path,
        default=None,
        help="Protocolo que se quiere auditar (también fija años y tipos).",
    )
    explorar_orden.add_argument(
        "--max",
        metavar="N",
        type=int,
        default=25,
        help=f"Cuántos resultados (por defecto 25, máximo {MAXIMO_EXPLORAR}).",
    )
    explorar_orden.set_defaults(funcion=_orden_explorar)

    tesauro_orden = subordenes.add_parser(
        "tesauro",
        help="Sugiere sinónimos y traducciones de un término (AGROVOC, Wikidata).",
        description=(
            "Busca un término en dos tesauros abiertos, AGROVOC (FAO) y "
            "Wikidata, y enseña cómo se llama ese concepto en español y en "
            "inglés, con sus formas alternativas. Solo sugiere: no toca el "
            "protocolo. Tú eliges qué términos copiar a sus bloques."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(tesauro_orden)
    tesauro_orden.add_argument(
        "termino", metavar="TÉRMINO", help='Lo que buscas, entre comillas: "compressed earth block".'
    )
    tesauro_orden.add_argument(
        "--fuente",
        choices=(*FUENTES_TESAURO, "todas"),
        default="todas",
        help="Qué tesauro consultar (por defecto, los dos).",
    )
    tesauro_orden.add_argument(
        "--max",
        metavar="N",
        type=int,
        default=3,
        help="Conceptos como máximo por tesauro (por defecto 3).",
    )
    tesauro_orden.set_defaults(funcion=_orden_tesauro)

    exportar_orden = subordenes.add_parser(
        "exportar",
        help="Escribe el BibTeX y las fichas en Markdown.",
        description=(
            "Escribe cuatro archivos en la carpeta de la revisión: incluidos.bib "
            "para Zotero o Mendeley, incluidos.md con una ficha por artículo, "
            "revision-manual.md con los dudosos que esperan una persona, y "
            "por-conseguir.md con los incluidos sin acceso abierto."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(exportar_orden)
    exportar_orden.add_argument(
        "revision", metavar="REVISIÓN", help="Nombre de la revisión."
    )
    exportar_orden.add_argument(
        "--protocolo",
        metavar="RUTA",
        type=Path,
        default=None,
        help="Ruta al protocolo. Si se omite, el que anotó la cosecha.",
    )
    exportar_orden.set_defaults(funcion=_orden_exportar)

    estado = subordenes.add_parser(
        "estado",
        help="Resume en qué punto va una revisión.",
        description=(
            "Dice en qué punto va una revisión: ecuaciones ejecutadas y "
            "pendientes, registros únicos, conteo por decisión y qué archivos "
            "están generados. Es de SOLO LECTURA: no escribe nada."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(estado)
    estado.add_argument(
        "revision", metavar="REVISIÓN", help="Nombre de la revisión."
    )
    estado.add_argument(
        "--protocolo",
        metavar="RUTA",
        type=Path,
        default=None,
        help="Ruta al protocolo. Si se omite, el que anotó la cosecha.",
    )
    estado.set_defaults(funcion=_orden_estado)

    # Knowledge Studio y ZEA MAYZ viven en su propio módulo para no engordar este.
    anadir_ordenes(subordenes, _preparar_parser, _FormateadorEspanol)
    anadir_orden_interfaz(subordenes, _preparar_parser, _FormateadorEspanol)

    biblioteca = subordenes.add_parser(
        "biblioteca",
        help="El acervo acumulativo de todas las revisiones.",
        description=(
            "Acumula las revisiones en una base SQLite para poder preguntarle "
            "cosas que ninguna carpeta contesta sola: si un artículo ya se leyó "
            "en otra revisión, o qué hay sobre un tema venga de donde venga. La "
            "base se reconstruye desde los archivos de evidencia; los archivos "
            "de evidencia no se reconstruyen desde la base."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(biblioteca)
    biblioteca.set_defaults(funcion=_orden_ayuda, parser_propio=biblioteca)
    acciones_biblioteca = biblioteca.add_subparsers(dest="accion", metavar="ACCIÓN")

    importar = acciones_biblioteca.add_parser(
        "importar",
        help="Vuelca una revisión en la biblioteca.",
        description=(
            "Vuelca una carpeta de revisión en la biblioteca. Volver a importar "
            "la misma revisión es seguro: las referencias se funden en vez de "
            "duplicarse."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(importar)
    importar.add_argument(
        "revision",
        metavar="REVISIÓN",
        nargs="?",
        default=None,
        help="Nombre de la revisión. Si se omite, se importan todas.",
    )
    importar.set_defaults(funcion=_orden_biblioteca_importar)

    buscar = acciones_biblioteca.add_parser(
        "buscar",
        help="Busca referencias en todo el acervo.",
        description="Busca referencias acumuladas. Los filtros se acumulan.",
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(buscar)
    buscar.add_argument(
        "texto",
        metavar="TEXTO",
        nargs="?",
        default=None,
        help="Busca en el título y en el resumen.",
    )
    buscar.add_argument(
        "--revision", metavar="NOMBRE", default=None, help="Solo de esta revisión."
    )
    buscar.add_argument(
        "--estado",
        choices=DECISIONES,
        default=None,
        help="Solo los que quedaron en este estado.",
    )
    buscar.add_argument(
        "--desde",
        metavar="AÑO",
        type=int,
        default=None,
        dest="anio_desde",
        help="Solo los publicados desde ese año.",
    )
    buscar.add_argument(
        "--cuantos", metavar="N", type=int, default=25, help="Cuántos mostrar."
    )
    buscar.set_defaults(funcion=_orden_biblioteca_buscar)

    resumen_biblioteca = acciones_biblioteca.add_parser(
        "resumen",
        help="Cuántas referencias y revisiones hay acumuladas.",
        description="Resumen del acervo: cuánto hay y de dónde viene.",
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(resumen_biblioteca)
    resumen_biblioteca.set_defaults(funcion=_orden_biblioteca_resumen)

    rehacer = acciones_biblioteca.add_parser(
        "reconstruir",
        help="Borra la base y la rehace desde las revisiones.",
        description=(
            "Borra la base y la rehace recorriendo las carpetas de revisiones. "
            "Es seguro porque la evidencia vive en los archivos, no aquí. Lo "
            "único que no vuelve son las anotaciones puestas a mano."
        ),
        formatter_class=_FormateadorEspanol,
        add_help=False,
    )
    _preparar_parser(rehacer)
    rehacer.set_defaults(funcion=_orden_biblioteca_reconstruir)

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

    cliente = (
        None if sin_red else ClienteHttp(credenciales=config.credenciales_http())
    )

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


def _preparar_cribado(args: argparse.Namespace) -> tuple[Cribado, int]:
    """Monta el `Cribado` de una revisión, o devuelve el código de salida.

    Lo comparten `cribar`, `pendientes` y `decidir`: las tres necesitan la misma
    configuración, el mismo protocolo y los mismos mensajes de error.
    """
    try:
        config = cargar_config()
    except ErrorConfig as error:
        print(error, file=sys.stderr)
        return None, SALIDA_CONFIGURACION

    carpeta = config.datos / args.revision
    ruta_protocolo = args.protocolo or protocolo_registrado(carpeta)
    if ruta_protocolo is None:
        print(
            f"No sé con qué protocolo cribar «{args.revision}»: no hay "
            f"estado.json en {carpeta} o no anota ninguno. Indícalo con "
            f"--protocolo RUTA.",
            file=sys.stderr,
        )
        return None, SALIDA_CRIBADO

    try:
        protocolo = cargar_protocolo(ruta_protocolo)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return None, SALIDA_ARCHIVO_NO_ENCONTRADO
    except ErrorProtocolo as error:
        print(error, file=sys.stderr)
        return None, SALIDA_PROTOCOLO_INVALIDO

    return (
        Cribado(revision=args.revision, protocolo=protocolo, config=config),
        SALIDA_OK,
    )


def _avance_antes(indice: int, total: int, decision) -> None:
    """Avisa de que empieza un registro, **antes** de esperar al modelo.

    Sin esto, el primer registro deja la consola muda medio minuto mientras
    Ollama carga el modelo en memoria, y parece que el programa se colgó.
    """
    print(
        f"  [{indice}/{total}] {decision.identificador}  preguntando… ",
        end="",
        flush=True,
    )


def _avance_despues(indice: int, total: int, paso) -> None:
    print(paso.linea())


def _cribar_con_modelo(cribado: Cribado, args: argparse.Namespace) -> int:
    """Pasa los dudosos por Ollama y guarda lo que decida. Devuelve el código."""
    try:
        resultado = cribado.calcular()
    except ErrorCribado as error:
        print(error, file=sys.stderr)
        return SALIDA_CRIBADO

    dudosos = resultado.por_decision("dudoso")
    if not dudosos:
        print(
            "No hay ningún registro dudoso que pasar por el modelo: el filtro "
            "los decidió todos."
        )
        return SALIDA_OK

    cliente = ClienteOllama.desde_config(cribado.config, modelo=args.modelo)
    try:
        # Comprobar primero: si Ollama no está levantado, mejor saberlo ahora
        # que después de cargar el protocolo y anunciar el trabajo.
        print(cliente.resumen())
        print()
        print(f"Registros dudosos que va a mirar el modelo: {len(dudosos)}")
        salida = cribar_dudosos(
            dudosos,
            cribado.protocolo,
            cliente,
            antes=_avance_antes,
            despues=_avance_despues,
        )
    except ErrorOllama as error:
        print(error, file=sys.stderr)
        return SALIDA_MODELO

    print()
    print(salida.resumen())

    if salida.decisiones:
        anadir_decisiones(cribado.ruta_decisiones, salida.decisiones)
        print(f"Decisiones guardadas en {cribado.ruta_decisiones}")
    print()
    return SALIDA_OK


def _orden_cribar(args: argparse.Namespace) -> int:
    cribado, codigo = _preparar_cribado(args)
    if cribado is None:
        return codigo

    if args.modelo_local:
        codigo = _cribar_con_modelo(cribado, args)
        if codigo != SALIDA_OK:
            return codigo

    try:
        resultado = cribado.ejecutar()
    except ErrorCribado as error:
        print(error, file=sys.stderr)
        return SALIDA_CRIBADO

    print(resultado.resumen())
    print()
    print(resultado.diagrama())
    print()
    print(f"Cribado  : {cribado.ruta_csv}")
    print(f"PRISMA   : {cribado.ruta_prisma}")
    print(f"Identific: {cribado.ruta_identificadores}")

    if resultado.avisos:
        print()
        print("Avisos:", file=sys.stderr)
        for aviso in resultado.avisos:
            print(f"  - {aviso}", file=sys.stderr)

    return SALIDA_OK


def _mostrar_registro(decision) -> None:
    """Imprime un registro para que una persona pueda decidir sobre él."""
    registro = decision.registro
    print(
        f"{decision.identificador}  {registro.get('anio', 'NR')}  "
        f"[{decision.decision}]  lo decidió: {decision.decidido_por}"
    )
    print(f"  Título : {registro.get('titulo', 'NR')}")
    print(f"  Revista: {registro.get('revista', 'NR')}")
    print(f"  Motivo : {decision.motivo}")
    if decision.es_manual:
        print(f"  El filtro decía: {decision.decision_filtro} — {decision.motivo_filtro}")
    print(f"  Resumen: {recortar(registro.get('resumen'), LIMITE_RESUMEN)}")
    print()


def _orden_pendientes(args: argparse.Namespace) -> int:
    cribado, codigo = _preparar_cribado(args)
    if cribado is None:
        return codigo

    try:
        resultado = cribado.calcular()
    except ErrorCribado as error:
        print(error, file=sys.stderr)
        return SALIDA_CRIBADO

    if args.modo == "auditoria":
        return _pendientes_auditoria(cribado, resultado, args)

    decisiones = resultado.por_decision(args.modo)
    if args.cuantos is not None:
        decisiones = decisiones[: max(0, args.cuantos)]

    etiqueta = {
        "dudoso": ("registro dudoso, esperando", "registros dudosos, esperando"),
        "incluir": ("registro que entra", "registros que entran"),
    }[args.modo]
    plural = etiqueta[0] if len(decisiones) == 1 else etiqueta[1]
    cola = (
        " una decisión humana" if args.modo == "dudoso" else " en la revisión"
    )
    print(f"Revisión {cribado.revision}: {len(decisiones)} {plural}{cola}.")
    print()
    for decision in decisiones:
        _mostrar_registro(decision)

    if args.modo == "dudoso" and decisiones:
        print(
            "Para decidir uno:  python -m tatewari decidir "
            f"{cribado.revision} {decisiones[0].identificador} "
            "--decision incluir --motivo \"...\""
        )
    return SALIDA_OK


def _pendientes_auditoria(
    cribado: Cribado, resultado, args: argparse.Namespace
) -> int:
    """Muestra aleatoria de las exclusiones, para revisarlas a mano.

    `pendientes` es de **solo lectura**: sin `--registrar` no escribe nada, ni
    aquí. Pero la regla 4 de AGENTS.md pide que la auditoría quede registrada, y
    una muestra que no se apunta no se puede volver a comprobar, así que cuando
    no se registra se dice en la salida y se enseña cómo hacerlo.
    """
    exclusiones = resultado.por_decision("excluir")
    cuantos = MUESTRA_POR_DEFECTO if args.cuantos is None else args.cuantos

    muestra = muestra_aleatoria(exclusiones, cuantos, semilla=args.semilla)
    print(muestra.resumen())
    print()
    for decision in muestra.elementos:
        _mostrar_registro(decision)

    if not muestra.elementos:
        return SALIDA_OK

    if args.registrar:
        try:
            ruta = registrar_auditoria(
                cribado.carpeta / NOMBRE_AUDITORIA,
                muestra,
                [d.identificador for d in muestra.elementos],
                revision=cribado.revision,
            )
        except ErrorAuditoria as error:
            print(error, file=sys.stderr)
            return SALIDA_CRIBADO
        print(f"Auditoría registrada en {ruta}")
    else:
        print(
            "Esta ronda NO ha quedado registrada: «pendientes» no escribe nada.\n"
            "La regla 4 de AGENTS.md pide que la auditoría quede registrada, así "
            "que\ncuando la hayas revisado de verdad, apúntala:"
        )
        print(
            f"  python -m tatewari pendientes {cribado.revision} --modo auditoria "
            f"--semilla {muestra.semilla} --registrar"
        )
    print()
    print(
        "Revisa estas exclusiones a mano. Si alguna está mal descartada, "
        "corrígela con «decidir»:"
    )
    print(
        f"  python -m tatewari decidir {cribado.revision} "
        f"{muestra.elementos[0].identificador} --decision incluir --motivo \"...\""
    )
    return SALIDA_OK


def _orden_decidir(args: argparse.Namespace) -> int:
    cribado, codigo = _preparar_cribado(args)
    if cribado is None:
        return codigo

    motivo = args.motivo.strip()
    if not motivo:
        print(
            "El motivo no puede estar vacío: una decisión sin motivo no es "
            "auditable, y entonces no vale más que la del filtro.",
            file=sys.stderr,
        )
        return SALIDA_CRIBADO

    try:
        resultado = cribado.calcular()
    except ErrorCribado as error:
        print(error, file=sys.stderr)
        return SALIDA_CRIBADO

    try:
        previa = resultado.buscar(args.identificador)
    except KeyError:
        print(
            f"No hay ningún registro {args.identificador} en la revisión "
            f"«{args.revision}». Mira los identificadores con «pendientes».",
            file=sys.stderr,
        )
        return SALIDA_CRIBADO

    # El autor por defecto es el usuario de esta máquina: es un dato real, no un
    # nombre inventado (AGENTS.md, regla 2).
    autor = (args.autor or getpass.getuser() or "NR").strip()
    nueva = DecisionManual(
        identificador=args.identificador,
        decision=args.decision,
        motivo=motivo,
        autor=autor,
        fecha=date.today().isoformat(),
    )

    if previa.es_manual:
        print(
            f"Sustituye la decisión anterior de {previa.decidido_por}: "
            f"{previa.decision} — {previa.motivo}"
        )
    print(
        f"{args.identificador}: el filtro decía «{previa.decision_filtro or previa.decision}»; "
        f"{autor} dice «{args.decision}»."
    )

    anadir_decisiones(cribado.ruta_decisiones, {args.identificador: nueva})

    try:
        final = cribado.ejecutar()
    except ErrorCribado as error:
        print(error, file=sys.stderr)
        return SALIDA_CRIBADO

    print()
    print(final.resumen())
    print()
    print(f"Decisiones: {cribado.ruta_decisiones}")
    print(f"Cribado   : {cribado.ruta_csv}")
    print(f"PRISMA    : {cribado.ruta_prisma}")
    return SALIDA_OK


def _avance_vectores(hechos: int, total: int, en_lote: int) -> None:
    print(f"  vectorizando… {hechos}/{total}", flush=True)


def _preparar_vectores(args: argparse.Namespace):
    """Criba la revisión y deja los vectores al día. Devuelve lo necesario.

    Es el arranque común de `ordenar`, `similares` y `casi-duplicados`: las tres
    necesitan el cribado (para los títulos y las decisiones) y la caché de
    vectores. Devuelve `(cribado, resultado, almacen, cliente, codigo)`; si algo
    falló, los cuatro primeros van a `None` y el código dice qué pasó.

    **No escribe ninguna decisión.** La similitud es una ayuda de lectura y no
    puede cambiar por sí sola nada del cribado, así que aquí se usa `calcular()`,
    que no toca `decisiones.json` ni reescribe `cribado.csv`.
    """
    vacio = (None, None, None, None)

    cribado, codigo = _preparar_cribado(args)
    if cribado is None:
        return (*vacio, codigo)

    try:
        resultado = cribado.calcular()
    except ErrorCribado as error:
        print(error, file=sys.stderr)
        return (*vacio, SALIDA_CRIBADO)

    cliente = ClienteEmbeddings.desde_config(
        cribado.config, modelo=args.modelo_embed
    )
    almacen = Almacen.leer(cribado.carpeta / NOMBRE_VECTORES, args.modelo_embed)

    try:
        salida = vectorizar(
            [d.registro for d in resultado.decisiones],
            cliente,
            almacen,
            lote=args.lote,
            avance=_avance_vectores,
        )
    except (ErrorEmbeddings, ErrorOllama) as error:
        print(error, file=sys.stderr)
        return (*vacio, SALIDA_EMBEDDINGS)

    if salida.calculados:
        almacen.guardar()
    print(salida.resumen())
    print()
    return cribado, resultado, almacen, cliente, SALIDA_OK


def _orden_ordenar(args: argparse.Namespace) -> int:
    cribado, resultado, almacen, cliente, codigo = _preparar_vectores(args)
    if cribado is None:
        return codigo

    try:
        vector = cliente.vector(args.pregunta)
    except (ErrorEmbeddings, ErrorOllama) as error:
        print(error, file=sys.stderr)
        return SALIDA_EMBEDDINGS

    decisiones = resultado.decisiones
    if args.modo != "todos":
        decisiones = resultado.por_decision(args.modo)

    parecidos = ordenar_por_parecido(decisiones, almacen, vector)
    mostrados = parecidos if args.cuantos <= 0 else parecidos[: args.cuantos]

    print(f"Pregunta: {args.pregunta}")
    print(
        f"Ordenados por cercanía: {len(mostrados)} de {len(parecidos)} registros"
        + (f" ({args.modo})" if args.modo != "todos" else "")
    )
    print()
    for puesto, parecido in enumerate(mostrados, start=1):
        print(f"{puesto:>3}. {parecido.linea()}")
        print()

    print(
        "La similitud es una ayuda de lectura: dice en qué orden mirar, no qué\n"
        "entra en la revisión. Ninguna decisión del cribado ha cambiado."
    )
    return SALIDA_OK


def _orden_similares(args: argparse.Namespace) -> int:
    cribado, resultado, almacen, _, codigo = _preparar_vectores(args)
    if cribado is None:
        return codigo

    try:
        referencia = resultado.buscar(args.identificador)
    except KeyError:
        print(
            f"No hay ningún registro {args.identificador} en la revisión "
            f"«{args.revision}». Mira los identificadores con «pendientes».",
            file=sys.stderr,
        )
        return SALIDA_CRIBADO

    try:
        parecidos = mas_parecidos(
            args.identificador, resultado.decisiones, almacen, args.cuantos
        )
    except KeyError:
        print(
            f"El registro {args.identificador} no tiene vector: no trae ni "
            f"título ni resumen con los que compararlo.",
            file=sys.stderr,
        )
        return SALIDA_EMBEDDINGS

    print(f"Parecidos a {args.identificador}:")
    print(f"  {referencia.registro.get('titulo', 'NR')}")
    print()
    for puesto, parecido in enumerate(parecidos, start=1):
        print(f"{puesto:>3}. {parecido.linea()}")
        print()

    print(
        "La similitud es una ayuda de lectura: no cambia ninguna decisión del\n"
        "cribado."
    )
    return SALIDA_OK


def _orden_casi_duplicados(args: argparse.Namespace) -> int:
    cribado, resultado, almacen, _, codigo = _preparar_vectores(args)
    if cribado is None:
        return codigo

    pares = casi_duplicados(resultado.decisiones, almacen, args.umbral)

    if not pares:
        print(
            f"No hay ningún par con similitud >= {args.umbral:g} entre los "
            f"{resultado.cribados} registros únicos.\n"
            f"La deduplicación por DOI y título no ha dejado pasar ningún casi "
            f"duplicado detectable."
        )
        return SALIDA_OK

    print(
        f"{len(pares)} pares con similitud >= {args.umbral:g} que la "
        f"deduplicación no atrapó:"
    )
    print()
    for par in pares:
        for linea in par.lineas():
            print(linea)
        print()

    ruta = _escribir_casi_duplicados(cribado, pares)
    print(f"Reporte: {ruta}")
    print(
        "Revísalos a mano. **No se han fusionado**: decidir que dos registros son\n"
        "el mismo trabajo es una decisión humana, y con este umbral también salen\n"
        "dos estudios distintos del mismo grupo sobre el mismo humedal.\n"
        "Si uno sobra, márcalo con «decidir ... --decision excluir»."
    )
    return SALIDA_OK


def _escribir_casi_duplicados(cribado: Cribado, pares) -> Path:
    """Deja el reporte en `casi_duplicados.csv`, dentro de la revisión.

    En UTF-8 sin BOM, como `cribado.csv`: la excepción del BOM que autoriza
    AGENTS.md es solo para `search_log.csv`.
    """
    ruta = cribado.carpeta / "casi_duplicados.csv"
    columnas = (
        "similitud",
        "identificador_uno",
        "identificador_otro",
        "diagnostico",
        "vector_baja_calidad",
        "doi_uno",
        "doi_otro",
        "titulo_uno",
        "titulo_otro",
    )
    cribado.carpeta.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as manejador:
        escritor = csv.DictWriter(
            manejador, fieldnames=list(columnas), lineterminator="\n"
        )
        escritor.writeheader()
        for par in pares:
            uno = getattr(par.decision_uno, "registro", {}) or {}
            otro = getattr(par.decision_otro, "registro", {}) or {}
            escritor.writerow(
                {
                    "similitud": f"{par.similitud:.4f}",
                    "identificador_uno": par.uno,
                    "identificador_otro": par.otro,
                    "diagnostico": par.diagnostico,
                    "vector_baja_calidad": "sí" if par.baja_calidad else "no",
                    "doi_uno": uno.get("doi", "NR"),
                    "doi_otro": otro.get("doi", "NR"),
                    "titulo_uno": uno.get("titulo", "NR"),
                    "titulo_otro": otro.get("titulo", "NR"),
                }
            )
    return ruta


def _orden_exportar(args: argparse.Namespace) -> int:
    cribado, codigo = _preparar_cribado(args)
    if cribado is None:
        return codigo

    try:
        resultado = cribado.calcular()
    except ErrorCribado as error:
        print(error, file=sys.stderr)
        return SALIDA_CRIBADO

    salida = exportar(resultado, cribado.carpeta, revision=cribado.revision)

    print(salida.resumen())
    if salida.sin_abierto:
        print()
        print(
            f"Los {salida.sin_abierto} sin acceso abierto están en "
            f"por-conseguir.md, con su DOI.\n"
            f"Tatewari no elude muros de pago: se piden a la biblioteca "
            f"(AGENTS.md, regla 5)."
        )
    if salida.incluidos == 0:
        print()
        print(
            "Ojo: no hay ningún registro incluido, así que el BibTeX sale vacío. "
            "¿Se ha cribado ya esta revisión?"
        )
    return SALIDA_OK


def _orden_descargar(args: argparse.Namespace) -> int:
    cribado, codigo = _preparar_cribado(args)
    if cribado is None:
        return codigo
    try:
        resultado = cribado.calcular()
    except ErrorCribado as error:
        print(error, file=sys.stderr)
        return SALIDA_CRIBADO

    incluidos = resultado.por_decision("incluir")
    if args.max is not None:
        incluidos = incluidos[: max(0, args.max)]
    if not incluidos:
        print(
            "No hay ningún registro incluido todavía, así que no hay nada que "
            "bajar. Lanza antes «tatewari cribar»."
        )
        return SALIDA_OK

    resueltos = leer_resueltos(cribado.carpeta / NOMBRE_TEXTO_COMPLETO)
    if not resueltos:
        print(
            "Aviso: no hay texto_completo.json; se usan los enlaces de OpenAlex, "
            "que a veces llevan a la página del artículo y no al PDF. Para más "
            f"PDF, lanza antes «tatewari texto-completo {args.revision}».",
        )
        print()

    print(f"Bajando los PDF abiertos de {len(incluidos)} registros incluidos.")
    print()

    def avance(indice: int, total: int, descarga) -> None:
        print(f"  [{indice}/{total}] {descarga.linea()}")

    salida = descargar_incluidos(
        incluidos, resueltos, cribado.carpeta, sesion=_sesion_descargas(), avance=avance
    )
    print()
    print(salida.resumen())
    print()
    print(f"Carpeta : {cribado.carpeta / 'pdf'}")
    a_mano = salida.a_mano()
    if a_mano:
        print(f"Para abrir: {cribado.carpeta / 'para-abrir.md'} ({len(a_mano)} enlaces)")
        if args.abrir:
            for descarga in a_mano[:MAX_PESTANAS]:
                _abrir_en_navegador(descarga.enlace)
            print()
            print(f"Abrí {min(len(a_mano), MAX_PESTANAS)} en tu navegador.", end=" ")
            if len(a_mano) > MAX_PESTANAS:
                print("Cuando los guardes, vuelve a lanzar la orden para los siguientes.")
            else:
                print("Guarda cada PDF en la carpeta pdf/ con el nombre de para-abrir.md.")
        else:
            print("Con --abrir se abren en tu navegador para guardarlos tú.")
    return SALIDA_OK


#: Pestañas que abre ``descargar --abrir`` de una vez: más satura el navegador.
MAX_PESTANAS = 15


def _abrir_en_navegador(enlace: str) -> None:
    """Abre `enlace` en el navegador del sistema. Aparte para que las pruebas lo cambien."""
    import webbrowser

    webbrowser.open_new_tab(enlace)


def _sesion_descargas():
    """Sesión de la orden ``descargar``. Función aparte para que las pruebas la cambien."""
    return nueva_sesion_descargas()


def _orden_asistente(args: argparse.Namespace) -> int:
    from .asistente import asistente_de_consola

    return asistente_de_consola(main, si_a_todo=args.si).recorrer()


def _orden_explorar(args: argparse.Namespace) -> int:
    try:
        config = cargar_config()
    except ErrorConfig as error:
        print(error, file=sys.stderr)
        return SALIDA_CONFIGURACION

    protocolo = None
    if args.protocolo is not None:
        try:
            protocolo = cargar_protocolo(args.protocolo)
        except FileNotFoundError as error:
            print(error, file=sys.stderr)
            return SALIDA_ARCHIVO_NO_ENCONTRADO
        except ErrorProtocolo as error:
            print(error, file=sys.stderr)
            return SALIDA_PROTOCOLO_INVALIDO

    cliente = _cliente_explorar(config)
    try:
        exploracion = explorar_por_significado(
            args.texto,
            cliente,
            protocolo,
            por_pagina=args.max,
            correo=config.mailto if config.tiene_mailto else "",
        )
    except ErrorHttp as error:
        print(f"OpenAlex no respondió: {error}", file=sys.stderr)
        return SALIDA_COSECHA

    print(f"Búsqueda por significado en OpenAlex: «{args.texto}»")
    print(f"URL: {exploracion.url}")
    print()
    for numero, hallado in enumerate(exploracion.hallados, start=1):
        print(f"{numero:>3}. {hallado.linea()}")
    if not exploracion.hallados:
        print("Sin resultados.")

    if protocolo is not None and exploracion.hallados:
        total = len(exploracion.hallados)
        cosechados = sum(1 for h in exploracion.hallados if h.cosechado)
        incluidos = sum(1 for h in exploracion.hallados if h.decision == "incluir")
        print()
        print(
            f"Tu protocolo: la cosecha encontraría {cosechados} de {total}, y el "
            f"cribado incluiría {incluidos}."
        )
        if exploracion.escapados:
            print(f"Se le escapan {len(exploracion.escapados)}: sus palabras no están en el eje y el cruce.")
        if exploracion.sugerencias:
            print()
            print("Frases que se repiten en los títulos que se escapan (candidatas a sinónimo):")
            print(
                "  "
                + ", ".join(f"«{frase}» ({veces})" for frase, veces in exploracion.sugerencias)
            )
            print(
                "Revísalas con «tatewari tesauro» y, si nombran tu tema, agrégalas a un "
                "bloque del protocolo. Tú decides."
            )
    print()
    print(
        "Ojo: esto son los trabajos más parecidos, no una búsqueda exhaustiva ni "
        "repetible. Para la revisión, cosecha con el protocolo."
    )
    cuota = getattr(cliente, "cuota", None)
    if cuota is not None and cuota.hay_datos:
        print(cuota.resumen())
    return SALIDA_OK


def _cliente_explorar(config) -> ClienteHttp:
    """Cliente de ``explorar``, con la clave de OpenAlex. Aparte para las pruebas."""
    return ClienteHttp(credenciales=config.credenciales_http())


def _orden_tesauro(args: argparse.Namespace) -> int:
    fuentes = FUENTES_TESAURO if args.fuente == "todas" else (args.fuente,)
    consulta = buscar_en_tesauros(
        args.termino, _cliente_tesauro(), fuentes=fuentes, maximo=max(1, args.max)
    )
    print(f"«{args.termino}» en tesauros abiertos. Son sugerencias: tú decides qué va al protocolo.")
    for concepto in consulta.conceptos:
        print()
        fuente = "AGROVOC" if concepto.fuente == "agrovoc" else "Wikidata"
        detalle = f" — {concepto.descripcion}" if concepto.descripcion else ""
        print(f"{fuente} · {concepto.nombre}{detalle}")
        for idioma, formas in concepto.etiquetas.items():
            marcadas = [f"{forma} (sigla)" if es_sigla(forma) else forma for forma in formas]
            print(f"  {idioma}: " + " · ".join(marcadas))
        if concepto.relacionados:
            print("  cercanos: " + " · ".join(concepto.relacionados[:8]))
        print(f"  {concepto.enlace}")
    for aviso in consulta.avisos:
        print()
        print(aviso)
    frases, siglas = terminos_sugeridos(consulta)
    if frases:
        print()
        print("Para copiar a un bloque del protocolo (borra los que no te sirvan):")
        print("  " + ", ".join(json.dumps(frase, ensure_ascii=False) for frase in frases))
    if siglas:
        print()
        print(
            "Siglas encontradas: " + ", ".join(siglas) + ". Compruébalas antes de "
            "usarlas: una sigla suele significar otra cosa en otro campo (en "
            "OpenAlex, «BTC» trae sobre todo artículos de Bitcoin)."
        )
    return SALIDA_OK


def _cliente_tesauro() -> ClienteHttp:
    """Cliente de la orden ``tesauro``. Función aparte para que las pruebas lo cambien."""
    return ClienteHttp()


def _orden_texto_completo(args: argparse.Namespace) -> int:
    cribado, codigo = _preparar_cribado(args)
    if cribado is None:
        return codigo

    config = cribado.config
    if not config.tiene_mailto:
        print(
            "Unpaywall exige un correo de contacto y TATEWARI_MAILTO está vacío "
            "o no es válido. Copia .env.example a .env y pon ahí tu correo; sin "
            "él, Unpaywall rechaza la petición.",
            file=sys.stderr,
        )
        return SALIDA_CONFIGURACION

    try:
        resultado = cribado.calcular()
    except ErrorCribado as error:
        print(error, file=sys.stderr)
        return SALIDA_CRIBADO

    incluidos = resultado.por_decision("incluir")
    if not incluidos:
        print(
            "No hay ningún registro incluido todavía, así que no hay textos que "
            "resolver. Lanza antes «tatewari cribar»."
        )
        return SALIDA_OK

    ruta_resueltos = cribado.carpeta / NOMBRE_TEXTO_COMPLETO
    previos = leer_resueltos(ruta_resueltos)

    print(f"Resolviendo el texto completo de {len(incluidos)} registros incluidos.")
    print()

    def avance(indice: int, total: int, resuelto) -> None:
        print(f"  [{indice}/{total}] {resuelto.linea()}")

    try:
        salida = resolver_incluidos(
            incluidos,
            ClienteHttp(),
            config.exigir_mailto(),
            resueltos=previos,
            rehacer=args.rehacer,
            avance=avance,
        )
    except ErrorConfig as error:
        print(error, file=sys.stderr)
        return SALIDA_CONFIGURACION

    guardar_resueltos(ruta_resueltos, salida.resueltos)

    # La URL va al registro, que es lo que hace que aparezca sola en el CSV y en
    # las fichas exportadas.
    registros = cribado.leer_registros()
    cambiados = aplicar_a_registros(
        registros, salida.resueltos, resultado.asignaciones
    )
    if cambiados:
        with open(cribado.ruta_registros, "w", encoding="utf-8") as manejador:
            json.dump(registros, manejador, ensure_ascii=False, indent=2)
            manejador.write("\n")

    print()
    print(salida.resumen())
    print()
    print(f"Detalle  : {ruta_resueltos}")
    if cambiados:
        print(f"Registros: {cribado.ruta_registros} ({cambiados} con oa_url nueva)")

    if salida.incidencias:
        print()
        print("Incidencias:", file=sys.stderr)
        for incidencia in salida.incidencias:
            print(f"  - {incidencia}", file=sys.stderr)
    return SALIDA_OK


def _orden_estado(args: argparse.Namespace) -> int:
    """Resume la revisión. **No escribe nada**: es de solo lectura.

    Por eso usa `Cribado.calcular()` y `Cosecha.cargar_estado()`, que leen, y no
    `ejecutar()`, que escribiría. Una orden que solo informa no puede cambiar el
    estado de la revisión que está informando.
    """
    cribado, codigo = _preparar_cribado(args)
    if cribado is None:
        return codigo

    print(f"Revisión : {cribado.revision}")
    print(f"Protocolo: {cribado.protocolo.titulo}")
    print(f"Carpeta  : {cribado.carpeta}")
    print()

    # -- La cosecha ---------------------------------------------------------
    print("COSECHA")
    try:
        cosecha = Cosecha(
            revision=cribado.revision,
            protocolo=cribado.protocolo,
            config=cribado.config,
        )
        ecuaciones = cosecha.ecuaciones()
        estado_cosecha = cosecha.cargar_estado()
        hechas = estado_cosecha.get("hechas") or {}
        fallidas = sum(
            1 for entrada in hechas.values()
            if isinstance(entrada, dict) and entrada.get("resultados") == "NR"
        )
        print(f"  Ecuaciones del protocolo : {len(ecuaciones)}")
        print(f"  Ejecutadas               : {len(hechas)}")
        print(f"  Pendientes               : {len(ecuaciones) - len(hechas)}")
        if fallidas:
            print(f"  Con error                : {fallidas} (--reintentar)")
    except ErrorCosecha as error:
        print(f"  Sin ecuaciones: {error}")

    # -- El cribado ---------------------------------------------------------
    print()
    print("CRIBADO")
    try:
        resultado = cribado.calcular()
    except ErrorCribado as error:
        print(f"  Sin cribar: {error}")
        print()
        print("Siguiente paso: «tatewari cosechar» para traer registros.")
        return SALIDA_OK

    conteos = resultado.conteos
    print(f"  Registros identificados  : {resultado.identificados}")
    print(f"  Duplicados eliminados    : {resultado.duplicados_eliminados}")
    print(f"  Registros únicos         : {resultado.cribados}")
    print(f"    Incluir                : {conteos['incluir']}")
    print(f"    Dudoso                 : {conteos['dudoso']}")
    print(f"    Excluir                : {conteos['excluir']}")
    if resultado.manuales:
        print(f"  Decisiones no del filtro : {resultado.manuales}")

    # -- Textos completos ---------------------------------------------------
    resueltos = leer_resueltos(cribado.carpeta / NOMBRE_TEXTO_COMPLETO)
    incluidos = resultado.por_decision("incluir")
    # Se cuenta igual que en `exportar`, y a propósito: un registro tiene texto
    # accesible si **alguna** fuente dio una URL, sea OpenAlex al cosechar o
    # Unpaywall al resolver. Contarlo solo por lo que dijo Unpaywall haría que
    # «estado» y «exportar» dieran números distintos de lo mismo, que es peor que
    # dar uno solo imperfecto.
    con_url = sum(1 for d in incluidos if str(d.registro.get("oa_url") or NR) != NR)
    if incluidos:
        print()
        print("TEXTO COMPLETO")
        print(f"  Incluidos con URL abierta: {con_url} de {len(incluidos)}")
        print(f"  Por conseguir a mano     : {len(incluidos) - con_url}")
        if resueltos:
            confirmados = sum(1 for r in resueltos.values() if r.esta_abierto)
            print(
                f"  Consultados en Unpaywall : {len(resueltos)}, "
                f"{confirmados} con versión abierta confirmada"
            )
        else:
            print(
                "  Unpaywall                : sin consultar "
                "(«tatewari texto-completo»)"
            )

    # -- Los archivos -------------------------------------------------------
    print()
    print("ARCHIVOS")
    esperados = (
        ("registros.json", "los registros cosechados, con duplicados"),
        ("search_log.csv", "la bitácora de búsquedas"),
        ("estado.json", "qué ecuaciones se han lanzado"),
        ("identificadores.json", "los identificadores estables"),
        ("decisiones.json", "las decisiones que no tomó el filtro"),
        ("cribado.csv", "una fila por registro, con su motivo"),
        ("prisma.txt", "el diagrama de flujo PRISMA"),
        ("auditoria.json", "las rondas de auditoría registradas"),
        ("vectores.json", "la caché de vectores"),
        (NOMBRE_TEXTO_COMPLETO, "lo que dijo Unpaywall"),
        ("incluidos.bib", "bibliografía para Zotero o Mendeley"),
        ("incluidos.md", "una ficha por artículo incluido"),
        ("revision-manual.md", "los dudosos, para resolver a mano"),
        ("por-conseguir.md", "los incluidos sin acceso abierto"),
        ("casi_duplicados.csv", "pares que la deduplicación no atrapó"),
    )
    ancho = max(len(nombre) for nombre, _ in esperados)
    for nombre, que in esperados:
        ruta = cribado.carpeta / nombre
        marca = "sí" if ruta.is_file() else "no"
        print(f"  [{marca}] {nombre.ljust(ancho)}  {que}")

    # -- Qué toca ahora -----------------------------------------------------
    print()
    print(f"Siguiente paso: {_siguiente_paso(cribado, resultado, resueltos)}")
    return SALIDA_OK


def _siguiente_paso(cribado: Cribado, resultado, resueltos: dict) -> str:
    """Qué es lo más útil que se puede hacer ahora con esta revisión."""
    revision = cribado.revision
    if not (cribado.carpeta / "cribado.csv").is_file():
        return f"«tatewari cribar {revision}» para cribar lo cosechado."
    dudosos = resultado.conteos["dudoso"]
    if dudosos:
        cuantos = (
            "el registro dudoso" if dudosos == 1 else f"los {dudosos} dudosos"
        )
        return (
            f"«tatewari cribar {revision} --modelo-local» para pasar {cuantos} "
            f"por el modelo, o «tatewari pendientes {revision}» para "
            f"resolverlo{'' if dudosos == 1 else 's'} a mano."
        )
    if resultado.conteos["incluir"] and not resueltos:
        return (
            f"«tatewari texto-completo {revision}» para buscar las versiones en "
            f"acceso abierto."
        )
    if not (cribado.carpeta / "incluidos.bib").is_file():
        return f"«tatewari exportar {revision}» para el BibTeX y las fichas."
    return (
        f"«tatewari pendientes {revision} --modo auditoria» para auditar una "
        f"muestra de las exclusiones (AGENTS.md, regla 4)."
    )


def _config_o_error():
    """La configuración, o `(None, codigo)` si no se pudo cargar."""
    try:
        return cargar_config(), SALIDA_OK
    except ErrorConfig as error:
        print(error, file=sys.stderr)
        return None, SALIDA_CONFIGURACION


def _orden_biblioteca_importar(args: argparse.Namespace) -> int:
    config, codigo = _config_o_error()
    if config is None:
        return codigo

    carpetas = (
        [config.datos / args.revision]
        if args.revision
        else sorted(c for c in config.datos.glob("*") if c.is_dir())
    )
    if not carpetas:
        print(
            f"No hay ninguna revisión en {config.datos}. Lanza antes "
            f"«tatewari cosechar».",
            file=sys.stderr,
        )
        return SALIDA_CRIBADO

    try:
        with abrir_biblioteca(config.datos) as biblioteca:
            for carpeta in carpetas:
                resumen = biblioteca.importar_revision(carpeta)
                print(resumen.resumen())
                print()
            print(biblioteca.resumen())
    except ErrorBiblioteca as error:
        print(error, file=sys.stderr)
        return SALIDA_CRIBADO
    return SALIDA_OK


def _orden_biblioteca_buscar(args: argparse.Namespace) -> int:
    config, codigo = _config_o_error()
    if config is None:
        return codigo

    try:
        with abrir_biblioteca(config.datos) as biblioteca:
            referencias = biblioteca.buscar(
                texto=args.texto,
                revision=args.revision,
                estado=args.estado,
                anio_desde=args.anio_desde,
                limite=args.cuantos,
            )
    except ErrorBiblioteca as error:
        print(error, file=sys.stderr)
        return SALIDA_CRIBADO

    if not referencias:
        print(
            "Ninguna referencia coincide. Si la biblioteca está vacía, impórtala "
            "con «tatewari biblioteca importar»."
        )
        return SALIDA_OK

    print(f"{len(referencias)} referencias:")
    print()
    for referencia in referencias:
        autores = referencia.get("autores") or ["NR"]
        print(
            f"{referencia.get('id', 'NR')}  {referencia.get('anio', 'NR')}  "
            f"{referencia.get('titulo', 'NR')}"
        )
        print(f"        {'; '.join(autores)}")
        print(f"        DOI: {referencia.get('doi', 'NR')}")
        print()
    return SALIDA_OK


def _orden_biblioteca_resumen(args: argparse.Namespace) -> int:
    config, codigo = _config_o_error()
    if config is None:
        return codigo

    try:
        with abrir_biblioteca(config.datos) as biblioteca:
            print(biblioteca.resumen())
    except ErrorBiblioteca as error:
        print(error, file=sys.stderr)
        return SALIDA_CRIBADO
    return SALIDA_OK


def _orden_biblioteca_reconstruir(args: argparse.Namespace) -> int:
    config, codigo = _config_o_error()
    if config is None:
        return codigo

    try:
        resumenes = reconstruir_biblioteca(config.datos)
    except ErrorBiblioteca as error:
        print(error, file=sys.stderr)
        return SALIDA_CRIBADO

    print(f"Biblioteca rehecha desde {len(resumenes)} revisiones.")
    print()
    for resumen in resumenes:
        print(resumen.resumen())
        print()
    print(
        "Las anotaciones y etiquetas puestas a mano NO vuelven: no están en "
        "ningún archivo de evidencia."
    )
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
