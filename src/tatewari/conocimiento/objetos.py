"""Objetos de conocimiento: el esquema, los estados y la validación del modelo.

El esquema
----------

Un `ObjetoConocimiento` es un concepto, una persona, un lugar, un proceso… con
todo lo que hace falta para fiarse de él o para saber que no hay que fiarse.
Corresponde al esquema pedido así (los nombres del código van en español, como
el resto del proyecto):

    id                  → id
    title               → titulo
    type                → tipo
    summary             → resumen          (interpretación del modelo)
    definition          → definiciones     (una por fuente, con su cita)
    details             → detalles
    relationships       → relaciones
    source_documents    → documentos
    source_locations    → ubicaciones
    tags                → etiquetas
    confidence          → confianza
    status              → estado
    created_at          → creado
    updated_at          → actualizado

Además: ``alias``, ``conflictos``, ``referencias``, ``modelo`` e ``insuficiente``.

Fuente frente a interpretación
------------------------------

Cada `Afirmacion` lleva su ``origen``: ``"fuente"`` si sale del documento o
``"inferencia"`` si la pone el modelo. Y no basta con que el modelo diga que es
de la fuente: tiene que dar una **cita literal**, y `verificar_cita` la busca en
el texto del trozo que leyó. Si no aparece, la afirmación pasa a ser una
inferencia no verificada y el objeto entra en ``REVIEW``. Un modelo de 4B se
inventa citas con naturalidad; esto es lo que impide que una cita inventada
llegue al Vault con aspecto de hecho.

Las páginas **nunca** las da el modelo. Salen del fragmento donde se encontró la
cita, que las trae desde la extracción.

Los estados
-----------

``DRAFT`` → ``REVIEW`` → ``APPROVED`` → ``PUBLISHED``. Lo que genera el modelo
solo puede nacer en ``DRAFT`` o en ``REVIEW``. ``APPROVED`` y ``PUBLISHED`` solo
los pone una persona, con su nombre, desde la orden ``conocimiento estado``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from ..texto import clave_alfanumerica, normalizar
from .documento import NR
from .normalizacion import Trozo

__all__ = [
    "ESTADOS",
    "ESTADOS_DEL_MODELO",
    "ESTADOS_PROTEGIDOS",
    "TRANSICIONES",
    "TIPOS",
    "Afirmacion",
    "Relacion",
    "ObjetoConocimiento",
    "RespuestaAnalisis",
    "ErrorEsquema",
    "ErrorEstado",
    "validar_respuesta",
    "verificar_cita",
    "clave_de_nombre",
    "id_de_objeto",
    "comprobar_transicion",
    "ahora",
]

ESTADOS = ("DRAFT", "REVIEW", "APPROVED", "PUBLISHED")

#: Los únicos estados en los que puede nacer algo generado por el modelo.
ESTADOS_DEL_MODELO = ("DRAFT", "REVIEW")

#: Una nota en uno de estos estados no se reescribe nunca en automático.
ESTADOS_PROTEGIDOS = ("APPROVED", "PUBLISHED")

#: Qué cambios de estado se admiten. Volver atrás a REVIEW siempre se puede: es
#: como se reabre una nota que resultó estar mal.
TRANSICIONES = {
    "DRAFT": ("REVIEW", "APPROVED"),
    "REVIEW": ("DRAFT", "APPROVED"),
    "APPROVED": ("REVIEW", "PUBLISHED"),
    "PUBLISHED": ("REVIEW",),
}

#: Tipos de objeto. Los pedidos más los que salen solos en materias académicas.
TIPOS = (
    "concepto",
    "persona",
    "organizacion",
    "lugar",
    "proceso",
    "problema",
    "metodo",
    "ejemplo",
    "referencia",
    "especie",
    "dato",
    "evento",
    "otro",
)

#: Lo que el modelo escribe a veces en inglés o sin acento, y a qué tipo va.
_SINONIMOS_TIPO = {
    "concept": "concepto", "definicion": "concepto", "termino": "concepto",
    "person": "persona", "autor": "persona", "personaje": "persona",
    "organization": "organizacion", "institucion": "organizacion",
    "place": "lugar", "territorio": "lugar", "region": "lugar",
    "process": "proceso", "problem": "problema", "method": "metodo",
    "tecnica": "metodo", "example": "ejemplo", "reference": "referencia",
    "cita": "referencia", "species": "especie", "organismo": "especie",
    "data": "dato", "cifra": "dato", "event": "evento", "other": "otro",
}

#: Largo máximo de lo que se acepta del modelo, por campo. Un modelo que se
#: desboca no puede meter un libro en una nota.
_MAXIMOS = {"titulo": 120, "resumen": 800, "texto": 900, "cita": 400, "alias": 80}

#: Confianza máxima de algo que no se pudo verificar contra la fuente.
CONFIANZA_SIN_VERIFICAR = 0.4


class ErrorEsquema(Exception):
    """La respuesta del modelo no cumple el esquema. Reúne todos los problemas."""

    def __init__(self, errores: list[str]) -> None:
        self.errores = list(errores)
        super().__init__("; ".join(self.errores) or "respuesta no válida")


class ErrorEstado(Exception):
    """Un cambio de estado que no se admite, o que no puede hacer quien lo pide."""


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def clave_de_nombre(nombre: str) -> str:
    """Clave para comparar nombres: sin acentos, sin signos, en minúsculas.

    «Nitrógeno total», «nitrogeno-total» y «Nitrógeno Total» dan la misma clave.
    """
    return clave_alfanumerica(nombre)


def id_de_objeto(titulo: str) -> str:
    """Identificador estable de un objeto, derivado de su nombre normalizado.

    El mismo concepto extraído de dos documentos distintos tiene el mismo id, y
    eso es lo que permite fundirlos en vez de duplicarlos.
    """
    return "KS-" + hashlib.sha1(clave_de_nombre(titulo).encode("utf-8")).hexdigest()[:10]


def comprobar_transicion(actual: str, nuevo: str, autor: str) -> None:
    """Lanza `ErrorEstado` si el cambio no se admite."""
    if nuevo not in ESTADOS:
        raise ErrorEstado(f"Estado desconocido: «{nuevo}». Los válidos son: {', '.join(ESTADOS)}.")
    if actual not in ESTADOS:
        raise ErrorEstado(f"La nota tiene un estado desconocido: «{actual}».")
    if nuevo == actual:
        raise ErrorEstado(f"La nota ya está en {actual}.")
    if nuevo not in TRANSICIONES[actual]:
        permitidos = ", ".join(TRANSICIONES[actual])
        raise ErrorEstado(
            f"No se puede pasar de {actual} a {nuevo}. Desde {actual} se puede ir a: {permitidos}."
        )
    if nuevo in ESTADOS_PROTEGIDOS and (not autor.strip() or autor.startswith("modelo:")):
        raise ErrorEstado(
            f"{nuevo} solo lo puede poner una persona, con su nombre. El modelo no "
            f"aprueba ni publica conocimiento."
        )


# ---------------------------------------------------------------------------
# El esquema
# ---------------------------------------------------------------------------


@dataclass
class Afirmacion:
    """Algo que se dice de un objeto, con de dónde sale."""

    texto: str
    origen: str = "fuente"  # «fuente» o «inferencia»
    cita: str = NR
    documento: str = NR
    ubicacion: str = NR
    verificada: bool = False

    @property
    def es_de_la_fuente(self) -> bool:
        return self.origen == "fuente" and self.verificada


@dataclass
class Relacion:
    """Un enlace con otro objeto: «forma parte de [[Suelo]]»."""

    tipo: str
    destino: str
    documento: str = NR
    ubicacion: str = NR
    origen: str = "fuente"


@dataclass
class ObjetoConocimiento:
    id: str
    titulo: str
    tipo: str
    resumen: str = NR
    definiciones: list[Afirmacion] = field(default_factory=list)
    detalles: list[Afirmacion] = field(default_factory=list)
    relaciones: list[Relacion] = field(default_factory=list)
    documentos: list[str] = field(default_factory=list)
    ubicaciones: list[str] = field(default_factory=list)
    etiquetas: list[str] = field(default_factory=list)
    alias: list[str] = field(default_factory=list)
    referencias: list[str] = field(default_factory=list)
    conflictos: list[dict[str, Any]] = field(default_factory=list)
    confianza: float = 0.0
    estado: str = "DRAFT"
    modelo: str = NR
    insuficiente: bool = False
    creado: str = field(default_factory=ahora)
    actualizado: str = field(default_factory=ahora)

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def desde_dict(cls, datos: Mapping[str, Any]) -> "ObjetoConocimiento":
        """Reconstruye un objeto guardado en una nota. Tolera campos que falten."""
        base = {k: v for k, v in datos.items() if k in cls.__dataclass_fields__}
        base["definiciones"] = [Afirmacion(**_campos(a, Afirmacion)) for a in datos.get("definiciones", [])]
        base["detalles"] = [Afirmacion(**_campos(a, Afirmacion)) for a in datos.get("detalles", [])]
        base["relaciones"] = [Relacion(**_campos(r, Relacion)) for r in datos.get("relaciones", [])]
        return cls(**base)

    @property
    def clave(self) -> str:
        return clave_de_nombre(self.titulo)

    @property
    def verificado(self) -> bool:
        """¿Tiene al menos una definición comprobada contra la fuente?"""
        return any(a.es_de_la_fuente for a in self.definiciones)


def _campos(datos: Mapping[str, Any], clase: type) -> dict[str, Any]:
    return {k: v for k, v in dict(datos).items() if k in clase.__dataclass_fields__}


@dataclass
class RespuestaAnalisis:
    """Lo que salió de validar una respuesta del modelo para un trozo."""

    objetos: list[ObjetoConocimiento] = field(default_factory=list)
    referencias: list[str] = field(default_factory=list)
    insuficiente: bool = False
    motivo_insuficiente: str = NR
    avisos: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Citas
# ---------------------------------------------------------------------------


def _sin_signos(texto: str) -> str:
    """Normaliza para comparar citas: sin acentos, sin signos, espacios simples."""
    plano = re.sub(r"[^\w\s]", " ", normalizar(texto))
    return " ".join(plano.split())


def verificar_cita(cita: str, trozo: Trozo) -> tuple[bool, str]:
    """¿Está la cita en el trozo? Devuelve si está y la ubicación más precisa.

    Se compara sin acentos ni signos de puntuación, porque el modelo cambia
    comillas y guiones al copiar, pero las **palabras** tienen que estar tal
    cual y en orden. Una cita de menos de cuatro palabras no cuenta como
    verificación: «el suelo» aparece en cualquier texto sobre suelos.
    """
    buscada = _sin_signos(cita or "")
    if len(buscada.split()) < 4:
        return False, trozo.ubicacion
    for fragmento in trozo.fragmentos:
        if buscada in _sin_signos(fragmento.texto):
            return True, fragmento.ubicacion
    if buscada in _sin_signos(trozo.texto):  # la cita cruza dos fragmentos
        return True, trozo.ubicacion
    return False, trozo.ubicacion


# ---------------------------------------------------------------------------
# Validación de la respuesta del modelo
# ---------------------------------------------------------------------------


def _texto(valor: Any, campo: str, errores: list[str], donde: str, obligatorio: bool = False) -> str:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        if obligatorio:
            errores.append(f"{donde}.{campo}: falta y es obligatorio.")
        return ""
    if not isinstance(valor, (str, int, float)):
        errores.append(f"{donde}.{campo}: debería ser un texto, no {type(valor).__name__}.")
        return ""
    limpio = " ".join(str(valor).split())
    maximo = _MAXIMOS.get(campo, 900)
    return limpio[:maximo].rstrip() + ("…" if len(limpio) > maximo else "")


def _lista(valor: Any, campo: str, errores: list[str], donde: str) -> list[Any]:
    if valor is None:
        return []
    if not isinstance(valor, list):
        errores.append(f"{donde}.{campo}: debería ser una lista.")
        return []
    return valor


def _tipo(valor: Any, avisos: list[str], donde: str) -> str:
    crudo = normalizar(str(valor or "")).strip()
    if crudo in TIPOS:
        return crudo
    if crudo in _SINONIMOS_TIPO:
        return _SINONIMOS_TIPO[crudo]
    avisos.append(f"{donde}: tipo «{valor}» desconocido; se guarda como «otro».")
    return "otro"


def _confianza(valor: Any) -> float:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return 0.5
    if numero > 1:  # el modelo a veces responde en porcentaje
        numero = numero / 100
    return round(max(0.0, min(1.0, numero)), 2)


def _afirmacion(
    crudo: Any,
    trozo: Trozo,
    documento: str,
    donde: str,
    errores: list[str],
    avisos: list[str],
    es_inferencia: bool = False,
) -> Afirmacion | None:
    if isinstance(crudo, str):
        crudo = {"texto": crudo}
    if not isinstance(crudo, Mapping):
        errores.append(f"{donde}: debería ser un objeto con «texto» y «cita».")
        return None
    texto = _texto(crudo.get("texto"), "texto", errores, donde)
    if not texto:
        return None
    cita = _texto(crudo.get("cita"), "cita", errores, donde)
    inferencia = es_inferencia or bool(crudo.get("es_inferencia"))
    verificada, ubicacion = verificar_cita(cita, trozo) if cita else (False, trozo.ubicacion)
    if cita and not verificada:
        avisos.append(
            f"{donde}: la cita que dio el modelo no aparece en el documento; se "
            f"guarda como inferencia sin verificar."
        )
    return Afirmacion(
        texto=texto,
        origen="fuente" if (verificada and not inferencia) else "inferencia",
        cita=cita if verificada else NR,
        documento=documento,
        ubicacion=ubicacion,
        verificada=verificada,
    )


def _referencia_en_fuente(referencia: str, trozo: Trozo) -> bool:
    """Una referencia bibliográfica solo cuenta si está escrita en el documento.

    Se exige que sus primeras ocho palabras aparezcan en el trozo: es lo que
    distingue una referencia copiada de una que el modelo «recuerda».
    """
    palabras = _sin_signos(referencia).split()[:8]
    if len(palabras) < 3:
        return False
    return " ".join(palabras) in _sin_signos(trozo.texto)


def validar_respuesta(
    datos: Any,
    trozo: Trozo,
    documento: str,
    modelo: str = NR,
) -> RespuestaAnalisis:
    """Convierte la respuesta del modelo en objetos validados, o lanza ErrorEsquema.

    Una respuesta que no tiene la forma pedida se rechaza entera (quien llama
    reintenta una vez). Un objeto suelto mal formado se descarta con su aviso y
    los demás siguen: un error en uno no invalida el resto.
    """
    errores: list[str] = []
    if not isinstance(datos, Mapping):
        raise ErrorEsquema(["la respuesta no es un objeto JSON"])
    if "objetos" not in datos:
        raise ErrorEsquema(["falta la lista «objetos»"])
    crudos = datos.get("objetos")
    if not isinstance(crudos, list):
        raise ErrorEsquema(["«objetos» debería ser una lista"])

    salida = RespuestaAnalisis()
    suficiente = datos.get("suficiente", True)
    if suficiente is False or str(suficiente).lower() in ("false", "no"):
        salida.insuficiente = True
        salida.motivo_insuficiente = _texto(
            datos.get("motivo_insuficiente"), "texto", [], "respuesta"
        ) or "El modelo indicó que el fragmento no tiene información suficiente."

    for indice, crudo in enumerate(crudos):
        donde = f"objetos[{indice}]"
        errores_objeto: list[str] = []
        if not isinstance(crudo, Mapping):
            salida.avisos.append(f"{donde}: no es un objeto; se descarta.")
            continue
        titulo = _texto(crudo.get("titulo"), "titulo", errores_objeto, donde, obligatorio=True)
        if errores_objeto or not titulo:
            salida.avisos.append(f"{donde}: {'; '.join(errores_objeto) or 'sin título'}; se descarta.")
            continue

        tipo = _tipo(crudo.get("tipo"), salida.avisos, donde)
        definicion = _afirmacion(
            crudo.get("definicion"), trozo, documento, f"{donde}.definicion",
            errores_objeto, salida.avisos,
        )
        detalles = [
            afirmacion
            for n, d in enumerate(_lista(crudo.get("detalles"), "detalles", errores_objeto, donde))
            if (afirmacion := _afirmacion(
                d, trozo, documento, f"{donde}.detalles[{n}]", errores_objeto, salida.avisos
            ))
        ]
        relaciones = []
        for n, r in enumerate(_lista(crudo.get("relaciones"), "relaciones", errores_objeto, donde)):
            if not isinstance(r, Mapping):
                continue
            destino = _texto(r.get("destino"), "titulo", errores_objeto, f"{donde}.relaciones[{n}]")
            if not destino or clave_de_nombre(destino) == clave_de_nombre(titulo):
                continue
            relaciones.append(
                Relacion(
                    tipo=_texto(r.get("tipo"), "alias", errores_objeto, donde) or "relacionado con",
                    destino=destino,
                    documento=documento,
                    ubicacion=trozo.ubicacion,
                    origen="inferencia" if r.get("es_inferencia") else "fuente",
                )
            )
        alias = [
            limpio
            for a in _lista(crudo.get("alias"), "alias", errores_objeto, donde)
            if (limpio := _texto(a, "alias", errores_objeto, donde))
            and clave_de_nombre(limpio) != clave_de_nombre(titulo)
        ]
        etiquetas = [
            re.sub(r"[^\w/-]", "", normalizar(str(e)).replace(" ", "-"))
            for e in _lista(crudo.get("etiquetas"), "etiquetas", errores_objeto, donde)
            if str(e).strip()
        ]
        if errores_objeto:
            salida.avisos.extend(errores_objeto)

        confianza = _confianza(crudo.get("confianza"))
        definiciones = [definicion] if definicion else []
        verificado = any(a.es_de_la_fuente for a in definiciones)
        if not verificado:
            confianza = min(confianza, CONFIANZA_SIN_VERIFICAR)

        ubicaciones = sorted(
            {a.ubicacion for a in (*definiciones, *detalles) if a.ubicacion != NR}
            or {trozo.ubicacion}
        )
        objeto = ObjetoConocimiento(
            id=id_de_objeto(titulo),
            titulo=titulo,
            tipo=tipo,
            resumen=_texto(crudo.get("resumen"), "resumen", [], donde) or NR,
            definiciones=definiciones,
            detalles=detalles,
            relaciones=relaciones,
            documentos=[documento],
            ubicaciones=[f"{documento}, {u}" for u in ubicaciones],
            etiquetas=sorted({e for e in etiquetas if e}),
            alias=sorted(set(alias)),
            confianza=confianza,
            modelo=modelo,
            insuficiente=salida.insuficiente,
            # Sin definición verificada, o sin suficiente información: a revisión.
            estado="DRAFT" if verificado and not salida.insuficiente else "REVIEW",
        )
        salida.objetos.append(objeto)

    for n, r in enumerate(_lista(datos.get("referencias"), "referencias", errores, "respuesta")):
        texto = _texto(r.get("texto") if isinstance(r, Mapping) else r, "texto", [], f"referencias[{n}]")
        if not texto:
            continue
        if _referencia_en_fuente(texto, trozo):
            salida.referencias.append(texto)
        else:
            salida.avisos.append(
                f"referencias[{n}]: no aparece en el documento; se descarta para no "
                f"inventar bibliografía."
            )
    return salida


def fundir(objetos: Iterable[ObjetoConocimiento]) -> list[ObjetoConocimiento]:
    """Junta los objetos con el mismo nombre que salieron de trozos distintos."""
    por_clave: dict[str, ObjetoConocimiento] = {}
    for objeto in objetos:
        existente = por_clave.get(objeto.clave)
        if existente is None:
            por_clave[objeto.clave] = objeto
            continue
        _anadir(existente, objeto)
    return list(por_clave.values())


def _anadir(base: ObjetoConocimiento, nuevo: ObjetoConocimiento) -> None:
    """Mete en `base` lo que trae `nuevo`, sin perder nada ni repetir."""
    def sin_repetir(destino: list, fuente: Sequence, clave) -> None:
        vistas = {clave(x) for x in destino}
        for x in fuente:
            if clave(x) not in vistas:
                destino.append(x)
                vistas.add(clave(x))

    sin_repetir(base.definiciones, nuevo.definiciones, lambda a: _sin_signos(a.texto))
    sin_repetir(base.detalles, nuevo.detalles, lambda a: _sin_signos(a.texto))
    sin_repetir(base.relaciones, nuevo.relaciones, lambda r: (clave_de_nombre(r.destino), r.tipo))
    sin_repetir(base.documentos, nuevo.documentos, str)
    sin_repetir(base.ubicaciones, nuevo.ubicaciones, str)
    sin_repetir(base.etiquetas, nuevo.etiquetas, str)
    sin_repetir(base.alias, nuevo.alias, clave_de_nombre)
    sin_repetir(base.referencias, nuevo.referencias, str)
    if base.resumen == NR:
        base.resumen = nuevo.resumen
    base.confianza = max(base.confianza, nuevo.confianza)
    base.insuficiente = base.insuficiente and nuevo.insuficiente
    base.estado = "DRAFT" if base.verificado and not base.insuficiente else "REVIEW"
    base.actualizado = ahora()


def anadir_a(base: ObjetoConocimiento, nuevo: ObjetoConocimiento) -> ObjetoConocimiento:
    """Funde `nuevo` en `base` aunque se llamen distinto (una coincidencia por alias)."""
    _anadir(base, nuevo)
    return base


__all__ += ["fundir", "anadir_a", "CONFIANZA_SIN_VERIFICAR"]
