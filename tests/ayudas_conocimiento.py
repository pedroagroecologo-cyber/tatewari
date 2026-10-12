"""Ayudas de las pruebas de Knowledge Studio: respuestas del modelo simuladas.

Las respuestas imitan lo que devuelve un modelo local de verdad, incluidas sus
trampas: una cita que no está en el documento («Según Darwin…») y una referencia
bibliográfica inventada. Las pruebas comprueban que ninguna de las dos llega al
Vault con aspecto de hecho.
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "conocimiento"
EDAFOLOGIA = FIXTURES / "edafologia_unidad1.md"
OTRA_FUENTE = FIXTURES / "edafologia_otra_fuente.md"

#: Lo que devolvería el modelo para `edafologia_unidad1.md`, con dos trampas.
RESPUESTA_EDAFOLOGIA = {
    "suficiente": True,
    "motivo_insuficiente": "",
    "objetos": [
        {
            "titulo": "Suelo",
            "tipo": "concepto",
            "alias": ["suelos"],
            "resumen": "Cuerpo natural donde crecen las plantas.",
            "definicion": {
                "texto": "Cuerpo natural de minerales, materia orgánica, agua y aire.",
                "cita": "El suelo es un cuerpo natural formado por minerales, materia orgánica, agua y aire",
            },
            "relaciones": [
                {"tipo": "se forma a partir de", "destino": "Material parental"},
                {"tipo": "contiene", "destino": "Materia orgánica"},
            ],
            "etiquetas": ["edafología"],
            "confianza": 0.9,
        },
        {
            "titulo": "Horizonte A",
            "tipo": "concepto",
            "definicion": {
                "texto": "Capa superficial rica en materia orgánica, de 10 a 30 cm.",
                "cita": "El horizonte A es la capa superficial, rica en materia orgánica, y en los "
                "suelos de la región de estudio tiene un espesor típico de 10 a 30 cm",
            },
            "relaciones": [{"tipo": "es un tipo de", "destino": "Horizonte"}],
            "confianza": 0.85,
        },
        {
            "titulo": "Meteorización",
            "tipo": "proceso",
            "definicion": {
                "texto": "Descomposición física y química de las rocas.",
                "cita": "La meteorización es el proceso de descomposición física y química de las rocas",
            },
            "detalles": [
                {
                    "texto": "La física fragmenta la roca sin cambiar su composición.",
                    "cita": "La meteorización física fragmenta la roca sin cambiar su composición",
                },
                {"texto": "Es más rápida en climas tropicales.", "cita": "", "es_inferencia": True},
            ],
            "relaciones": [{"tipo": "da origen a", "destino": "Material parental"}],
            "confianza": 0.9,
        },
        {
            # Trampa: la cita no está en el documento.
            "titulo": "Materia orgánica",
            "tipo": "concepto",
            "definicion": {
                "texto": "Restos de plantas y animales.",
                "cita": "Según Darwin, la materia orgánica es el alma de todo suelo fértil",
            },
            "confianza": 0.95,
        },
    ],
    "referencias": [
        {"texto": "Pérez Ficticio, A. (2021). Manual ficticio de edafología. Editorial de Prueba."},
        # Trampa: referencia que no está en el documento.
        {"texto": "Smith, J. (2015). A totally invented reference about soils. Nature."},
    ],
}

#: La segunda fuente, que contradice la cifra del horizonte A.
RESPUESTA_OTRA_FUENTE = {
    "suficiente": True,
    "objetos": [
        {
            "titulo": "Horizonte A",
            "tipo": "concepto",
            "definicion": {
                "texto": "Capa superficial de 20 a 50 cm en las parcelas de campo.",
                "cita": "el horizonte A tiene un espesor típico de 20 a 50 cm",
            },
            "confianza": 0.8,
        }
    ],
}

RESPUESTA_INSUFICIENTE = {
    "suficiente": False,
    "motivo_insuficiente": "El fragmento solo trae un índice, sin definiciones.",
    "objetos": [],
}


def como_texto(respuesta: dict, envoltorio: str = "") -> str:
    """La respuesta como la escribiría el modelo, opcionalmente con texto alrededor."""
    crudo = json.dumps(respuesta, ensure_ascii=False)
    return f"{envoltorio}\n```json\n{crudo}\n```\nEspero que sirva." if envoltorio else crudo
