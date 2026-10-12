"""La orden `tatewari interfaz`: arranca el servidor local y abre el navegador."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path
from typing import Callable

from ..config import ErrorConfig, cargar_config
from .servicio import Servicio
from .servidor import Trabajos, crear_servidor, tarea_precargar

__all__ = ["anadir_orden", "PUERTO_POR_DEFECTO"]

PUERTO_POR_DEFECTO = 8765
_INTENTOS_DE_PUERTO = 10


def anadir_orden(subordenes, preparar: Callable, formateador: type) -> None:
    orden = subordenes.add_parser(
        "interfaz",
        help="Abre la interfaz gráfica en el navegador.",
        description=(
            "Abre la interfaz de Tatewari: una biblioteca de tres paneles (colecciones, "
            "elementos y ficha) con tus revisiones y tu Vault de Obsidian. Corre solo en "
            "esta computadora (127.0.0.1) y, al arrancar, carga el modelo local en la "
            "tarjeta para que el primer documento no espere."
        ),
        formatter_class=formateador,
        add_help=False,
    )
    preparar(orden)
    orden.add_argument("--puerto", type=int, default=PUERTO_POR_DEFECTO, help=f"Puerto local (por defecto {PUERTO_POR_DEFECTO}).")
    orden.add_argument("--vault", metavar="RUTA", type=Path, default=None, help="Vault de Obsidian. Si se omite, el de TATEWARI_OBSIDIAN_VAULT.")
    orden.add_argument("--no-abrir", action="store_true", dest="no_abrir", help="No abre el navegador; solo imprime la dirección.")
    orden.add_argument("--sin-precarga", action="store_true", dest="sin_precarga", help="No carga el modelo en la tarjeta al arrancar.")
    orden.add_argument(
        "--esperar-ollama", type=int, default=0, metavar="SEGUNDOS", dest="esperar_ollama",
        help="Espera hasta estos segundos a que Ollama responda (lo usa el lanzador al abrirlo).",
    )
    orden.set_defaults(funcion=_interfaz)


def _esperar_ollama(direccion: str, segundos: int) -> bool:
    """Espera a que Ollama conteste. Devuelve si llegó a contestar."""
    import time

    import requests

    limite = time.monotonic() + segundos
    avisado = False
    while True:
        try:
            requests.get(f"{direccion.rstrip('/')}/api/version", timeout=2)
            return True
        except requests.RequestException:
            if time.monotonic() >= limite:
                return False
            if not avisado:
                print("Esperando a que Ollama arranque…", flush=True)
                avisado = True
            time.sleep(1)


def _interfaz(args: argparse.Namespace) -> int:
    try:
        config = cargar_config()
    except ErrorConfig as error:
        print(error, file=sys.stderr)
        return 3

    if args.esperar_ollama > 0 and not _esperar_ollama(config.ollama, args.esperar_ollama):
        print("Ollama no respondió a tiempo. La interfaz abre igual; el modelo se cargará cuando Ollama esté listo.")

    servicio = Servicio(config=config, vault_ruta=args.vault)
    trabajos = Trabajos()
    servidor = None
    for puerto in range(args.puerto, args.puerto + _INTENTOS_DE_PUERTO):
        try:
            servidor, clave = crear_servidor(servicio, trabajos, puerto=puerto)
            break
        except OSError:
            continue
    if servidor is None:
        print(
            f"No hay ningún puerto libre entre {args.puerto} y {args.puerto + _INTENTOS_DE_PUERTO - 1}. "
            f"¿Ya hay una interfaz abierta? Prueba con --puerto 9000.",
            file=sys.stderr,
        )
        return 1

    direccion = f"http://127.0.0.1:{servidor.server_address[1]}/#t={clave}"
    print("Tatewari — interfaz local")
    print(f"  Dirección : {direccion}")
    print(f"  Vault     : {servicio.vault_ruta or '(sin configurar: elígelo en la interfaz)'}")
    print(f"  Datos     : {config.datos}")
    print("  Solo se puede abrir desde esta computadora. Ctrl+C para cerrarla.")
    print()

    if not args.sin_precarga:
        trabajos.aparte("Cargar el modelo", tarea_precargar(servicio))
        print("Cargando el modelo local en la tarjeta (se ve en la barra de abajo)…")
    if not args.no_abrir:
        webbrowser.open(direccion)

    try:
        servidor.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nInterfaz cerrada.")
    finally:
        servidor.server_close()
    return 0
