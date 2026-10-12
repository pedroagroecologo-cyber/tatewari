"""Análisis con el modelo local: de trozos de texto a objetos de conocimiento.

El modelo recibe un trozo y devuelve JSON. Lo que devuelve **no se cree**:

1. Se extrae el primer objeto JSON útil, aunque venga envuelto en texto o en un
   bloque de razonamiento (`cribado_modelo.extraer_json_si`, el mismo mecanismo
   del cribado).
2. Se valida contra el esquema (`objetos.validar_respuesta`). Si no cuadra, se
   reintenta **una** vez con un recordatorio. Si vuelve a fallar, el trozo queda
   sin analizar y el reporte lo dice; no se inventa nada para rellenar.
3. Cada cita se busca literalmente en el trozo. Cada referencia bibliográfica
   también. Lo que no aparece, no pasa como fuente.

Además de lo que diga el modelo, las referencias bibliográficas se detectan de
forma **determinista**: DOI escritos en el texto y líneas de una sección de
bibliografía. Así una referencia real no depende de que el modelo la vea.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from ..cribado_modelo import extraer_json_si
from ..modelo import ErrorOllama, ModeloNoInstalado, OllamaNoResponde, SinModelosUtiles
from .documento import NR, Documento
from .enrutador import Enrutador
from .normalizacion import Trozo
from .objetos import (
    TIPOS,
    ErrorEsquema,
    ObjetoConocimiento,
    fundir,
    validar_respuesta,
)

__all__ = [
    "ResultadoAnalisis",
    "construir_prompt",
    "analizar_trozo",
    "analizar_documento",
    "referencias_deterministas",
    "MAXIMO_OBJETOS_POR_TROZO",
]

MAXIMO_OBJETOS_POR_TROZO = 8

RECORDATORIO = (
    "IMPORTANTE: tu respuesta anterior no se pudo leer o no tenía la forma pedida. "
    "Responde ahora ÚNICAMENTE con el objeto JSON, con la clave «objetos»."
)

_DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"<>)\]]+", re.I)
_SECCION_BIBLIOGRAFIA = re.compile(
    r"^\s*#*\s*(referencias|bibliograf[ií]a|references|literatura citada|obras citadas)\b",
    re.I,
)
_ANIO = re.compile(r"\((19|20)\d{2}[a-z]?\)|\b(19|20)\d{2}\b")


def construir_prompt(trozo: Trozo, documento: Documento, recordatorio: bool = False) -> str:
    """El prompt en español para extraer objetos de un trozo."""
    lineas = [
        "Extraes conocimiento de documentos académicos. Lee el FRAGMENTO y devuelve",
        "SOLO un objeto JSON, sin texto antes ni después.",
        "",
        "REGLAS",
        "1. Usa solo lo que dice el fragmento. No añadas hechos, autores, fechas,",
        "   cifras, páginas ni referencias que no estén escritos en él.",
        "2. En «cita» copia LITERALMENTE una frase del fragmento, de 5 a 40 palabras,",
        "   que respalde lo que dices. Si no hay ninguna, deja «cita» vacía.",
        "3. Lo que sea interpretación tuya y no esté escrito, márcalo con",
        "   \"es_inferencia\": true.",
        "4. Si el fragmento no da información suficiente, pon \"suficiente\": false",
        "   y explica por qué en «motivo_insuficiente». Decir que no hay suficiente",
        "   información es una respuesta válida y preferible a inventar.",
        "5. En «referencias» pon solo referencias bibliográficas escritas en el",
        "   fragmento, copiadas tal cual.",
        f"6. Tipos permitidos: {', '.join(TIPOS)}.",
        f"7. Como máximo {MAXIMO_OBJETOS_POR_TROZO} objetos: los más importantes.",
        "8. Escribe en el idioma del fragmento.",
        "",
        "FORMATO",
        '{"suficiente": true, "motivo_insuficiente": "", "objetos": [{"titulo": "Nombre",'
        ' "tipo": "concepto", "alias": [], "resumen": "una o dos frases con tus palabras",'
        ' "definicion": {"texto": "qué es", "cita": "frase literal del fragmento"},'
        ' "detalles": [{"texto": "...", "cita": "...", "es_inferencia": false}],'
        ' "relaciones": [{"tipo": "es parte de", "destino": "Otro concepto",'
        ' "es_inferencia": false}], "etiquetas": ["tema"], "confianza": 0.8}],'
        ' "referencias": [{"texto": "referencia copiada del fragmento"}]}',
        "",
        f"DOCUMENTO: {documento.titulo_legible}",
        f"FRAGMENTO ({trozo.ubicacion}):",
        '"""',
        trozo.texto,
        '"""',
    ]
    if recordatorio:
        lineas.extend(["", RECORDATORIO])
    return "\n".join(lineas)


@dataclass
class ResultadoAnalisis:
    """Lo que salió de analizar un documento entero."""

    objetos: list[ObjetoConocimiento] = field(default_factory=list)
    referencias: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    trozos: int = 0
    trozos_analizados: int = 0
    trozos_insuficientes: int = 0
    #: Afirmaciones que no se pudieron comprobar contra el texto de la fuente.
    sin_verificar: int = 0
    modelo: str = NR
    segundos: float = 0.0

    @property
    def completo(self) -> bool:
        return self.trozos_analizados == self.trozos and not self.errores


