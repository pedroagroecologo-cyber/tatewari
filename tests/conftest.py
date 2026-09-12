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
