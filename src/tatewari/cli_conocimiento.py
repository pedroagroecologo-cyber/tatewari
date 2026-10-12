"""Órdenes de Knowledge Studio y de ZEA MAYZ para la línea de órdenes.

Viven aquí y no en `cli.py` para que ese archivo no siga creciendo; `cli.py` las
registra con `anadir_ordenes`. Las órdenes:

    tatewari conocimiento crear-vault         «crear base de conocimiento»
    tatewari conocimiento procesar RUTA       «procesar documento»
    tatewari conocimiento materia [CARPETA]   «analizar materia»
    tatewari conocimiento actualizar          «actualizar conocimiento existente»
    tatewari conocimiento conceptos           «mostrar conceptos detectados»
    tatewari conocimiento conflictos          «mostrar conflictos»
    tatewari conocimiento reporte             «generar reporte»
    tatewari conocimiento validar | buscar | estado | habilidades | modelos
    tatewari pedir "procesa este documento apuntes.pdf"
    tatewari zea-mayz divulgar | validar
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from .config import ErrorConfig, cargar_config
from .conocimiento.documento import ErrorDocumento
from .conocimiento.enrutador import Enrutador
from .conocimiento.habilidades import habilidades
from .conocimiento.objetos import ESTADOS, TIPOS, ErrorEstado
from .conocimiento.orquestador import ACCIONES, Orquestador, interpretar_peticion
from .conocimiento.rutas import ErrorRuta, Jaula
from .conocimiento.vault import ErrorVault, Vault
from .modelo import ErrorOllama
from .zea_mayz.divulgacion import ErrorDivulgacion, generar_borrador
from .zea_mayz.validacion import validar_archivo

__all__ = ["anadir_ordenes", "SALIDA_CONOCIMIENTO"]

SALIDA_OK = 0
SALIDA_CONFIGURACION = 3
SALIDA_MODELO = 6
SALIDA_CONOCIMIENTO = 8


def anadir_ordenes(subordenes, preparar: Callable, formateador: type) -> None:
    """Registra `conocimiento`, `pedir` y `zea-mayz` en el analizador de `cli.py`."""

    def comunes(orden: argparse.ArgumentParser, modelo: bool = False) -> None:
        orden.add_argument(
            "--vault",
            metavar="RUTA",
            type=Path,
            default=None,
            help="Vault de Obsidian. Si se omite, el de TATEWARI_OBSIDIAN_VAULT.",
        )
        if modelo:
            orden.add_argument(
                "--modelo-extraccion",
                metavar="NOMBRE",
                default=None,
                dest="modelo_extraccion",
                help="Modelo de Ollama para leer los trozos (por defecto, el que entra en 4 GB).",
            )
            orden.add_argument(
                "--modelo-sintesis",
                metavar="NOMBRE",
                default=None,
                dest="modelo_sintesis",
                help="Modelo de Ollama para la síntesis (por defecto, el mismo).",
            )

    def nueva(padre, nombre: str, ayuda: str, descripcion: str) -> argparse.ArgumentParser:
        orden = padre.add_parser(
            nombre, help=ayuda, description=descripcion, formatter_class=formateador, add_help=False
        )
        preparar(orden)
        return orden

    # -- conocimiento -------------------------------------------------------
    conocimiento = nueva(
        subordenes,
        "conocimiento",
        "Knowledge Studio: documentos académicos a notas de Obsidian.",
        "Convierte documentos académicos (PDF, DOCX, PPTX, TXT, Markdown) en una base "
        "de conocimiento en un Vault de Obsidian, con el modelo local. Todo lo que genera "
        "el modelo entra en DRAFT o REVIEW y nunca pisa conocimiento aprobado.",
    )
    conocimiento.set_defaults(funcion=lambda a: (a.parser_propio.print_help(), SALIDA_OK)[1], parser_propio=conocimiento)
    acciones = conocimiento.add_subparsers(dest="accion", metavar="ACCIÓN")

    procesar = nueva(acciones, "procesar", "Procesa un documento.",
                     "Procesa un documento: extrae el texto, detecta el conocimiento con el "
                     "modelo local, escribe las notas en el Vault y un reporte.")
    procesar.add_argument("ruta", metavar="DOCUMENTO", type=Path, help="El documento a procesar.")
    procesar.add_argument("--sin-modelo", action="store_true", dest="sin_modelo",
                          help="No usa Ollama: solo extrae el texto, la nota de fuente y las referencias.")
    comunes(procesar, modelo=True)
    procesar.set_defaults(funcion=_procesar)

    materia = nueva(acciones, "materia", "Procesa todos los documentos de una carpeta.",
                    "Analiza una materia: procesa cada documento de la carpeta (por defecto, "
                    "la de materia del Vault) que no se haya procesado antes.")
    materia.add_argument("carpeta", metavar="CARPETA", nargs="?", type=Path, default=None,
                         help="Carpeta con los documentos. Por defecto, 01_MATERIA del Vault.")
    materia.add_argument("--forzar", action="store_true", help="Vuelve a procesar los ya procesados.")
    materia.add_argument("--sin-modelo", action="store_true", dest="sin_modelo",
                         help="No usa Ollama.")
    comunes(materia, modelo=True)
    materia.set_defaults(funcion=_materia)

    crear = nueva(acciones, "crear-vault", "Crea la estructura del Vault.",
                  "Crea la base de conocimiento: las carpetas (00_INBOX … 09_LIBRO por "
                  "defecto), las plantillas y la configuración. No toca nada que ya exista.")
    comunes(crear)
    crear.set_defaults(funcion=_crear_vault)

    actualizar = nueva(acciones, "actualizar", "Rehace enlaces e índice del Vault.",
                       "Actualiza el conocimiento existente sin modelo: vuelve a escribir las "
                       "notas de Tatewari que siguen intactas para resolver enlaces, y rehace "
                       "el índice. No toca notas aprobadas ni editadas a mano.")
    comunes(actualizar)
    actualizar.set_defaults(funcion=_actualizar)

    conceptos = nueva(acciones, "conceptos", "Muestra los conceptos detectados.",
                      "Lista las notas de conocimiento del Vault con su tipo y su estado.")
    conceptos.add_argument("--estado", choices=ESTADOS, default=None, help="Solo este estado.")
    conceptos.add_argument("--tipo", choices=TIPOS, default=None, help="Solo este tipo.")
    comunes(conceptos)
    conceptos.set_defaults(funcion=_conceptos)

    conflictos = nueva(acciones, "conflictos", "Muestra los conflictos entre fuentes.",
                       "Lista las notas donde dos fuentes dicen cosas distintas, con ambas "
                       "versiones. Tatewari no las resuelve: lo decide una persona.")
    comunes(conflictos)
    conflictos.set_defaults(funcion=_conflictos)

    reporte = nueva(acciones, "reporte", "Genera el reporte del Vault.",
                    "Valida el Vault y deja un reporte en la carpeta de reportes.")
    comunes(reporte)
    reporte.set_defaults(funcion=_reporte)

    validar = nueva(acciones, "validar", "Valida el Vault sin escribir nada.",
                    "Revisa estados, fuentes, duplicados, conflictos y enlaces pendientes. "
                    "No escribe nada.")
    comunes(validar)
    validar.set_defaults(funcion=_validar)

    buscar = nueva(acciones, "buscar", "Busca notas por contenido.", "Busca notas del Vault.")
    buscar.add_argument("texto", metavar="TEXTO", help="Lo que se busca.")
    comunes(buscar)
    buscar.set_defaults(funcion=_buscar)

    estado = nueva(acciones, "estado", "Cambia el estado de una nota.",
                   "Cambia el estado de una nota: DRAFT, REVIEW, APPROVED o PUBLISHED. "
                   "APPROVED y PUBLISHED exigen --autor: solo una persona aprueba.")
    estado.add_argument("nota", metavar="NOTA", help="Nombre de la nota.")
    estado.add_argument("nuevo", metavar="ESTADO", choices=ESTADOS, help="El estado nuevo.")
    estado.add_argument("--autor", metavar="NOMBRE", default="", help="Quién lo decide.")
    comunes(estado)
    estado.set_defaults(funcion=_estado)

    lista = nueva(acciones, "habilidades", "Lista las habilidades registradas.",
                  "Lista las habilidades (skills) que usa el orquestador.")
    lista.set_defaults(funcion=_habilidades)

    modelos = nueva(acciones, "modelos", "Muestra qué modelo hace cada tarea.",
                    "Pregunta a Ollama qué hay instalado y dice qué modelo usaría cada tarea.")
    comunes(modelos, modelo=True)
    modelos.set_defaults(funcion=_modelos)

    # -- pedir --------------------------------------------------------------
    pedir = nueva(subordenes, "pedir", "Pide algo en español: «procesa este documento X.pdf».",
                  "Interpreta una petición en español y lanza la acción que corresponde. "
                  "Ejemplos: «procesa este documento apuntes.pdf», «muestra los conflictos», "
                  "«genera el reporte».")
    pedir.add_argument("peticion", metavar="PETICIÓN", nargs="+", help="Lo que quieres que haga.")
    pedir.add_argument("--sin-modelo", action="store_true", dest="sin_modelo", help="No usa Ollama.")
    comunes(pedir, modelo=True)
    pedir.set_defaults(funcion=_pedir)

    # -- zea-mayz -----------------------------------------------------------
    zea = nueva(subordenes, "zea-mayz", "Divulgación científica desde conocimiento aprobado.",
                "Produce borradores narrativos (guion, storyboard, especificaciones de "
                "ilustración) solo a partir de conceptos APPROVED, y los valida.")
    zea.set_defaults(funcion=lambda a: (a.parser_propio.print_help(), SALIDA_OK)[1], parser_propio=zea)
    acciones_zea = zea.add_subparsers(dest="accion", metavar="ACCIÓN")

    divulgar = nueva(acciones_zea, "divulgar", "Escribe un borrador narrativo.",
                     "Escribe guion, storyboard y especificaciones de ilustración a partir "
                     "de conceptos APPROVED, y valida cada afirmación contra ellos.")
    divulgar.add_argument("--tema", default="", help="El tema del borrador.")
    divulgar.add_argument("--concepto", action="append", default=[], dest="conceptos",
                          metavar="NOTA", help="Un concepto aprobado a usar. Se puede repetir.")
    divulgar.add_argument("--publico", default="lectores de 10 a 14 años", help="A quién va dirigido.")
    divulgar.add_argument("--capitulos", type=int, default=1, help="Cuántos capítulos (por defecto 1).")
    comunes(divulgar, modelo=True)
    divulgar.set_defaults(funcion=_divulgar)

    validar_zea = nueva(acciones_zea, "validar", "Valida un borrador contra la base aprobada.",
                        "Comprueba que cada afirmación, recuadro y cifra del borrador tenga "
                        "base en conceptos APPROVED. No escribe nada.")
    validar_zea.add_argument("ruta", metavar="BORRADOR", type=Path, help="El guion a validar.")
    comunes(validar_zea)
    validar_zea.set_defaults(funcion=_validar_zea)


# ---------------------------------------------------------------------------
# Preparación común
# ---------------------------------------------------------------------------


def _orquestador(args: argparse.Namespace, crear: bool = False) -> tuple[Orquestador | None, int]:
    try:
        config = cargar_config()
    except ErrorConfig as error:
        print(error, file=sys.stderr)
        return None, SALIDA_CONFIGURACION
    try:
        vault = Vault.cargar(getattr(args, "vault", None) or config.vault, crear=crear)
        jaula = Jaula.para(vault.raiz, config.datos)
    except (ErrorVault, ErrorRuta) as error:
        print(error, file=sys.stderr)
        return None, SALIDA_CONOCIMIENTO

    enrutador = None
    if hasattr(args, "modelo_extraccion") and not getattr(args, "sin_modelo", False):
        enrutador = Enrutador.desde_config(
            config, extraccion=args.modelo_extraccion, sintesis=args.modelo_sintesis
        )
    return (
        Orquestador(
            vault=vault,
            jaula=jaula,
            enrutador=enrutador,
            sin_modelo=getattr(args, "sin_modelo", False),
            avance=lambda mensaje: print(mensaje, flush=True),
        ),
        SALIDA_OK,
    )


def _comprobar_modelo(orquestador: Orquestador) -> int:
    """Antes de procesar: que Ollama responda y el modelo exista. Si no, se dice ya."""
    if orquestador.enrutador is None:
        return SALIDA_OK
    try:
        print("Modelos:")
        print(orquestador.enrutador.describir())
        print()
    except ErrorOllama as error:
        print(error, file=sys.stderr)
        print(
            "\nPara procesar el documento sin modelo (solo texto, fuente y referencias), "
            "añade --sin-modelo.",
            file=sys.stderr,
        )
        return SALIDA_MODELO
    return SALIDA_OK


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------


def _procesar(args: argparse.Namespace) -> int:
    orquestador, codigo = _orquestador(args)
    if orquestador is None:
        return codigo
    codigo = _comprobar_modelo(orquestador)
    if codigo:
        return codigo
    try:
        reporte = orquestador.procesar_documento(args.ruta)
    except (ErrorDocumento, ErrorVault, ErrorRuta) as error:
        print(error, file=sys.stderr)
        return SALIDA_CONOCIMIENTO
    print()
    print(reporte.texto())
    if reporte.ruta_reporte:
        print()
        print(f"Reporte: {reporte.ruta_reporte}")
    print("Las notas nuevas están en DRAFT o REVIEW: revísalas antes de aprobarlas.")
    return SALIDA_OK


def _materia(args: argparse.Namespace) -> int:
    orquestador, codigo = _orquestador(args)
    if orquestador is None:
        return codigo
    codigo = _comprobar_modelo(orquestador)
    if codigo:
        return codigo
    try:
        resultados = orquestador.analizar_materia(args.carpeta, forzar=args.forzar)
    except ErrorVault as error:
        print(error, file=sys.stderr)
        return SALIDA_CONOCIMIENTO
    if not resultados:
        print("No hay documentos admitidos en la carpeta.")
    for resultado in resultados:
        print()
        if isinstance(resultado, tuple):
            print(f"{resultado[0]}: {resultado[1]}")
        else:
            print(resultado.texto())
    return SALIDA_OK


def _crear_vault(args: argparse.Namespace) -> int:
    orquestador, codigo = _orquestador(args, crear=True)
    if orquestador is None:
        return codigo
    try:
        creadas = orquestador.crear_base()
    except (ErrorVault, ErrorRuta) as error:
        print(error, file=sys.stderr)
        return SALIDA_CONOCIMIENTO
    print(f"Vault: {orquestador.vault.raiz}")
    print(f"Creado: {len(creadas)} carpetas y archivos (lo que ya existía no se ha tocado).")
    for nombre, carpeta in orquestador.vault.carpetas.items():
        print(f"  {nombre:<14} {carpeta}")
    print("\nAbre esa carpeta en Obsidian como Vault («Open folder as vault»).")
    return SALIDA_OK


def _actualizar(args: argparse.Namespace) -> int:
    orquestador, codigo = _orquestador(args)
    if orquestador is None:
        return codigo
    resultado = orquestador.actualizar()
    print("Enlaces e índice actualizados.")
    print(resultado.resumen())
    return SALIDA_OK


def _conceptos(args: argparse.Namespace) -> int:
    orquestador, codigo = _orquestador(args)
    if orquestador is None:
        return codigo
    notas = orquestador.conceptos(args.estado, args.tipo)
    if not notas:
        print("No hay conceptos que mostrar con ese filtro.")
        return SALIDA_OK
    print(f"{len(notas)} notas de conocimiento:\n")
    ancho = max(len(n.nombre) for n in notas)
    for nota in notas:
        conflicto = "  ⚠ conflicto" if nota.conflictos else ""
        print(f"  {nota.nombre.ljust(ancho)}  {nota.tipo:<12} {nota.estado:<9}{conflicto}")
    return SALIDA_OK


def _conflictos(args: argparse.Namespace) -> int:
    orquestador, codigo = _orquestador(args)
    if orquestador is None:
        return codigo
    notas = orquestador.conflictos()
    if not notas:
        print("No hay conflictos entre fuentes.")
        return SALIDA_OK
    for nota in notas:
        print(f"[[{nota.nombre}]] ({nota.estado})")
        for conflicto in nota.conflictos:
            print(f"  {conflicto.get('descripcion', 'Conflicto')}:")
            for version in conflicto.get("versiones", []):
                print(f"    - «{version.get('texto')}» — {version.get('documento')}, {version.get('ubicacion')}")
        print()
    print("Tatewari no elige una versión: revisa las fuentes y edita la nota a mano.")
    return SALIDA_OK


def _reporte(args: argparse.Namespace) -> int:
    orquestador, codigo = _orquestador(args)
    if orquestador is None:
        return codigo
    resultado, ruta = orquestador.reporte()
    print(resultado.resumen())
    if ruta:
        print(f"\nReporte: {ruta}")
    return SALIDA_OK


def _validar(args: argparse.Namespace) -> int:
    orquestador, codigo = _orquestador(args)
    if orquestador is None:
        return codigo
    resultado = orquestador.validar()
    print(resultado.resumen())
    for error in resultado.errores:
        print(f"  ✗ {error}")
    for aviso in resultado.avisos:
        print(f"  ! {aviso}")
    return SALIDA_OK if resultado.valida else SALIDA_CONOCIMIENTO


def _buscar(args: argparse.Namespace) -> int:
    orquestador, codigo = _orquestador(args)
    if orquestador is None:
        return codigo
    resultados = orquestador.vault.buscar_texto(args.texto)
    if not resultados:
        print("Ninguna nota lo menciona.")
    for nota, aciertos in resultados:
        print(f"  {nota.nombre}  ({nota.estado}, {aciertos} coincidencias)")
    return SALIDA_OK


def _estado(args: argparse.Namespace) -> int:
    orquestador, codigo = _orquestador(args)
    if orquestador is None:
        return codigo
    try:
        nota = orquestador.vault.cambiar_estado(orquestador.jaula, args.nota, args.nuevo, args.autor)
    except (ErrorEstado, ErrorVault, ErrorRuta) as error:
        print(error, file=sys.stderr)
        if isinstance(error, ErrorEstado) and not args.autor:
            print('Añade quién lo decide:  --autor "Tu nombre"', file=sys.stderr)
        return SALIDA_CONOCIMIENTO
    print(f"[[{nota.nombre}]] ahora está en {nota.estado}.")
    return SALIDA_OK


def _habilidades(args: argparse.Namespace) -> int:
    for h in habilidades():
        marcas = ", ".join(m for m, si in (("usa el modelo", h.usa_modelo), ("escribe", h.escribe)) if si)
        print(f"{h.nombre}{f'  [{marcas}]' if marcas else ''}")
        print(f"    {h.descripcion}")
    return SALIDA_OK


def _modelos(args: argparse.Namespace) -> int:
    try:
        config = cargar_config()
    except ErrorConfig as error:
        print(error, file=sys.stderr)
        return SALIDA_CONFIGURACION
    enrutador = Enrutador.desde_config(config, args.modelo_extraccion, args.modelo_sintesis)
    try:
        print(f"Ollama: {config.ollama}")
        print(enrutador.describir())
    except ErrorOllama as error:
        print(error, file=sys.stderr)
        return SALIDA_MODELO
    return SALIDA_OK


def _pedir(args: argparse.Namespace) -> int:
    texto = " ".join(args.peticion)
    peticion = interpretar_peticion(texto)
    if peticion is None:
        print(f"No entiendo «{texto}». Puedo hacer:", file=sys.stderr)
        for accion, frase in ACCIONES.items():
            print(f"  - {frase}", file=sys.stderr)
        print('Ejemplo:  python -m tatewari pedir "procesa este documento apuntes.pdf"', file=sys.stderr)
        return SALIDA_CONOCIMIENTO
    print(f"Entendido: {ACCIONES[peticion.accion]}" + (f" «{peticion.argumento}»" if peticion.argumento else ""))
    print()
    if peticion.accion == "procesar":
        if not peticion.argumento:
            print("¿Qué documento? Escribe su ruta, entre comillas si tiene espacios.", file=sys.stderr)
            return SALIDA_CONOCIMIENTO
        args.ruta = Path(peticion.argumento)
        return _procesar(args)
    if peticion.accion == "materia":
        args.carpeta = Path(peticion.argumento) if peticion.argumento else None
        args.forzar = False
        return _materia(args)
    if peticion.accion == "conceptos":
        args.estado, args.tipo = None, None
    manejadores = {
        "crear-vault": _crear_vault,
        "actualizar": _actualizar,
        "conceptos": _conceptos,
        "conflictos": _conflictos,
        "reporte": _reporte,
        "validar": _validar,
    }
    return manejadores[peticion.accion](args)


def _divulgar(args: argparse.Namespace) -> int:
    args.sin_modelo = False
    orquestador, codigo = _orquestador(args)
    if orquestador is None:
        return codigo
    try:
        resultado = generar_borrador(
            orquestador.vault,
            orquestador.jaula,
            orquestador.enrutador,
            tema=args.tema,
            nombres=args.conceptos,
            publico=args.publico,
            capitulos=max(1, args.capitulos),
        )
    except ErrorDivulgacion as error:
        print(error, file=sys.stderr)
        return SALIDA_CONOCIMIENTO
    except ErrorOllama as error:
        print(error, file=sys.stderr)
        return SALIDA_MODELO
    print(resultado.resumen())
    return SALIDA_OK


def _validar_zea(args: argparse.Namespace) -> int:
    orquestador, codigo = _orquestador(args)
    if orquestador is None:
        return codigo
    try:
        resultado = validar_archivo(args.ruta, orquestador.vault)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return SALIDA_CONOCIMIENTO
    print(resultado.resumen())
    return SALIDA_OK if resultado.valida else SALIDA_CONOCIMIENTO
