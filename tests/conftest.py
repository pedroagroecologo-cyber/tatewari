"""Configuración común de las pruebas.

Las pruebas corren **sin red** (AGENTS.md, regla 6): todo sale de
`protocolos/` y de `fixtures/`, nunca de una API.

`pyproject.toml` ya añade `src` al `pythonpath` de pytest; esto lo repite por
si alguien invoca pytest desde otra carpeta o con una configuración distinta.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
FUENTES = RAIZ / "src"

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
