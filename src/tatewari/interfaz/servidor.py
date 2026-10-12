"""El servidor local de la interfaz y la cola de trabajos largos.

Seguridad, en corto: escucha solo en ``127.0.0.1``; cada arranque genera una
clave que la página recibe en la dirección (``#t=…``, que el navegador no manda
nunca al servidor) y que toda llamada a ``/api`` tiene que llevar en la
cabecera ``X-Tatewari-Clave``. Además se comprueba la cabecera ``Host`` (contra
el *DNS rebinding*) y el ``Origin`` de las escrituras. Una página web cualquiera
abierta en el mismo navegador no puede leer ni cambiar nada.

Los trabajos largos que escriben (procesar un documento, analizar la materia,
divulgar) van a una cola con **un solo** hilo: nunca hay dos escribiendo en el
Vault a la vez. Precargar el modelo va aparte, en su propio hilo, porque no
escribe nada y puede tardar minutos si la tarjeta está ocupada.
"""

from __future__ import annotations

import hmac
import json
import mimetypes
import queue
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from ..conocimiento.documento import ErrorDocumento
from ..conocimiento.ingesta import TAMANO_MAXIMO
from ..conocimiento.reporte import ReporteProcesamiento
from ..conocimiento.rutas import ErrorRuta
from ..conocimiento.vault import ErrorVault
from ..modelo import ErrorOllama
from ..zea_mayz.divulgacion import ErrorDivulgacion, generar_borrador
from .servicio import ErrorInterfaz, Servicio

__all__ = ["Trabajo", "Trabajos", "crear_servidor", "CABECERA_CLAVE"]

CABECERA_CLAVE = "X-Tatewari-Clave"
MAXIMO_JSON = 1024 * 1024
_ESTATICOS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/estatico/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/estatico/estilo.css": ("estilo.css", "text/css; charset=utf-8"),
}
_POLITICA = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-src 'self'; object-src 'self'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)


# ---------------------------------------------------------------------------
# Trabajos
# ---------------------------------------------------------------------------


@dataclass
class Trabajo:
    id: str
    titulo: str
    tarea: Callable[["Trabajo"], str]
    estado: str = "en_cola"  # en_cola | en_curso | hecho | fallo
    lineas: list[str] = field(default_factory=list)
    resultado: str = ""
    creado: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    segundos: float = 0.0
    al_terminar: Callable[[], None] | None = None

    def decir(self, mensaje: str) -> None:
        self.lineas.append(mensaje)
        del self.lineas[:-200]

    def como_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "titulo": self.titulo,
            "estado": self.estado,
            "lineas": self.lineas[-40:],
            "resultado": self.resultado,
            "creado": self.creado,
            "segundos": round(self.segundos, 1),
        }


