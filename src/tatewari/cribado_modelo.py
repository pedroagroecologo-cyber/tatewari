"""Segunda vuelta del cribado: los dudosos, con el modelo local.

Qué se le pregunta al modelo, y qué no
--------------------------------------

**Solo los dudosos.** Los que el filtro determinista ya decidió no se vuelven a
preguntar. No es una optimización cosmética: en el fixture son 2 de 13, y en una
revisión real de miles de registros los dudosos son una fracción. A segundos por
registro en una tarjeta de 4 GB, preguntar por todo convertiría una revisión en
un fin de semana de cómputo; preguntar solo por los dudosos la deja en un café.

Tampoco se le pregunta por el año ni por el idioma: eso ya lo comprobó el filtro
con datos, no con opiniones, y volver a preguntarlo solo abre la puerta a que el
modelo excluya por un motivo que ya estaba resuelto.

Cómo se le pregunta
-------------------

Con los criterios del protocolo —los ``motivo`` de las reglas de inclusión y los
términos de exclusión temática—, el título y el resumen recortado. Y se le exige
responder **solo** con un JSON::

    {"decision": "incluir|excluir|dudoso", "motivo": "máximo doce palabras"}

Se le pide además a Ollama que fuerce formato JSON. Ayuda, pero no basta: un
modelo de 3B devuelve tan pronto el JSON limpio como el JSON envuelto en «Claro,
aquí tienes:» y un bloque de código. Por eso `extraer_json` busca el primer
objeto JSON **equilibrado** que además traiga una decisión reconocible, y no le
importa lo que haya alrededor.

La regla que no se negocia
--------------------------

Si la respuesta no se puede interpretar, se reintenta **una** vez. Si vuelve a
fallar, el registro **se queda en «dudoso»**. Nunca se excluye por una respuesta
que no se entendió: un modelo pequeño que contesta un disparate no es evidencia
de nada, y convertir «no entendí» en «fuera» es exactamente la forma de perder un
artículo bueno sin dejar rastro (AGENTS.md, regla 4).

Por lo mismo, tampoco se traducen los síes y los noes sueltos: si el modelo
contesta ``"no"``, eso no se lee como «excluir». Puede estar contestando a otra
cosa.

El rastro
---------

Toda decisión del modelo se guarda con ``decidido_por = "modelo:NOMBRE"``, con el
nombre y la etiqueta exactos del modelo que la tomó (``modelo:llama3.2:3b``). Un
cribado hecho con un 1B y otro hecho con un 3B no valen lo mismo, y dentro de
seis meses nadie se va a acordar de con qué se hizo.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Iterable, Mapping, Sequence

from .cribado import DECISIONES, Decision, DecisionManual, PREFIJO_MODELO
from .fuentes import NR
from .modelo import ClienteOllama, Generacion
from .protocolo import Protocolo
from .texto import normalizar

__all__ = [
    "LIMITE_RESUMEN",
    "PALABRAS_MOTIVO",
    "RespuestaModelo",
    "Paso",
    "ResultadoModelo",
    "construir_prompt",
    "extraer_json",
    "extraer_json_si",
    "interpretar",
    "sin_razonamiento",
    "recortar",
    "cribar_dudosos",
]

#: Caracteres de resumen que se le mandan al modelo. Un resumen académico cabe
#: de sobra; lo que se corta son los que traen la licencia, el aviso de derechos
#: y media bibliografía pegados detrás. Con `num_ctx` de 4096 hay sitio, pero un
#: prompt más corto se genera antes, y aquí cada segundo se nota.
LIMITE_RESUMEN = 1200

#: El máximo que se le pide al motivo. Cabe en una celda del CSV y se lee de un
#: vistazo al auditar.
PALABRAS_MOTIVO = 12

#: Lo que se acepta como decisión. Se compara ya normalizado (sin acentos y en
#: minúsculas), así que «Exclusión» entra por «exclusion».
#:
#: Deliberadamente **no** están «si», «no», «yes» ni «ok»: un «no» suelto no es
#: una exclusión, es una palabra que puede estar contestando a cualquier cosa, y
#: excluir con eso sería excluir a ciegas.
_SINONIMOS_DECISION = {
    "incluir": "incluir",
    "incluido": "incluir",
    "inclusion": "incluir",
    "include": "incluir",
    "included": "incluir",
    "excluir": "excluir",
    "excluido": "excluir",
    "exclusion": "excluir",
    "exclude": "excluir",
    "excluded": "excluir",
    "dudoso": "dudoso",
    "duda": "dudoso",
    "dudosa": "dudoso",
    "doubtful": "dudoso",
    "unclear": "dudoso",
    "uncertain": "dudoso",
}

#: Claves con las que el modelo puede nombrar la decisión y el motivo. Se
#: comparan normalizadas, así que «decisión» entra por «decision».
_CLAVES_DECISION = ("decision", "resultado", "veredicto")
_CLAVES_MOTIVO = ("motivo", "razon", "justificacion", "reason", "explicacion")

#: Bloque de razonamiento de un modelo que piensa en voz alta. Uno sin cerrar se
#: come el resto del texto a propósito: ver sin_razonamiento.
_RAZONAMIENTO = re.compile(
    r"<think[^>]*>.*?(?:</think[^>]*>|$)", re.IGNORECASE | re.DOTALL
)

#: Lo que se le añade al prompt en el reintento. Corto a propósito: si la
#: primera vez se distrajo explicando, la segunda hay que apretarle, no darle
#: más texto donde perderse.
RECORDATORIO = (
    "IMPORTANTE: tu respuesta anterior no se pudo leer. Responde ahora "
    "únicamente con el objeto JSON, sin ninguna palabra antes ni después."
)


def recortar(texto: object, limite: int = LIMITE_RESUMEN) -> str:
    """Recorta `texto` a `limite` caracteres, cortando en un espacio.

    Devuelve ``"NR"`` si no hay texto: al modelo se le dice que no hay resumen,
    no se le manda una cadena vacía para que se lo imagine.
    """
    if texto is None:
        return NR
    limpio = " ".join(str(texto).split())
    if not limpio or limpio == NR:
        return NR
    if len(limpio) <= limite:
        return limpio
    cortado = limpio[:limite]
    espacio = cortado.rfind(" ")
    if espacio > limite // 2:
        cortado = cortado[:espacio]
    return cortado.rstrip(" ,;:.") + "…"


def recortar_palabras(texto: object, palabras: int = PALABRAS_MOTIVO) -> str:
    """Deja el motivo en `palabras` palabras como máximo.

    El modelo se pasa del límite con frecuencia. Se recorta aquí en vez de
    rechazar la respuesta: la decisión es buena aunque el motivo sea largo.
    """
    if texto is None:
        return NR
    trozos = str(texto).split()
    if not trozos:
        return NR
    if len(trozos) <= palabras:
        return " ".join(trozos)
    return " ".join(trozos[:palabras]) + "…"


# ---------------------------------------------------------------------------
# El prompt
# ---------------------------------------------------------------------------


def construir_prompt(
    registro: Mapping[str, Any],
    protocolo: Protocolo,
    limite_resumen: int = LIMITE_RESUMEN,
    recordatorio: bool = False,
) -> str:
    """Arma el prompt en español para un registro dudoso.

    Lleva los criterios del protocolo, el título y el resumen recortado. Con
    `recordatorio` se añade el apretón del reintento.
    """
    inicio, fin = protocolo.ventana
    lineas = [
        "Ayudas a cribar literatura científica para una revisión sistemática.",
        "Tu tarea es decidir si UN artículo entra en la revisión, leyendo solo su",
        "título y su resumen.",
        "",
        f"REVISIÓN: {protocolo.titulo}",
        "",
        "CRITERIOS DE INCLUSIÓN (basta con que se cumpla uno):",
    ]

    criterios = [r.motivo for r in protocolo.reglas.incluir if r.motivo != NR]
    if criterios:
        lineas.extend(f"  - {criterio}" for criterio in criterios)
    else:
        # Un protocolo sin reglas de inclusión no puede guiar al modelo, y
        # decírselo es más honesto que dejarle la lista vacía.
        lineas.append("  - (el protocolo no declara criterios de inclusión)")

    if protocolo.exclusion:
        lineas.append("")
        lineas.append("TEMAS EXCLUIDOS. Si el artículo trata de esto, es «excluir»:")
        lineas.append("  " + "; ".join(protocolo.exclusion))

    resumen = recortar(registro.get("resumen"), limite_resumen)
    lineas.extend(
        [
            "",
            "ARTÍCULO",
            f"  Título : {registro.get('titulo', NR)}",
            f"  Año    : {registro.get('anio', NR)}",
            f"  Resumen: {resumen}",
        ]
    )

    if resumen == NR:
        # Sin resumen, un modelo pequeño tiende a copiar el criterio de
        # inclusión como si lo hubiera leído en el artículo. Decirle que solo
        # tiene el título, y que puede contestar «dudoso», es lo que evita que
        # se lo invente (AGENTS.md, regla 2).
        lineas.extend(
            [
                "",
                "AVISO: este registro NO trae resumen. Decide solo con el título.",
                "Si el título no basta para saberlo, responde «dudoso»: no des por",
                "supuesto nada que el título no diga.",
            ]
        )

    lineas.extend(
        [
            "",
            "CÓMO DECIDIR",
            '  - "incluir" si el resumen indica que cumple algún criterio de',
            "    inclusión.",
            '  - "excluir" si trata un tema excluido, o si no tiene nada que ver',
            "    con la revisión.",
            '  - "dudoso" si el resumen no da para decidir. Es una respuesta',
            "    válida y preferible a adivinar: lo verá una persona.",
            f"  - El año ({inicio}-{fin}) y el idioma "
            f"({', '.join(protocolo.idiomas)}) ya están comprobados. No los",
            "    tengas en cuenta.",
            "  - El motivo, en español y de doce palabras como máximo.",
            "",
            "Responde ÚNICAMENTE con este objeto JSON, sin nada antes ni después:",
            '{"decision": "incluir", "motivo": "aquí el motivo, doce palabras"}',
        ]
    )

    if recordatorio:
        lineas.extend(["", RECORDATORIO])

    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Interpretar la respuesta
# ---------------------------------------------------------------------------


def _fin_del_objeto(texto: str, inicio: int) -> int | None:
    """Dónde acaba el objeto JSON que empieza en `inicio`, o `None`.

    Cuenta llaves respetando las cadenas y los escapes: un ``{`` dentro de
    ``"motivo"`` no abre un objeto nuevo, y una ``\\"`` no cierra la cadena.
    """
    profundidad = 0
    en_cadena = False
    escapado = False

    for indice in range(inicio, len(texto)):
        caracter = texto[indice]
        if en_cadena:
            if escapado:
                escapado = False
            elif caracter == "\\":
                escapado = True
            elif caracter == '"':
                en_cadena = False
            continue
        if caracter == '"':
            en_cadena = True
        elif caracter == "{":
            profundidad += 1
        elif caracter == "}":
            profundidad -= 1
            if profundidad == 0:
                return indice + 1
    return None


def extraer_json(texto: str) -> dict[str, Any] | None:
    """Saca el primer objeto JSON **útil** de un texto, o `None`.

    Útil quiere decir: que sea un objeto, que se pueda analizar y que traiga una
    clave de decisión. Por eso no vale con buscar el primer ``{``: el modelo
    escribe cosas como «Claro, {el artículo} habla de…», y el primer ``{`` de ahí
    no es JSON. Se prueban todos los candidatos hasta encontrar uno que sirva, y
    da igual que venga envuelto en ```json o en un párrafo de explicación.
    """
    return extraer_json_si(
        texto, lambda candidato: _clave_de(candidato, _CLAVES_DECISION) is not None
    )


def extraer_json_si(
    texto: str, acepta: Callable[[dict[str, Any]], bool]
) -> dict[str, Any] | None:
    """El primer objeto JSON equilibrado del texto que `acepta` da por bueno.

    Es la maquinaria de `extraer_json` sin atarla a la clave «decision», para
    que la reutilicen otros módulos (Knowledge Studio, la divulgación) en vez de
    copiarla. Quita antes los bloques de razonamiento, por la misma razón que
    `interpretar`: el borrador de un modelo que piensa en voz alta no es su
    conclusión.
    """
    if not texto:
        return None
    texto = sin_razonamiento(texto)

    posicion = texto.find("{")
    while posicion != -1:
        fin = _fin_del_objeto(texto, posicion)
        if fin is not None:
            try:
                candidato = json.loads(texto[posicion:fin])
            except (ValueError, TypeError):
                candidato = None
            if isinstance(candidato, dict) and acepta(candidato):
                return candidato
        posicion = texto.find("{", posicion + 1)
    return None


def _clave_de(datos: Mapping[str, Any], candidatas: Sequence[str]) -> Any:
    """Busca en `datos` la primera clave de `candidatas`, comparando normalizado."""
    normalizadas = {normalizar(clave): valor for clave, valor in datos.items()}
    for candidata in candidatas:
        if candidata in normalizadas:
            return normalizadas[candidata]
    return None


@dataclass(frozen=True)
class RespuestaModelo:
    """Lo que dijo el modelo, ya interpretado."""

    decision: str
    motivo: str
    bruto: str = ""


def sin_razonamiento(texto: str) -> str:
    """Quita los bloques ``<think>…</think>`` de la respuesta.

    Un modelo de razonamiento escribe primero su borrador y luego su conclusión.
    Si el borrador trae un JSON —y lo trae, porque va probando— se leería la
    idea que el modelo **descartó** en vez de la que se quedó. Se corta antes de
    buscar el JSON.

    Un ``<think>`` sin cerrar se lleva por delante el resto: si el modelo se
    quedó pensando y nunca concluyó, no hay conclusión que leer.
    """
    return _RAZONAMIENTO.sub(" ", texto)


def interpretar(texto: str) -> RespuestaModelo | None:
    """Convierte la respuesta del modelo en una decisión, o devuelve `None`.

    `None` significa «no se entendió», y quien llama sabe lo que hacer con eso:
    reintentar una vez y, si vuelve a pasar, dejar el registro en «dudoso».
    """
    datos = extraer_json(sin_razonamiento(texto))
    if datos is None:
        return None

    cruda = _clave_de(datos, _CLAVES_DECISION)
    if cruda is None:
        return None

    decision = _SINONIMOS_DECISION.get(normalizar(cruda))
    if decision is None or decision not in DECISIONES:
        return None

    motivo = _clave_de(datos, _CLAVES_MOTIVO)
    return RespuestaModelo(
        decision=decision,
        motivo=recortar_palabras(motivo),
        bruto=texto.strip(),
    )


# ---------------------------------------------------------------------------
# La pasada completa
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Paso:
    """Lo que pasó con un registro. Es lo que se le enseña a quien mira."""

    identificador: str
    decision: str
    motivo: str
    intentos: int = 1
    segundos: float | None = None
    interpretado: bool = True

    def linea(self) -> str:
        """Una línea de avance para la CLI."""
        tiempo = f" {self.segundos:.1f} s" if self.segundos is not None else ""
        aviso = "" if self.interpretado else "  (no se entendió la respuesta)"
        return f"{self.decision:<8}{tiempo}  {self.motivo}{aviso}"


@dataclass
class ResultadoModelo:
    """Lo que salió de pasar los dudosos por el modelo."""

    modelo: str
    pasos: list[Paso] = field(default_factory=list)
    decisiones: dict[str, DecisionManual] = field(default_factory=dict)

    @property
    def preguntados(self) -> int:
        return len(self.pasos)

    @property
    def no_interpretados(self) -> int:
        """Cuántos se quedaron dudosos porque no se entendió la respuesta."""
        return sum(1 for paso in self.pasos if not paso.interpretado)

    @property
    def segundos(self) -> float:
        return sum(paso.segundos or 0.0 for paso in self.pasos)

    @property
    def conteos(self) -> dict[str, int]:
        conteos = {cual: 0 for cual in DECISIONES}
        for paso in self.pasos:
            conteos[paso.decision] += 1
        return conteos

    def resumen(self) -> str:
        """Texto para la CLI."""
        conteos = self.conteos
        lineas = [
            f"Modelo     : {self.modelo}",
            f"Preguntados: {self.preguntados} registros dudosos",
            f"Respondió  : {conteos['incluir']} incluir, "
            f"{conteos['excluir']} excluir, {conteos['dudoso']} dudoso",
        ]
        if self.segundos:
            media = self.segundos / max(1, self.preguntados)
            lineas.append(
                f"Tiempo     : {self.segundos:.0f} s en total, "
                f"{media:.1f} s por registro"
            )
        if self.no_interpretados:
            lineas.append(
                f"Sin entender: {self.no_interpretados}. Se quedan en «dudoso»; "
                f"nunca se excluye por una respuesta que no se entendió."
            )
        return "\n".join(lineas)


def cribar_dudosos(
    dudosos: Iterable[Decision],
    protocolo: Protocolo,
    cliente: ClienteOllama,
    antes: Callable[[int, int, Decision], None] | None = None,
    despues: Callable[[int, int, Paso], None] | None = None,
    fecha: str | None = None,
    limite_resumen: int = LIMITE_RESUMEN,
) -> ResultadoModelo:
    """Pasa por el modelo los registros que el filtro dejó en «dudoso».

    `antes` y `despues` son para el avance: el primero se llama al empezar cada
    registro y el segundo al acabarlo. Hacen falta de verdad, no son adorno: el
    primer registro tarda más que los demás porque Ollama tiene que cargar el
    modelo en memoria, y sin avance parece que el programa se colgó.

    Nunca lanza por una respuesta rara. Sí lanza `ErrorOllama` si Ollama deja de
    responder a media pasada: eso no es una respuesta rara, es que ya no hay con
    quién hablar, y seguir preguntando no arregla nada.
    """
    pendientes = list(dudosos)
    total = len(pendientes)
    nombre = cliente.elegir()
    hoy = fecha or date.today().isoformat()
    resultado = ResultadoModelo(modelo=nombre)

    for indice, decision in enumerate(pendientes, start=1):
        if antes is not None:
            antes(indice, total, decision)

        paso = _preguntar(
            decision, protocolo, cliente, nombre, hoy, limite_resumen, resultado
        )
        resultado.pasos.append(paso)

        if despues is not None:
            despues(indice, total, paso)

    return resultado


def _preguntar(
    decision: Decision,
    protocolo: Protocolo,
    cliente: ClienteOllama,
    nombre: str,
    fecha: str,
    limite_resumen: int,
    resultado: ResultadoModelo,
) -> Paso:
    """Pregunta por un registro, con un reintento si no se entiende la respuesta."""
    registro = decision.registro
    segundos = 0.0
    respuesta: RespuestaModelo | None = None
    intentos = 0

    for intento in (1, 2):
        intentos = intento
        prompt = construir_prompt(
            registro,
            protocolo,
            limite_resumen=limite_resumen,
            recordatorio=intento > 1,
        )
        generacion: Generacion = cliente.generar(prompt, formato_json=True)
        segundos += generacion.duracion or 0.0
        respuesta = interpretar(generacion.texto)
        if respuesta is not None:
            break

    if respuesta is None:
        # Ni al segundo intento. El registro se queda como estaba: dudoso. No se
        # guarda ninguna decisión, porque nadie decidió nada.
        return Paso(
            identificador=decision.identificador,
            decision="dudoso",
            motivo="El modelo no devolvió una respuesta interpretable.",
            intentos=intentos,
            segundos=segundos or None,
            interpretado=False,
        )

    resultado.decisiones[decision.identificador] = DecisionManual(
        identificador=decision.identificador,
        decision=respuesta.decision,
        motivo=respuesta.motivo,
        autor=f"{PREFIJO_MODELO}{nombre}",
        fecha=fecha,
    )
    return Paso(
        identificador=decision.identificador,
        decision=respuesta.decision,
        motivo=respuesta.motivo,
        intentos=intentos,
        segundos=segundos or None,
    )
