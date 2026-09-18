"""Configuración común de las pruebas.

Las pruebas corren **sin red** (AGENTS.md, regla 6): todo sale de
`protocolos/` y de `fixtures/`, nunca de una API.

`pyproject.toml` ya añade `src` al `pythonpath` de pytest; esto lo repite por
si alguien invoca pytest desde otra carpeta o con una configuración distinta.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[1]
FUENTES = RAIZ / "src"
RESPUESTAS = Path(__file__).resolve().parent / "respuestas"

if str(FUENTES) not in sys.path:
    sys.path.insert(0, str(FUENTES))


@pytest.fixture
def raiz() -> Path:
    """Raíz del repositorio."""
    return RAIZ


@pytest.fixture
def ruta_protocolo_humedales() -> Path:
    """Protocolo de ejemplo que se versiona en el repositorio."""
    return RAIZ / "protocolos" / "humedales.json"


@pytest.fixture
def ruta_fixture_demo() -> Path:
    """Fixture de registros sintéticos."""
    return RAIZ / "fixtures" / "demo.json"


class ClienteFalso:
    """Doble de `ClienteHttp` que nunca sale a la red (AGENTS.md, regla 6).

    Se le da una cola de respuestas: cada `obtener_json` devuelve la siguiente.
    Si en la cola hay una excepción, se lanza, que es como se prueban los
    fallos. Guarda las URL pedidas para poder comprobarlas.
    """

    def __init__(self, respuestas: list[Any] | None = None) -> None:
        self.respuestas = list(respuestas or [])
        self.urls: list[str] = []

    def obtener_json(self, url: str) -> Any:
        self.urls.append(url)
        if not self.respuestas:
            raise AssertionError(
                f"El cliente falso se quedó sin respuestas; se pidió {url}"
            )
        siguiente = self.respuestas.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente


def cargar_respuesta(nombre: str) -> dict:
    """Lee una respuesta de ejemplo de `tests/respuestas/`."""
    with open(RESPUESTAS / nombre, encoding="utf-8") as manejador:
        return json.load(manejador)


@pytest.fixture
def cliente_falso():
    """Fábrica de clientes falsos: `cliente_falso([respuesta1, respuesta2])`."""
    return ClienteFalso


@pytest.fixture
def respuesta():
    """Carga una respuesta de ejemplo por nombre de archivo."""
    return cargar_respuesta


@pytest.fixture
def protocolo(ruta_protocolo_humedales):
    """El protocolo de humedales ya validado."""
    from tatewari.protocolo import cargar_protocolo

    return cargar_protocolo(ruta_protocolo_humedales)


@pytest.fixture
def config_temporal(tmp_path):
    """Configuración que escribe en una carpeta temporal, con correo puesto."""
    from tatewari.config import Config

    return Config(
        mailto="prueba@ejemplo.invalid",
        ollama="http://localhost:11434",
        datos=tmp_path / "revisiones",
    )


class RespuestaFalsa:
    """Respuesta mínima con la forma que espera `ClienteHttp`.

    `text` existe porque `ErrorHttp` guarda el cuerpo de la respuesta: es lo
    único que distingue un «no soporta embeddings» de un 501 cualquiera.
    """

    def __init__(self, estado: int = 200, datos: Any = None) -> None:
        self.status_code = estado
        self._datos = {} if datos is None else datos
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        return self._datos

    @property
    def text(self) -> str:
        return json.dumps(self._datos, ensure_ascii=False)


#: Lo que contesta Ollama cuando el modelo cargado no genera vectores. Es el
#: texto literal, medido el 2026-09-12 pidiéndole un vector a `qwen3:4b`.
_ERROR_SIN_SOPORTE = (
    "This server does not support embeddings. Start it with `--embeddings`"
)


def _vector_por_defecto(texto: str) -> list[float]:
    """Un vector determinista derivado del texto, de ocho dimensiones.

    Sirve para las pruebas que solo necesitan *algún* vector estable: la caché,
    el recuento, el aviso de baja calidad. Las que comprueban un orden pasan su
    propia función, porque el parecido entre estos vectores no significa nada.
    """
    from hashlib import sha256

    digest = sha256(texto.encode("utf-8")).digest()
    return [b / 255 for b in digest[:8]]


def modelo_falso(
    nombre: str,
    tamano: str = "3.2B",
    cuantizacion: str = "Q4_K_M",
    bytes_en_disco: int = 2_000_000_000,
    familia: str = "llama",
) -> dict:
    """Una entrada de `/api/tags` con la forma que devuelve Ollama de verdad."""
    return {
        "name": nombre,
        "model": nombre,
        "size": bytes_en_disco,
        "details": {
            "parameter_size": tamano,
            "quantization_level": cuantizacion,
            "family": familia,
        },
    }


class SesionOllamaFalsa:
    """Doble de `requests.Session` que finge ser Ollama.

    Las pruebas corren **sin Ollama instalado y sin red** (AGENTS.md, regla 6).
    Este doble responde a `/api/tags` con los modelos que se le den y a
    `/api/generate` con las respuestas de una cola.

    Cada elemento de `respuestas` puede ser:

    - un **texto**: se devuelve como el campo ``response`` de la generación;
    - un **diccionario**: se devuelve tal cual, para probar formas raras como la
      del modelo de razonamiento que deja ``response`` vacío;
    - una **excepción**: se lanza, que es como se prueba que Ollama no responde.

    Guarda todas las peticiones para poder comprobar qué se le pidió: que la
    temperatura iba a 0, que `num_ctx` iba explícito, y que no se preguntó dos
    veces por lo mismo.
    """

    def __init__(
        self,
        modelos: list[dict] | None = None,
        respuestas: list[Any] | None = None,
        vector_de: Any = None,
        soporta_embed: bool = True,
        soporta_embeddings: bool = True,
        sin_soporte: bool = False,
    ) -> None:
        self.modelos = list(modelos or [])
        self.respuestas = list(respuestas or [])
        self.peticiones: list[tuple[str, str, Any]] = []
        self.headers: dict[str, str] = {}
        #: Qué vector se devuelve para cada texto. Por defecto, uno derivado del
        #: propio texto: determinista, pero sin parecidos con sentido. Las
        #: pruebas de orden pasan el suyo.
        self.vector_de = vector_de or _vector_por_defecto
        #: `False` finge un Ollama viejo, sin la ruta nueva `/api/embed`.
        self.soporta_embed = soporta_embed
        self.soporta_embeddings = soporta_embeddings
        #: `True` finge lo que contesta Ollama cuando el modelo cargado no sabe
        #: generar vectores: 501 y «This server does not support embeddings».
        self.sin_soporte = sin_soporte
        #: Los textos que se han vectorizado, en orden. Es lo que prueba que la
        #: caché funciona: un texto que no cambió no puede volver a aparecer aquí.
        self.textos_vectorizados: list[str] = []

    @property
    def cuerpos(self) -> list[Any]:
        """Los cuerpos de los POST, en orden."""
        return [cuerpo for metodo, _, cuerpo in self.peticiones if metodo == "POST"]

    @property
    def veces_tags(self) -> int:
        return sum(1 for _, url, _ in self.peticiones if url.endswith("/api/tags"))

    def get(self, url: str, timeout: float | None = None) -> RespuestaFalsa:
        self.peticiones.append(("GET", url, None))
        if url.endswith("/api/tags"):
            return RespuestaFalsa(200, {"models": self.modelos})
        return RespuestaFalsa(404, {"error": "not found"})

    def post(
        self, url: str, json: Any = None, timeout: float | None = None
    ) -> RespuestaFalsa:
        self.peticiones.append(("POST", url, json))
        cuerpo = json or {}

        if url.endswith("/api/embed"):
            if not self.soporta_embed:
                return RespuestaFalsa(404, {"error": "not found"})
            if self.sin_soporte:
                return RespuestaFalsa(501, {"error": _ERROR_SIN_SOPORTE})
            entradas = cuerpo.get("input") or []
            if isinstance(entradas, str):
                entradas = [entradas]
            self.textos_vectorizados.extend(entradas)
            return RespuestaFalsa(
                200,
                {
                    "model": cuerpo.get("model", "NR"),
                    "embeddings": [self.vector_de(t) for t in entradas],
                },
            )

        if url.endswith("/api/embeddings"):
            if not self.soporta_embeddings:
                return RespuestaFalsa(404, {"error": "not found"})
            if self.sin_soporte:
                return RespuestaFalsa(500, {"error": _ERROR_SIN_SOPORTE})
            texto = cuerpo.get("prompt") or ""
            self.textos_vectorizados.append(texto)
            return RespuestaFalsa(200, {"embedding": self.vector_de(texto)})

        if not self.respuestas:
            raise AssertionError(
                f"El Ollama falso se quedó sin respuestas; se pidió {url}"
            )
        siguiente = self.respuestas.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        if isinstance(siguiente, dict):
            return RespuestaFalsa(200, siguiente)
        return RespuestaFalsa(
            200,
            {
                "response": siguiente,
                "model": (json or {}).get("model", "NR"),
                "total_duration": 1_500_000_000,
                "eval_count": 20,
            },
        )


@pytest.fixture
def sesion_ollama():
    """La clase del doble, para montarlo a mano en una prueba."""
    return SesionOllamaFalsa


@pytest.fixture
def tags_falsos():
    """Fábrica de entradas de `/api/tags`."""
    return modelo_falso


@pytest.fixture
def ollama():
    """Fábrica de `ClienteOllama` conectado a un Ollama falso.

    Devuelve `(cliente, sesion)`: la sesión sirve para comprobar después qué se
    le pidió. El cliente no duerme de verdad entre reintentos.
    """
    from tatewari.http import ClienteHttp
    from tatewari.modelo import ClienteOllama

    def fabrica(
        modelos: list[dict] | None = None,
        respuestas: list[Any] | None = None,
        modelo: str | None = None,
        sesion: Any = None,
        **extra: Any,
    ):
        if modelos is None:
            modelos = [modelo_falso("llama3.2:3b")]
        if sesion is None:
            sesion = SesionOllamaFalsa(modelos=modelos, respuestas=respuestas)
        cliente = ClienteOllama(
            direccion="http://localhost:11434",
            modelo=modelo,
            cliente=ClienteHttp(sesion=sesion, dormir=lambda _: None, intentos=2),
            **extra,
        )
        return cliente, sesion

    return fabrica


@pytest.fixture
def embeddings(ollama):
    """Fábrica de `ClienteEmbeddings` contra un Ollama falso.

    Devuelve `(cliente, sesion)`. Las pruebas corren **sin Ollama y sin el modelo
    de embeddings descargado** (AGENTS.md, regla 6).
    """
    from tatewari.embeddings import MODELO_EMBED_POR_DEFECTO, ClienteEmbeddings

    def fabrica(
        vector_de: Any = None,
        modelo: str = MODELO_EMBED_POR_DEFECTO,
        instalado: bool = True,
        modelos: list[dict] | None = None,
        **extra: Any,
    ):
        if modelos is None:
            modelos = [modelo_falso(modelo, "137M", "F16")] if instalado else []
            modelos.append(modelo_falso("llama3.2:3b"))
        sesion = SesionOllamaFalsa(
            modelos=modelos, vector_de=vector_de, **extra
        )
        cliente_ollama, _ = ollama(sesion=sesion)
        return ClienteEmbeddings(ollama=cliente_ollama, modelo=modelo), sesion

    return fabrica


@pytest.fixture
def protocolo_minimo() -> dict:
    """Protocolo válido más pequeño posible, para retocar en cada prueba."""
    return {
        "titulo": "Protocolo mínimo de prueba",
        "ventana": [2016, 2026],
        "idiomas": ["es", "en"],
        "tipos": ["article"],
        "bloques": {
            "B1": ["alfa", "beta"],
            "B2": ["gamma"],
        },
    }