class Trabajos:
    """Una cola con un solo trabajador. Recuerda los últimos trabajos para mostrarlos."""

    def __init__(self, recordar: int = 30) -> None:
        self._cola: queue.Queue[Trabajo] = queue.Queue()
        self._todos: list[Trabajo] = []
        self._recordar = recordar
        self._cerrojo = threading.Lock()
        self._hilo = threading.Thread(target=self._trabajar, name="tatewari-trabajos", daemon=True)
        self._hilo.start()

    def encolar(
        self, titulo: str, tarea: Callable[[Trabajo], str], al_terminar: Callable[[], None] | None = None
    ) -> Trabajo:
        trabajo = Trabajo(id=secrets.token_hex(6), titulo=titulo, tarea=tarea, al_terminar=al_terminar)
        with self._cerrojo:
            self._todos.append(trabajo)
            del self._todos[: -self._recordar]
        self._cola.put(trabajo)
        return trabajo

    def aparte(self, titulo: str, tarea: Callable[[Trabajo], str]) -> Trabajo:
        """Un trabajo que no escribe en el Vault y corre en su propio hilo, fuera de la cola.

        Es para precargar el modelo: si Ollama tarda minutos en cargarlo (la
        tarjeta ocupada por otro programa), no debe bloquear el procesamiento de
        documentos, que de todos modos esperará a Ollama por su cuenta.
        """
        trabajo = Trabajo(id=secrets.token_hex(6), titulo=titulo, tarea=tarea)
        with self._cerrojo:
            self._todos.append(trabajo)
            del self._todos[: -self._recordar]
        threading.Thread(target=self._ejecutar, args=(trabajo,), name="tatewari-aparte", daemon=True).start()
        return trabajo

    def lista(self) -> list[dict[str, Any]]:
        with self._cerrojo:
            return [t.como_dict() for t in reversed(self._todos)]

    def esperar(self, tiempo: float = 30.0) -> None:
        """Para las pruebas: espera a que la cola se vacíe."""
        limite = time.monotonic() + tiempo
        while time.monotonic() < limite:
            with self._cerrojo:
                pendientes = [t for t in self._todos if t.estado in ("en_cola", "en_curso")]
            if not pendientes:
                return
            time.sleep(0.02)
        raise TimeoutError("Los trabajos no terminaron a tiempo.")

    def _trabajar(self) -> None:
        while True:
            trabajo = self._cola.get()
            try:
                self._ejecutar(trabajo)
            finally:
                self._cola.task_done()

    @staticmethod
    def _ejecutar(trabajo: Trabajo) -> None:
        trabajo.estado = "en_curso"
        inicio = time.monotonic()
        try:
            trabajo.resultado = trabajo.tarea(trabajo)
            trabajo.estado = "hecho"
        except (ErrorInterfaz, ErrorDocumento, ErrorVault, ErrorRuta, ErrorOllama, ErrorDivulgacion, OSError) as error:
            trabajo.resultado = str(error)
            trabajo.estado = "fallo"
        except Exception as error:  # que un fallo inesperado no mate al trabajador
            trabajo.resultado = f"Fallo inesperado: {type(error).__name__}: {error}"
            trabajo.estado = "fallo"
        finally:
            trabajo.segundos = time.monotonic() - inicio
            if trabajo.al_terminar is not None:
                try:
                    trabajo.al_terminar()
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Tareas
# ---------------------------------------------------------------------------


def _texto_reporte(reporte: ReporteProcesamiento) -> str:
    return reporte.texto()


def tarea_procesar(servicio: Servicio, ruta: Path) -> Callable[[Trabajo], str]:
    def tarea(trabajo: Trabajo) -> str:
        orquestador = servicio.orquestador(avance=trabajo.decir)
        return _texto_reporte(orquestador.procesar_documento(ruta))

    return tarea


def tarea_materia(servicio: Servicio) -> Callable[[Trabajo], str]:
    def tarea(trabajo: Trabajo) -> str:
        resultados = servicio.orquestador(avance=trabajo.decir).analizar_materia()
        if not resultados:
            return "No hay documentos admitidos en la carpeta de materia."
        partes = []
        for resultado in resultados:
            partes.append(f"{resultado[0]}: {resultado[1]}" if isinstance(resultado, tuple) else resultado.texto())
        return "\n\n".join(partes)

    return tarea


def tarea_divulgar(servicio: Servicio, tema: str, publico: str) -> Callable[[Trabajo], str]:
    def tarea(trabajo: Trabajo) -> str:
        trabajo.decir("Escribiendo el borrador con los conceptos aprobados…")
        orquestador = servicio.orquestador()
        resultado = generar_borrador(
            orquestador.vault, orquestador.jaula, servicio.enrutador, tema=tema, publico=publico or "lectores de 10 a 14 años"
        )
        return resultado.resumen()

    return tarea


def tarea_precargar(servicio: Servicio) -> Callable[[Trabajo], str]:
    def tarea(trabajo: Trabajo) -> str:
        trabajo.decir("Cargando el modelo en la tarjeta gráfica…")
        try:
            nombre = servicio.precargar()
        except ErrorOllama as error:
            raise ErrorInterfaz(
                f"{error}\n\nSi Ollama tarda minutos en cargar un modelo pequeño, mira si otro "
                f"programa está usando la tarjeta gráfica (un juego, LM Studio…): con 4 GB de "
                f"VRAM no caben a la vez. Puedes seguir usando la interfaz; los documentos "
                f"esperarán a que el modelo esté listo."
            ) from error
        return f"{nombre} está cargado y listo."

    return tarea


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _estatico(nombre: str) -> bytes:
    return resources.files("tatewari.interfaz").joinpath("estatico", nombre).read_bytes()


