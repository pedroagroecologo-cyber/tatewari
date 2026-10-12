"""Capa HTTP común: tiempo de espera, reintentos y fallo limpio.

Todas las fuentes pasan por aquí. La política es siempre la misma:

- **429 y 5xx**: se reintenta con espera creciente (1 s, 2 s, 4 s, 8 s…). Si la
  respuesta trae `Retry-After`, manda ese valor sobre la espera calculada.
- **4xx que no sea 429**: no se reintenta. Es un error nuestro (una URL mal
  construida, un DOI que no existe) y repetirlo solo gasta la cuota de un
  servicio gratuito.
- **Fallo de red o de espera agotada**: se reintenta como un 5xx.

Un error en una ecuación **no puede tumbar la cosecha entera**: quien llama
atrapa `ErrorHttp`, lo anota en la bitácora y sigue con la siguiente ecuación.
Por eso todos los fallos previsibles salen como `ErrorHttp` y no como una
excepción cualquiera de `requests`.

Las URL se construyen enteras en los módulos de cada fuente y se pasan aquí ya
formadas. **Nunca** se usa el parámetro `params=` de `requests`: convierte los
espacios en `+` dentro del valor de un filtro, y OpenAlex no lo interpreta como
espacio.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

from . import __version__

__all__ = [
    "ClienteHttp",
    "Cuota",
    "ErrorHttp",
    "ErrorHttpCliente",
    "ErrorHttpServidor",
    "ErrorRed",
    "AGENTE_USUARIO",
]

AGENTE_USUARIO = (
    f"Tatewari/{__version__} (revisión sistemática local; +https://github.com/tatewari)"
)

TIEMPO_ESPERA = 30.0
INTENTOS = 4
ESPERA_BASE = 1.0
ESPERA_MAXIMA = 60.0

CODIGOS_REINTENTABLES = frozenset({429, 500, 502, 503, 504})


class ErrorHttp(Exception):
    """Fallo al pedir una URL. Se anota en la bitácora y la cosecha continúa.

    `cuerpo` es lo que respondió el servidor, recortado. Se guarda porque a veces
    es lo único que explica el fallo: Ollama contesta 501 con «This server does
    not support embeddings» y sin ese texto solo se sabría que fue un 501.
    """

    def __init__(
        self,
        mensaje: str,
        url: str,
        estado: int | None = None,
        cuerpo: str = "",
    ) -> None:
        self.url = url
        self.estado = estado
        self.cuerpo = cuerpo
        super().__init__(mensaje)


class ErrorHttpCliente(ErrorHttp):
    """4xx: el problema está en la petición. No se reintenta."""


class ErrorHttpServidor(ErrorHttp):
    """5xx o 429 que no se recuperó tras agotar los reintentos."""


class ErrorRed(ErrorHttp):
    """No se pudo llegar al servidor: sin conexión, DNS o espera agotada."""


@dataclass(frozen=True)
class Cuota:
    """Lo que queda de cuota, leído de las cabeceras ``x-ratelimit-*``.

    OpenAlex las manda en cada respuesta y cobra por **créditos**, no por
    peticiones: medido el 2026-09-12, la cola anónima da 1000 créditos y cada
    petición gasta 10, o sea unas 100 peticiones por ventana. Una cosecha de 40
    ecuaciones con varias páginas cada una se come eso sin despeinarse, así que
    conviene mirarlo antes de seguir.

    Todos los campos pueden ser `None`: no todas las fuentes mandan cabeceras
    de cuota, y las que las mandan no siempre las mandan todas.
    """

    limite: int | None = None
    restante: int | None = None
    coste: int | None = None
    reinicio: int | None = None

    @property
    def hay_datos(self) -> bool:
        return self.restante is not None

    @property
    def peticiones_restantes(self) -> int | None:
        """Cuántas peticiones más caben, si se sabe el coste de cada una."""
        if self.restante is None:
            return None
        if not self.coste:
            return None
        return self.restante // self.coste

    def resumen(self) -> str:
        if not self.hay_datos:
            return "La fuente no informa de cuota."
        peticiones = self.peticiones_restantes
        texto = f"Cuota: quedan {self.restante}"
        if self.limite is not None:
            texto += f" de {self.limite}"
        if peticiones is not None:
            texto += f" (unas {peticiones} peticiones)"
        return texto + "."


def _entero_de_cabecera(cabeceras: Any, nombre: str) -> int | None:
    if not cabeceras:
        return None
    valor = cabeceras.get(nombre)
    if valor is None:
        return None
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


#: Cuánto del cuerpo de un error se guarda. Lo bastante para el mensaje del
#: servidor, no tanto como para volcar una página de error entera en la consola.
LIMITE_CUERPO = 500


def _cuerpo_de(respuesta: Any) -> str:
    """El texto que devolvió el servidor, recortado. Nunca falla.

    Un doble de pruebas puede no tener `text`, y leer el cuerpo de una respuesta
    a medio llegar puede lanzar: ninguna de las dos cosas puede tumbar el manejo
    del error que estamos construyendo.
    """
    try:
        texto = getattr(respuesta, "text", "") or ""
    except Exception:  # noqa: BLE001 - leer el cuerpo no puede romper nada
        return ""
    return " ".join(str(texto).split())[:LIMITE_CUERPO]


def leer_cuota(cabeceras: Any) -> Cuota:
    """Extrae la cuota de las cabeceras de una respuesta."""
    return Cuota(
        limite=_entero_de_cabecera(cabeceras, "x-ratelimit-limit"),
        restante=_entero_de_cabecera(cabeceras, "x-ratelimit-remaining"),
        coste=_entero_de_cabecera(cabeceras, "x-ratelimit-credits-used"),
        reinicio=_entero_de_cabecera(cabeceras, "x-ratelimit-reset"),
    )


@dataclass
class ClienteHttp:
    """Cliente HTTP con reintentos.

    `dormir` y `sesion` se inyectan para que las pruebas no esperen de verdad
    ni salgan a la red (AGENTS.md, regla 6).
    """

    tiempo_espera: float = TIEMPO_ESPERA
    intentos: int = INTENTOS
    espera_base: float = ESPERA_BASE
    espera_maxima: float = ESPERA_MAXIMA
    agente_usuario: str = AGENTE_USUARIO
    dormir: Callable[[float], None] = time.sleep
    sesion: Any | None = None
    esperas: list[float] = field(default_factory=list, repr=False)
    cuota: Cuota = field(default_factory=Cuota, repr=False)
    #: Token por nombre de servidor. Se manda como ``Authorization: Bearer`` y
    #: solo a ese servidor; la URL queda limpia para la bitácora.
    credenciales: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.sesion is None:
            self.sesion = requests.Session()
        self.sesion.headers.update({"User-Agent": self.agente_usuario})

    def obtener_json(self, url: str, tiempo_espera: float | None = None) -> dict:
        """Pide una URL con GET y devuelve el JSON.

        `tiempo_espera` sustituye al del cliente solo para esta llamada: una
        petición a la máquina local no necesita los mismos segundos que una a
        una API remota. Lanza `ErrorHttp` si no se puede.
        """
        return self._pedir("GET", url, None, tiempo_espera)

    def enviar_json(
        self, url: str, cuerpo: Any, tiempo_espera: float | None = None
    ) -> dict:
        """Manda `cuerpo` como JSON con POST y devuelve el JSON de respuesta.

        Existe para hablar con Ollama, que genera por POST. La política de
        reintentos es la misma que la del GET, y por eso está aquí y no en un
        cliente aparte: una sola política HTTP en todo el proyecto.
        """
        return self._pedir("POST", url, cuerpo, tiempo_espera)

    def _pedir(
        self,
        metodo: str,
        url: str,
        cuerpo: Any,
        tiempo_espera: float | None,
    ) -> dict:
        espera_maxima = (
            self.tiempo_espera if tiempo_espera is None else tiempo_espera
        )
        ultimo: ErrorHttp | None = None
        opciones: dict[str, Any] = {"timeout": espera_maxima}
        token = self.credenciales.get(urlsplit(url).hostname or "")
        if token:
            opciones["headers"] = {"Authorization": f"Bearer {token}"}

        for intento in range(1, self.intentos + 1):
            try:
                if metodo == "POST":
                    respuesta = self.sesion.post(url, json=cuerpo, **opciones)
                else:
                    respuesta = self.sesion.get(url, **opciones)
            except requests.RequestException as error:
                ultimo = ErrorRed(
                    f"No se pudo conectar con {url}: {error}", url=url
                )
                if intento == self.intentos:
                    break
                self._esperar(intento, None)
                continue

            estado = respuesta.status_code
            self.cuota = leer_cuota(getattr(respuesta, "headers", None))

            if 200 <= estado < 300:
                try:
                    return respuesta.json()
                except ValueError as error:
                    raise ErrorHttp(
                        f"La respuesta de {url} no es JSON válido: {error}",
                        url=url,
                        estado=estado,
                    ) from error

            cuerpo = _cuerpo_de(respuesta)

            if estado in CODIGOS_REINTENTABLES:
                ultimo = ErrorHttpServidor(
                    f"El servidor respondió {estado} en {url}.",
                    url=url,
                    estado=estado,
                    cuerpo=cuerpo,
                )
                if intento == self.intentos:
                    break
                self._esperar(intento, respuesta)
                continue

            if 400 <= estado < 500:
                raise ErrorHttpCliente(
                    f"Petición rechazada con {estado} en {url}. "
                    f"Revisa cómo se construyó la URL.",
                    url=url,
                    estado=estado,
                    cuerpo=cuerpo,
                )

            ultimo = ErrorHttpServidor(
                f"Respuesta inesperada {estado} en {url}.",
                url=url,
                estado=estado,
                cuerpo=cuerpo,
            )
            if intento == self.intentos:
                break
            self._esperar(intento, respuesta)

        assert ultimo is not None  # el bucle siempre deja algo aquí
        raise ultimo

    def _esperar(self, intento: int, respuesta: Any | None) -> None:
        """Espera creciente, respetando `Retry-After` si el servidor lo manda."""
        espera = min(self.espera_base * (2 ** (intento - 1)), self.espera_maxima)

        if respuesta is not None:
            cabecera = respuesta.headers.get("Retry-After") if respuesta.headers else None
            if cabecera:
                try:
                    espera = min(float(cabecera), self.espera_maxima)
                except ValueError:
                    # Retry-After también admite una fecha HTTP; si no es un
                    # número, nos quedamos con la espera calculada.
                    pass

        self.esperas.append(espera)
        self.dormir(espera)