def analizar_trozo(trozo: Trozo, documento: Documento, cliente) -> tuple[object, float]:
    """Pregunta al modelo por un trozo. Un reintento si la respuesta no sirve.

    Devuelve la `RespuestaAnalisis` validada y los segundos que tardó. Lanza
    `ErrorEsquema` si ni al segundo intento hay una respuesta con la forma pedida.
    Los errores de Ollama (caído, modelo inexistente) suben tal cual: no son una
    respuesta rara, son que no hay con quién hablar.
    """
    segundos = 0.0
    ultimo_error: ErrorEsquema | None = None
    for intento in (1, 2):
        generacion = cliente.generar(
            construir_prompt(trozo, documento, recordatorio=intento > 1),
            formato_json=True,
        )
        segundos += generacion.duracion or 0.0
        datos = extraer_json_si(generacion.texto, lambda d: "objetos" in d)
        try:
            return validar_respuesta(datos, trozo, documento.nombre, modelo=f"modelo:{generacion.modelo}"), segundos
        except ErrorEsquema as error:
            ultimo_error = error
    assert ultimo_error is not None
    raise ultimo_error


def analizar_documento(
    documento: Documento,
    trozos: list[Trozo],
    enrutador: Enrutador,
    avance: Callable[[int, int, str], None] | None = None,
) -> ResultadoAnalisis:
    """knowledge_extract: pasa cada trozo por el modelo de extracción.

    Un trozo que falla no tumba el documento: se anota y se sigue. Si Ollama deja
    de responder, se para en seco y se devuelve lo que se tenga, con el error.
    """
    resultado = ResultadoAnalisis(trozos=len(trozos))
    resultado.referencias = referencias_deterministas(documento)
    try:
        cliente = enrutador.cliente("extraccion")
        resultado.modelo = f"modelo:{cliente.elegir()}"
    except (OllamaNoResponde, ModeloNoInstalado, SinModelosUtiles) as error:
        resultado.errores.append(str(error))
        return resultado

    todos: list[ObjetoConocimiento] = []
    for trozo in trozos:
        if avance is not None:
            avance(trozo.indice, len(trozos), trozo.ubicacion)
        try:
            respuesta, segundos = analizar_trozo(trozo, documento, cliente)
        except ErrorEsquema as error:
            resultado.avisos.append(
                f"Trozo {trozo.indice} ({trozo.ubicacion}): el modelo no devolvió una "
                f"respuesta válida ni al segundo intento ({error}). Queda sin analizar."
            )
            continue
        except OllamaNoResponde as error:
            resultado.errores.append(f"Ollama dejó de responder en el trozo {trozo.indice}: {error}")
            break
        except ErrorOllama as error:
            resultado.avisos.append(f"Trozo {trozo.indice} ({trozo.ubicacion}): {error}")
            continue

        resultado.trozos_analizados += 1
        resultado.segundos += segundos
        if respuesta.insuficiente:
            resultado.trozos_insuficientes += 1
            resultado.avisos.append(
                f"Trozo {trozo.indice} ({trozo.ubicacion}): {respuesta.motivo_insuficiente}"
            )
        resultado.avisos.extend(f"Trozo {trozo.indice}: {a}" for a in respuesta.avisos)
        for referencia in respuesta.referencias:
            if not _ya_esta(referencia, resultado.referencias):
                resultado.referencias.append(referencia)
        todos.extend(respuesta.objetos)

    resultado.objetos = fundir(todos)
    resultado.sin_verificar = sum(
        not a.es_de_la_fuente
        for objeto in resultado.objetos
        for a in (*objeto.definiciones, *objeto.detalles)
    )
    return resultado


def _ya_esta(referencia: str, lista: list[str]) -> bool:
    """¿Esta referencia ya está en la lista, aunque venga copiada algo distinta?

    El detector determinista guarda la línea entera, con su DOI; el modelo suele
    copiar solo el principio. Se comparan las primeras ocho palabras.
    """
    from .objetos import _sin_signos

    inicio = " ".join(_sin_signos(referencia).split()[:8])
    return any(" ".join(_sin_signos(r).split()[:8]) == inicio for r in lista)


def referencias_deterministas(documento: Documento) -> list[str]:
    """Referencias escritas en el documento, encontradas sin modelo.

    Dos vías: cualquier línea que contenga un DOI, y las líneas con año de una
    sección titulada «Referencias», «Bibliografía» o equivalente.
    """
    encontradas: list[str] = []
    en_bibliografia = False
    for fragmento in documento.fragmentos:
        for linea in fragmento.texto.split("\n"):
            limpia = linea.strip(" -•*\t")
            if not limpia:
                continue
            if _SECCION_BIBLIOGRAFIA.match(limpia):
                en_bibliografia = True
                continue
            if limpia.startswith("#"):
                en_bibliografia = False
                continue
            if (_DOI.search(limpia) or (en_bibliografia and _ANIO.search(limpia) and len(limpia) > 25)):
                if limpia not in encontradas:
                    encontradas.append(limpia)
    return encontradas[:200]