def crear_servidor(
    servicio: Servicio,
    trabajos: Trabajos,
    puerto: int = 8765,
    clave: str | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    """Monta el servidor en 127.0.0.1. Devuelve el servidor y la clave de la sesión."""
    clave = clave or secrets.token_urlsafe(24)

    class Manejador(BaseHTTPRequestHandler):
        server_version = "Tatewari"
        sys_version = ""

        # -- Respuestas ---------------------------------------------------

        def log_message(self, formato: str, *argumentos: Any) -> None:  # silencio en consola
            return

        def _cabeceras_comunes(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")

        def _json(self, datos: Any, estado: int = 200) -> None:
            cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
            self.send_response(estado)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self._cabeceras_comunes()
            self.end_headers()
            self.wfile.write(cuerpo)

        def _error(self, mensaje: str, estado: int = 400) -> None:
            self._json({"error": mensaje}, estado)

        # -- Comprobaciones -------------------------------------------------

        def _host_valido(self) -> bool:
            puerto_real = self.server.server_address[1]
            host = (self.headers.get("Host") or "").lower()
            return host in (f"127.0.0.1:{puerto_real}", f"localhost:{puerto_real}")

        def _origen_valido(self) -> bool:
            origen = self.headers.get("Origin")
            if origen is None:
                return True
            puerto_real = self.server.server_address[1]
            return origen.lower() in (f"http://127.0.0.1:{puerto_real}", f"http://localhost:{puerto_real}")

        def _clave_valida(self) -> bool:
            recibida = self.headers.get(CABECERA_CLAVE) or ""
            if not recibida:
                galleta = self.headers.get("Cookie") or ""
                for parte in galleta.split(";"):
                    nombre, _, valor = parte.strip().partition("=")
                    if nombre == "tatewari_clave":
                        recibida = valor
            return hmac.compare_digest(recibida.encode(), clave.encode())

        def _leer_json(self) -> dict[str, Any]:
            largo = int(self.headers.get("Content-Length") or 0)
            if largo > MAXIMO_JSON:
                raise ErrorInterfaz("La petición es demasiado grande.")
            crudo = self.rfile.read(largo) if largo else b"{}"
            try:
                datos = json.loads(crudo.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ErrorInterfaz("La petición no es JSON válido.") from error
            if not isinstance(datos, dict):
                raise ErrorInterfaz("La petición tiene que ser un objeto JSON.")
            return datos

        # -- GET ------------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802 - nombre de la biblioteca estándar
            if not self._host_valido():
                return self._error("Host no permitido.", HTTPStatus.FORBIDDEN)
            url = urlparse(self.path)
            if url.path in _ESTATICOS:
                nombre, tipo = _ESTATICOS[url.path]
                cuerpo = _estatico(nombre)
                self.send_response(200)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(cuerpo)))
                self.send_header("Content-Security-Policy", _POLITICA)
                self.send_header("X-Frame-Options", "DENY")
                self._cabeceras_comunes()
                self.end_headers()
                self.wfile.write(cuerpo)
                return None
            if not self._clave_valida():
                return self._error("Falta la clave de esta sesión. Abre la interfaz desde «tatewari interfaz».", HTTPStatus.UNAUTHORIZED)
            parametros = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path == "/archivo":
                    return self._archivo(servicio.ruta_de_archivo(parametros.get("ruta", "")))
                respuesta = self._get_api(url.path, parametros)
            except ErrorInterfaz as error:
                return self._error(str(error))
            if respuesta is None:
                return self._error("No existe esa dirección.", HTTPStatus.NOT_FOUND)
            return self._json(respuesta)

        def _get_api(self, ruta: str, p: dict[str, str]) -> Any:
            if ruta == "/api/estado":
                return servicio.estado()
            if ruta == "/api/modelos":
                return servicio.modelos()
            if ruta == "/api/colecciones":
                return servicio.colecciones()
            if ruta == "/api/elementos":
                return servicio.elementos(p.get("coleccion", ""), p.get("q", ""))
            if ruta == "/api/elemento":
                return servicio.elemento(p.get("coleccion", ""), p.get("id", ""))
            if ruta == "/api/nota":
                return servicio.buscar_nota(p.get("nombre", ""))
            if ruta == "/api/trabajos":
                return trabajos.lista()
            return None

        def _archivo(self, ruta: Path) -> None:
            tipo = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
            if tipo.startswith("text/"):
                tipo += "; charset=utf-8"
            cuerpo = ruta.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            if "html" in tipo or "svg" in tipo or "xml" in tipo:
                # Un documento que pueda ejecutar código se abre aislado. Un PDF
                # no: el visor del navegador no funciona en modo aislado.
                self.send_header("Content-Security-Policy", "sandbox")
            self._cabeceras_comunes()
            self.end_headers()
            self.wfile.write(cuerpo)

        # -- POST -----------------------------------------------------------

        def do_POST(self) -> None:  # noqa: N802
            if not self._host_valido() or not self._origen_valido():
                return self._error("Origen no permitido.", HTTPStatus.FORBIDDEN)
            url = urlparse(self.path)
            if url.path == "/api/sesion":
                return self._sesion()
            if not self._clave_valida() or not self.headers.get(CABECERA_CLAVE):
                return self._error("Falta la clave de esta sesión.", HTTPStatus.UNAUTHORIZED)
            parametros = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path == "/api/subir":
                    return self._json(self._subir(parametros.get("nombre", "")))
                datos = self._leer_json()
                respuesta = self._post_api(url.path, datos)
            except ErrorInterfaz as error:
                return self._error(str(error))
            if respuesta is None:
                return self._error("No existe esa dirección.", HTTPStatus.NOT_FOUND)
            return self._json(respuesta)

        def _sesion(self) -> None:
            """Cambia la clave de la dirección por una galleta, para abrir archivos con un enlace."""
            if not hmac.compare_digest((self.headers.get(CABECERA_CLAVE) or "").encode(), clave.encode()):
                return self._error("Clave incorrecta.", HTTPStatus.UNAUTHORIZED)
            cuerpo = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Set-Cookie", f"tatewari_clave={clave}; HttpOnly; SameSite=Strict; Path=/")
            self._cabeceras_comunes()
            self.end_headers()
            self.wfile.write(cuerpo)
            return None

        def _subir(self, nombre: str) -> dict[str, Any]:
            largo = int(self.headers.get("Content-Length") or 0)
            if largo > TAMANO_MAXIMO:
                raise ErrorInterfaz(f"El archivo pasa de {TAMANO_MAXIMO // (1024 * 1024)} MB.")
            servicio.orquestador()  # sin Vault no se acepta nada
            ruta = servicio.guardar_subida(nombre, self.rfile.read(largo))
            trabajo = trabajos.encolar(
                f"Procesar «{ruta.name}»",
                tarea_procesar(servicio, ruta),
                al_terminar=lambda: shutil.rmtree(ruta.parent, ignore_errors=True),
            )
            return trabajo.como_dict()

        def _post_api(self, ruta: str, d: dict[str, Any]) -> Any:
            if ruta == "/api/decidir":
                return servicio.decidir(
                    str(d.get("revision", "")), str(d.get("id", "")), str(d.get("decision", "")),
                    str(d.get("motivo", "")), str(d.get("autor", "")),
                )
            if ruta == "/api/estado-nota":
                return servicio.cambiar_estado(str(d.get("id", "")), str(d.get("estado", "")), str(d.get("autor", "")))
            if ruta == "/api/vault":
                return servicio.elegir_vault(str(d.get("ruta", "")), bool(d.get("recordar")))
            if ruta == "/api/procesar":
                texto = str(d.get("ruta", "")).strip().strip('"')
                if not texto:
                    raise ErrorInterfaz("Escribe la ruta del documento.")
                servicio.orquestador()
                documento = Path(texto)
                return trabajos.encolar(f"Procesar «{documento.name}»", tarea_procesar(servicio, documento)).como_dict()
            if ruta == "/api/materia":
                servicio.orquestador()
                return trabajos.encolar("Analizar la materia", tarea_materia(servicio)).como_dict()
            if ruta == "/api/divulgar":
                servicio.orquestador()
                tema = str(d.get("tema", "")).strip()
                return trabajos.encolar(
                    f"Divulgar «{tema or 'toda la base aprobada'}»",
                    tarea_divulgar(servicio, tema, str(d.get("publico", "")).strip()),
                ).como_dict()
            if ruta == "/api/precargar":
                return trabajos.aparte("Cargar el modelo", tarea_precargar(servicio)).como_dict()
            if ruta == "/api/validar":
                resultado = servicio.orquestador().validar()
                return {"resumen": resultado.resumen(), "errores": resultado.errores, "avisos": resultado.avisos}
            return None

    servidor = _Servidor(("127.0.0.1", puerto), Manejador)
    return servidor, clave


class _Servidor(ThreadingHTTPServer):
    # En Windows, SO_REUSEADDR deja que dos programas escuchen en el mismo
    # puerto sin error: una segunda interfaz se colaría en el de la primera.
    allow_reuse_address = False
    daemon_threads = True
