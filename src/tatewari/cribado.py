"""Cribado determinista: reglas del protocolo, sin modelo de lenguaje.

Aquí no hay Ollama ni embeddings. Todo lo que decide este módulo lo decide una
regla escrita en el protocolo, y la misma entrada da siempre la misma salida.
Eso es lo que permite auditarlo: si una decisión sorprende, se puede seguir a
mano hasta el término exacto que la disparó.

Orden de evaluación
-------------------

El orden no es decorativo; cambia el motivo que acaba en la bitácora:

1. **Ventana temporal.** Un artículo de 2009 se excluye por año, no por
   contenido. Es barato y es el motivo verdadero.
2. **Idioma.**
3. **¿Hay resumen?** Un registro sin resumen es **dudoso**, nunca «excluir»
   (salvo que el protocolo diga otra cosa en ``reglas.sinResumen``). No es
   cribable en automático, y descartar a ciegas lo que no se puede leer es el
   error clásico: así se pierden artículos buenos sin que quede rastro. Va a
   revisión humana (AGENTS.md, regla 4).
4. **Términos de exclusión temática.** Lo que el protocolo excluye por tema se
   excluye por tema, y el motivo cita los términos encontrados.
5. **Reglas de bloques**, y solo entonces: primero las de ``incluir``, luego las
   de ``dudoso``. Gana la primera que se cumple. Lo que no cuadra con ninguna se
   excluye, con ese motivo explícito.

Un dato que falta nunca es motivo de exclusión automática: si el año o el idioma
no vienen reportados, el registro es **dudoso**, porque el filtro no tiene con
qué decidir.

Semántica de una regla
----------------------

La de `protocolo`: ``todos`` (están todos), ``alguno_de`` (de cada sublista hay
al menos uno) y ``ninguno`` (no está ninguno), las tres a la vez.

Decisiones manuales
-------------------

`decisiones.json` guarda lo que una persona —o el modelo, más adelante— decidió
a mano. Una decisión registrada **sobreescribe** al filtro pero **no lo borra**:
la salida conserva ``decision_filtro`` y ``motivo_filtro`` junto a la decisión
final, y la columna ``decidido_por`` dice de quién fue: ``"filtro"``, el nombre
de la persona, o el del modelo. Sin eso no se puede medir cuánto se equivoca el
filtro, que es justo lo que hay que medir.

Forma del archivo::

    {
      "R0007": {
        "decision": "incluir",
        "motivo": "El texto completo sí reporta remoción de DQO.",
        "autor": "Pedro",
        "fecha": "2026-09-12"
      }
    }

Los cuatro campos son obligatorios: una decisión manual sin motivo, sin autor o
sin fecha no es auditable, y una decisión que no se puede auditar no vale más
que la del filtro.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import prisma
from .config import Config
from .dedup import (
    NOMBRE_IDENTIFICADORES,
    ResultadoDedup,
    deduplicar,
    guardar_asignaciones,
    leer_asignaciones,
)
from .fuentes import NR
from .protocolo import Protocolo, Regla
from .texto import nombres_presentes, terminos_presentes, texto_buscable

__all__ = [
    "DECISIONES",
    "COLUMNAS_CRIBADO",
    "NOMBRE_DECISIONES",
    "NOMBRE_CRIBADO",
    "NOMBRE_PRISMA",
    "CATEGORIA_VENTANA",
    "CATEGORIA_IDIOMA",
    "CATEGORIA_TEMA",
    "CATEGORIA_SIN_REGLA",
    "CATEGORIA_SIN_RESUMEN",
    "CATEGORIA_MANUAL",
    "CATEGORIA_MODELO",
    "PREFIJO_MODELO",
    "es_autor_modelo",
    "Decision",
    "DecisionManual",
    "ResultadoCribado",
    "Cribado",
    "ErrorCribado",
    "protocolo_registrado",
    "leer_decisiones",
    "guardar_decisiones",
    "anadir_decisiones",
    "decidir",
    "regla_se_cumple",
    "clasificar",
    "validar_decisiones",
    "cribar",
]

#: Las tres decisiones posibles. No hay una cuarta: «excluir» siempre lleva
#: motivo y «dudoso» siempre va a una persona.
DECISIONES = ("incluir", "dudoso", "excluir")

NOMBRE_REGISTROS = "registros.json"
NOMBRE_ESTADO = "estado.json"
NOMBRE_DECISIONES = "decisiones.json"
NOMBRE_CRIBADO = "cribado.csv"
NOMBRE_PRISMA = "prisma.txt"

#: Categorías de motivo. El motivo de cada registro es una frase concreta; la
#: categoría es lo que se cuenta en el diagrama PRISMA, porque contar frases
#: distintas una por una no dice nada.
CATEGORIA_VENTANA = "Fuera de la ventana temporal"
CATEGORIA_IDIOMA = "Idioma no admitido"
CATEGORIA_TEMA = "Exclusión temática"
CATEGORIA_SIN_REGLA = "No cumple ninguna regla de inclusión"
CATEGORIA_SIN_RESUMEN = "Sin resumen"
CATEGORIA_MANUAL = "Decisión de una persona"
CATEGORIA_MODELO = "Decisión del modelo local"

#: Quién decidió, cuando no decidió nadie a mano.
FILTRO = "filtro"

#: Con lo que empieza el autor de una decisión tomada por el modelo local:
#: ``modelo:llama3.2:3b``. Un cribado hecho con un 1B y otro hecho con un 3B no
#: valen lo mismo, así que el nombre del modelo va pegado a cada decisión.
PREFIJO_MODELO = "modelo:"


def es_autor_modelo(autor: str) -> bool:
    """¿Esta decisión la tomó el modelo local y no una persona?"""
    return str(autor).startswith(PREFIJO_MODELO)


COLUMNAS_CRIBADO = (
    "identificador",
    "decision",
    "motivo",
    "categoria",
    "decidido_por",
    "decision_filtro",
    "motivo_filtro",
    "clasificacion",
    "bloques",
    "bloques_presentes",
    "regla",
    "doi",
    "titulo",
    "anio",
    "idioma",
    "tipo",
    "revista",
    "autores",
    "consulta_origen",
    "copias",
    "oa_url",
)

#: Separador de los campos que llevan varios valores dentro de una celda. No se
#: usa la coma: el CSV ya la usa para separar columnas y leerlo luego sería un
#: lío incluso estando bien escapado.
SEPARADOR = "|"


class ErrorCribado(Exception):
    """El cribado no puede correr: faltan registros, o `decisiones.json` está mal.

    Reúne **todos** los problemas encontrados, como `ErrorProtocolo`: corregir
    un archivo de decisiones de uno en uno es un suplicio.
    """

    def __init__(self, errores: list[str] | str, ruta: Path | None = None) -> None:
        self.errores = [errores] if isinstance(errores, str) else list(errores)
        self.ruta = ruta
        super().__init__(str(self))

    def __str__(self) -> str:
        origen = f" en {self.ruta}" if self.ruta is not None else ""
        if len(self.errores) == 1:
            return f"Cribado{origen}: {self.errores[0]}"
        cabecera = f"El cribado{origen} encontró {len(self.errores)} problemas:"
        detalle = "\n".join(f"  {i}. {e}" for i, e in enumerate(self.errores, 1))
        return f"{cabecera}\n{detalle}"


@dataclass(frozen=True)
class DecisionManual:
    """Lo que una persona (o el modelo) decidió a mano sobre un registro."""

    identificador: str
    decision: str
    motivo: str
    autor: str
    fecha: str


@dataclass(frozen=True)
class Decision:
    """La decisión sobre un registro, con todo lo necesario para auditarla.

    `bloques` son los que **dispararon** la regla que decidió; `bloques_presentes`
    son todos los detectados en el texto, que es lo que hace falta para entender
    por qué *no* se disparó otra.
    """

    identificador: str
    decision: str
    motivo: str
    categoria: str = ""
    bloques: tuple[str, ...] = ()
    bloques_presentes: tuple[str, ...] = ()
    clasificacion: str = NR
    regla: str = NR
    decidido_por: str = FILTRO
    decision_filtro: str = ""
    motivo_filtro: str = ""
    registro: Mapping[str, Any] = field(default_factory=dict)

    @property
    def es_manual(self) -> bool:
        """¿La decidió una persona o el modelo, en vez del filtro?"""
        return self.decidido_por != FILTRO

    def fila(self) -> dict[str, Any]:
        """La fila del CSV. Las listas se unen con `SEPARADOR`."""
        registro = self.registro
        autores = registro.get("autores", [NR])
        if not isinstance(autores, (list, tuple)):
            autores = [autores]
        origen = registro.get("consulta_origen", [NR])
        if not isinstance(origen, (list, tuple)):
            origen = [origen]
        return {
            "identificador": self.identificador,
            "decision": self.decision,
            "motivo": self.motivo,
            "categoria": self.categoria or NR,
            "decidido_por": self.decidido_por,
            "decision_filtro": self.decision_filtro or self.decision,
            "motivo_filtro": self.motivo_filtro or self.motivo,
            "clasificacion": self.clasificacion,
            "bloques": SEPARADOR.join(self.bloques) or NR,
            "bloques_presentes": SEPARADOR.join(self.bloques_presentes) or NR,
            "regla": self.regla,
            "doi": registro.get("doi", NR),
            "titulo": registro.get("titulo", NR),
            "anio": registro.get("anio", NR),
            "idioma": registro.get("idioma", NR),
            "tipo": registro.get("tipo", NR),
            "revista": registro.get("revista", NR),
            "autores": SEPARADOR.join(str(a) for a in autores) or NR,
            "consulta_origen": SEPARADOR.join(str(o) for o in origen) or NR,
            "copias": registro.get("copias", 1),
            "oa_url": registro.get("oa_url", NR),
        }


# ---------------------------------------------------------------------------
# Motor de reglas
# ---------------------------------------------------------------------------


def regla_se_cumple(
    regla: Regla, presentes: Iterable[str]
) -> tuple[bool, tuple[str, ...]]:
    """¿Se cumple `regla` con estos bloques presentes?

    Devuelve si se cumple y **qué bloques la dispararon**: los de ``todos`` más,
    de cada sublista de ``alguno_de``, los que estaban. Los de ``ninguno`` no
    disparan nada por definición: si alguno estuviera, la regla no se cumpliría.
    """
    disponibles = set(presentes)

    faltan = [nombre for nombre in regla.todos if nombre not in disponibles]
    if faltan:
        return False, ()

    disparados = list(regla.todos)
    for sublista in regla.alguno_de:
        hallados = [nombre for nombre in sublista if nombre in disponibles]
        if not hallados:
            return False, ()
        disparados.extend(hallados)

    for nombre in regla.ninguno:
        if nombre in disponibles:
            return False, ()

    # Sin duplicar y en orden de aparición: un mismo bloque puede estar citado
    # en "todos" y en una sublista.
    vistos: dict[str, None] = {}
    for nombre in disparados:
        vistos.setdefault(nombre, None)
    return True, tuple(vistos)


def clasificar(protocolo: Protocolo, presentes: Iterable[str]) -> str:
    """Etiqueta temática del registro: la **primera** que cuadre, o ``"NR"``.

    El orden de ``clasificacion`` en el protocolo es, por tanto, una decisión de
    la persona que lo escribió: la etiqueta más específica va primero. No se
    devuelven varias etiquetas a propósito, para que cada registro cuente una
    sola vez en los recuentos por tema.
    """
    disponibles = set(presentes)
    for etiqueta in protocolo.clasificacion:
        if all(nombre in disponibles for nombre in etiqueta.todos):
            return etiqueta.etiqueta
    return NR


def _sin_dato(valor: Any) -> bool:
    """¿Este campo no viene reportado?"""
    if valor is None:
        return True
    if isinstance(valor, str):
        return not valor.strip() or valor.strip() == NR
    return False


def _mapa_de_terminos(protocolo: Protocolo) -> dict[str, tuple[str, ...]]:
    """Bloques y grupos en un solo diccionario nombre -> términos.

    Los nombres no pueden chocar: el protocolo se valida antes justamente para
    que un nombre citado en una regla sea inequívoco.
    """
    return {**protocolo.bloques, **protocolo.grupos}


def decidir(
    registro: Mapping[str, Any],
    protocolo: Protocolo,
    mapa: Mapping[str, tuple[str, ...]] | None = None,
) -> Decision:
    """Decide sobre un registro siguiendo el orden documentado en el módulo.

    Devuelve siempre una `Decision` con ``decidido_por="filtro"``: la decisión
    manual se aplica después, con `aplicar_manual`, para que la del filtro no se
    pierda.
    """
    if mapa is None:
        mapa = _mapa_de_terminos(protocolo)

    identificador = str(registro.get("identificador", NR))
    texto = texto_buscable(registro.get("titulo"), registro.get("resumen"))
    detectados = nombres_presentes(mapa, texto)
    presentes = tuple(detectados)
    etiqueta = clasificar(protocolo, presentes)

    def decision(
        cual: str,
        motivo: str,
        categoria: str = "",
        bloques: tuple[str, ...] = (),
        regla: str = NR,
    ) -> Decision:
        return Decision(
            identificador=identificador,
            decision=cual,
            motivo=motivo,
            categoria=categoria,
            bloques=bloques,
            bloques_presentes=presentes,
            clasificacion=etiqueta,
            regla=regla,
            registro=registro,
        )

    # 1. Ventana temporal.
    inicio, fin = protocolo.ventana
    anio = registro.get("anio")
    if _sin_dato(anio) or not isinstance(anio, int) or isinstance(anio, bool):
        return decision(
            "dudoso",
            f"El año no viene reportado ({NR}), así que la ventana temporal "
            f"{inicio}-{fin} no se puede comprobar. Lo decide una persona.",
        )
    if not inicio <= anio <= fin:
        return decision(
            "excluir",
            f"Fuera de la ventana temporal {inicio}-{fin}: el registro es de {anio}.",
            CATEGORIA_VENTANA,
        )

    # 2. Idioma.
    idioma = registro.get("idioma")
    if _sin_dato(idioma):
        return decision(
            "dudoso",
            f"El idioma no viene reportado ({NR}), así que no se puede comprobar "
            f"contra los admitidos ({', '.join(protocolo.idiomas)}). Lo decide "
            f"una persona.",
        )
    if idioma not in protocolo.idiomas:
        return decision(
            "excluir",
            f"Idioma «{idioma}» fuera de los admitidos por el protocolo "
            f"({', '.join(protocolo.idiomas)}).",
            CATEGORIA_IDIOMA,
        )

    # 3. ¿Hay resumen? Sin él no es cribable en automático.
    if _sin_dato(registro.get("resumen")):
        cual = protocolo.reglas.sin_resumen
        motivo = (
            f"No trae resumen ({NR}), así que no es cribable en automático: las "
            f"reglas de bloques no tienen texto que leer. Lo decide una persona "
            f"(AGENTS.md, regla 4)."
        )
        categoria = CATEGORIA_SIN_RESUMEN if cual == "excluir" else ""
        return decision(cual, motivo, categoria)

    # 4. Exclusión temática.
    excluyentes = terminos_presentes(texto, protocolo.exclusion)
    if excluyentes:
        citados = ", ".join(f"«{t}»" for t in excluyentes)
        return decision(
            "excluir",
            f"Exclusión temática: el texto trae {citados}, que el protocolo "
            f"excluye por tema.",
            CATEGORIA_TEMA,
        )

    # 5. Reglas de bloques: primero incluir, luego dudoso.
    for cual in ("incluir", "dudoso"):
        for indice, regla in enumerate(getattr(protocolo.reglas, cual)):
            cumple, disparados = regla_se_cumple(regla, presentes)
            if cumple:
                return decision(
                    cual,
                    regla.motivo,
                    bloques=disparados,
                    regla=f"{cual}[{indice}]",
                )

    detalle = ", ".join(presentes) if presentes else "ninguno"
    return decision(
        "excluir",
        f"No cumple ninguna regla de inclusión ni de duda del protocolo. Bloques "
        f"detectados en el texto: {detalle}.",
        CATEGORIA_SIN_REGLA,
    )


def aplicar_manual(decision: Decision, manual: DecisionManual) -> Decision:
    """Sobreescribe una decisión del filtro con una decisión manual.

    La del filtro **no se borra**: queda en ``decision_filtro`` y
    ``motivo_filtro``, y ``decidido_por`` pasa a ser el autor. Es lo que permite
    comparar después al filtro con la persona.
    """
    categoria = decision.categoria
    if manual.decision == "excluir":
        # Una exclusión del modelo no se cuenta con las de una persona: en el
        # PRISMA hay que poder ver cuántas descartó una máquina pequeña.
        categoria = (
            CATEGORIA_MODELO if es_autor_modelo(manual.autor) else CATEGORIA_MANUAL
        )
    elif categoria:
        # Ya no está excluido por esa categoría, así que no debe contarse en ella.
        categoria = ""
    return Decision(
        identificador=decision.identificador,
        decision=manual.decision,
        motivo=f"{manual.motivo} [{manual.autor}, {manual.fecha}]",
        categoria=categoria,
        bloques=decision.bloques,
        bloques_presentes=decision.bloques_presentes,
        clasificacion=decision.clasificacion,
        regla=decision.regla,
        decidido_por=manual.autor,
        decision_filtro=decision.decision,
        motivo_filtro=decision.motivo,
        registro=decision.registro,
    )


# ---------------------------------------------------------------------------
# Decisiones manuales
# ---------------------------------------------------------------------------


def validar_decisiones(
    datos: Any, ruta: Path | None = None
) -> dict[str, DecisionManual]:
    """Valida el contenido de `decisiones.json` y lo devuelve indexado por id.

    Admite dos formas: un objeto ``{"R0007": {...}}`` —la canónica— o una lista
    de objetos con ``identificador`` dentro, que es más cómoda de ir añadiendo a
    mano. Lanza `ErrorCribado` con **todos** los problemas encontrados.
    """
    errores: list[str] = []
    entradas: list[tuple[str, Any]] = []

    if isinstance(datos, dict):
        entradas = [(str(clave), valor) for clave, valor in datos.items()]
    elif isinstance(datos, list):
        for indice, elemento in enumerate(datos):
            if not isinstance(elemento, dict):
                errores.append(
                    f"decisiones[{indice}]: cada decisión debe ser un objeto."
                )
                continue
            identificador = str(elemento.get("identificador", "")).strip()
            if not identificador:
                errores.append(
                    f'decisiones[{indice}]: falta "identificador". En forma de '
                    f"lista, cada decisión tiene que decir sobre qué registro es."
                )
                continue
            entradas.append((identificador, elemento))
    else:
        raise ErrorCribado(
            "el archivo de decisiones debe ser un objeto de identificador -> "
            "decisión, o una lista de decisiones con su identificador.",
            ruta,
        )

    decisiones: dict[str, DecisionManual] = {}
    for identificador, crudo in entradas:
        campo = f"decisiones[{identificador!r}]"
        if not isinstance(crudo, dict):
            errores.append(f"{campo}: debe ser un objeto.")
            continue
        if identificador in decisiones:
            errores.append(
                f"{campo}: hay dos decisiones para el mismo registro. Deja solo "
                f"la que vale."
            )
            continue

        # Los problemas de esta entrada se cuentan aparte: un error en una
        # decisión no puede hacer que las siguientes se queden sin validar.
        antes = len(errores)

        decision = str(crudo.get("decision", "")).strip()
        if decision not in DECISIONES:
            errores.append(
                f"{campo}.decision: debe ser una de {', '.join(DECISIONES)}; se "
                f"encontró {crudo.get('decision')!r}."
            )
        faltantes = [
            nombre
            for nombre in ("motivo", "autor", "fecha")
            if not str(crudo.get(nombre, "")).strip()
        ]
        if faltantes:
            errores.append(
                f"{campo}: falta {', '.join(faltantes)}. Una decisión manual sin "
                f"motivo, autor y fecha no es auditable, y entonces no vale más "
                f"que la del filtro."
            )
        sobrantes = [
            clave
            for clave in crudo
            if clave
            not in ("identificador", "decision", "motivo", "autor", "fecha")
        ]
        if sobrantes:
            errores.append(
                f"{campo}: campo desconocido {', '.join(sorted(sobrantes))}. Los "
                f"permitidos son: decision, motivo, autor, fecha."
            )
        if len(errores) > antes:
            continue

        decisiones[identificador] = DecisionManual(
            identificador=identificador,
            decision=decision,
            motivo=str(crudo["motivo"]).strip(),
            autor=str(crudo["autor"]).strip(),
            fecha=str(crudo["fecha"]).strip(),
        )

    if errores:
        raise ErrorCribado(errores, ruta)
    return decisiones


def guardar_decisiones(
    ruta: Path | str, decisiones: Mapping[str, DecisionManual]
) -> None:
    """Escribe `decisiones.json` entero, ordenado por identificador.

    Ordenado para que el archivo no baile entre ejecuciones: se lee a mano y se
    compara entre versiones. Quien llama es responsable de haber mezclado lo que
    ya había con lo nuevo; aquí no se adivina nada.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    salida = {
        identificador: {
            "decision": decision.decision,
            "motivo": decision.motivo,
            "autor": decision.autor,
            "fecha": decision.fecha,
        }
        for identificador, decision in sorted(decisiones.items())
    }
    with open(ruta, "w", encoding="utf-8") as manejador:
        json.dump(salida, manejador, ensure_ascii=False, indent=2)
        manejador.write("\n")


def anadir_decisiones(
    ruta: Path | str, nuevas: Mapping[str, DecisionManual]
) -> dict[str, DecisionManual]:
    """Mete `nuevas` en `decisiones.json` sin tocar las que ya estaban.

    Una decisión nueva sobre un registro que ya tenía una la **sustituye**: es lo
    que se espera al corregir a mano una decisión anterior. Devuelve el archivo
    resultante ya leído.
    """
    todas = dict(leer_decisiones(ruta))
    todas.update(nuevas)
    guardar_decisiones(ruta, todas)
    return todas


def protocolo_registrado(carpeta: Path | str) -> Path | None:
    """La ruta del protocolo que la cosecha anotó en `estado.json`, si la hay.

    Así ``tatewari cribar demo`` no obliga a repetir ``--protocolo``: se criba
    con el mismo protocolo con el que se cosechó, que es lo único coherente. Si
    el estado no existe o no lo anotó, devuelve `None` y la CLI lo pide.
    """
    ruta = Path(carpeta) / NOMBRE_ESTADO
    if not ruta.is_file():
        return None
    try:
        with open(ruta, encoding="utf-8") as manejador:
            estado = json.load(manejador)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(estado, dict):
        return None
    anotada = estado.get("protocolo")
    if not anotada or anotada == NR:
        return None
    return Path(str(anotada))


def leer_decisiones(ruta: Path | str) -> dict[str, DecisionManual]:
    """Lee y valida `decisiones.json`. Si no existe, no hay decisiones manuales."""
    ruta = Path(ruta)
    if not ruta.is_file():
        return {}
    with open(ruta, encoding="utf-8") as manejador:
        try:
            datos = json.load(manejador)
        except json.JSONDecodeError as error:
            raise ErrorCribado(
                f"el archivo no es JSON válido: línea {error.lineno}, columna "
                f"{error.colno}: {error.msg}.",
                ruta,
            ) from error
    return validar_decisiones(datos, ruta)


# ---------------------------------------------------------------------------
# Cribado completo
# ---------------------------------------------------------------------------


@dataclass
class ResultadoCribado:
    """Lo que salió de cribar una revisión."""

    revision: str
    protocolo: str = NR
    fecha: str = NR
    identificados: int = 0
    duplicados_eliminados: int = 0
    decisiones: list[Decision] = field(default_factory=list)
    asignaciones: dict[str, str] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)

    @property
    def cribados(self) -> int:
        return len(self.decisiones)

    @property
    def conteos(self) -> Counter[str]:
        """Cuántos registros por decisión final."""
        contador: Counter[str] = Counter({cual: 0 for cual in DECISIONES})
        contador.update(d.decision for d in self.decisiones)
        return contador

    @property
    def motivos_de_exclusion(self) -> Counter[str]:
        """Cuántas exclusiones por categoría de motivo."""
        return Counter(
            d.categoria or CATEGORIA_SIN_REGLA
            for d in self.decisiones
            if d.decision == "excluir"
        )

    @property
    def manuales(self) -> int:
        return sum(1 for d in self.decisiones if d.es_manual)

    def por_decision(self, cual: str) -> list[Decision]:
        return [d for d in self.decisiones if d.decision == cual]

    def buscar(self, identificador: str) -> Decision:
        """La decisión de un registro. Útil en las pruebas y para depurar."""
        for decision in self.decisiones:
            if decision.identificador == identificador:
                return decision
        raise KeyError(f"No hay ninguna decisión para {identificador}")

    def flujo(self) -> prisma.Flujo:
        """Los números listos para el diagrama PRISMA."""
        return prisma.Flujo(
            revision=self.revision,
            protocolo=self.protocolo,
            fecha=self.fecha,
            identificados=self.identificados,
            duplicados_eliminados=self.duplicados_eliminados,
            conteos=dict(self.conteos),
            motivos=dict(self.motivos_de_exclusion),
            manuales=self.manuales,
        )

    def diagrama(self) -> str:
        """El diagrama PRISMA en texto."""
        return prisma.diagrama(self.flujo())

    def resumen(self) -> str:
        """Texto corto para la CLI, antes del diagrama."""
        conteos = self.conteos
        return (
            f"Revisión  : {self.revision}\n"
            f"Cribados  : {self.cribados} únicos de {self.identificados} "
            f"identificados ({self.duplicados_eliminados} duplicados)\n"
            f"Decisiones: {conteos['incluir']} incluir, {conteos['dudoso']} "
            f"dudoso, {conteos['excluir']} excluir"
        )


def cribar(
    registros: Iterable[Mapping[str, Any]],
    protocolo: Protocolo,
    decisiones_manuales: Mapping[str, DecisionManual] | None = None,
    asignaciones: Mapping[str, str] | None = None,
    revision: str = NR,
    fecha: str | None = None,
) -> ResultadoCribado:
    """Deduplica y criba una tanda de registros. No toca el disco ni la red.

    Es la función que prueban las pruebas de oro: entra una lista de registros
    crudos y sale la decisión de cada artículo único, con su motivo.
    """
    dedup: ResultadoDedup = deduplicar(registros, asignaciones)
    mapa = _mapa_de_terminos(protocolo)
    manuales = dict(decisiones_manuales or {})

    resultado = ResultadoCribado(
        revision=revision,
        protocolo=protocolo.titulo or NR,
        fecha=fecha or datetime.now().isoformat(timespec="seconds"),
        identificados=dedup.identificados,
        duplicados_eliminados=dedup.duplicados_eliminados,
        asignaciones=dict(dedup.asignaciones),
    )

    vistos: set[str] = set()
    for registro in dedup.unicos:
        decision = decidir(registro, protocolo, mapa)
        vistos.add(decision.identificador)
        manual = manuales.get(decision.identificador)
        if manual is not None:
            decision = aplicar_manual(decision, manual)
        resultado.decisiones.append(decision)

    for identificador in sorted(set(manuales) - vistos):
        resultado.avisos.append(
            f"Hay una decisión manual para {identificador}, pero ese registro no "
            f"está en esta cosecha. La decisión se conserva sin aplicar."
        )

    return resultado


class Cribado:
    """Criba una revisión ya cosechada y escribe sus salidas en disco.

    Lee de la carpeta de la revisión:

    - ``registros.json``: lo que dejó la cosecha, con duplicados.
    - ``identificadores.json``: los identificadores estables ya asignados.
    - ``decisiones.json``: las decisiones manuales, si hay.

    Y escribe en la misma carpeta ``cribado.csv``, ``prisma.txt`` y el
    ``identificadores.json`` actualizado.
    """

    def __init__(self, revision: str, protocolo: Protocolo, config: Config) -> None:
        self.revision = revision
        self.protocolo = protocolo
        self.config = config

    # -- Rutas -------------------------------------------------------------

    @property
    def carpeta(self) -> Path:
        return self.config.datos / self.revision

    @property
    def ruta_registros(self) -> Path:
        return self.carpeta / NOMBRE_REGISTROS

    @property
    def ruta_identificadores(self) -> Path:
        return self.carpeta / NOMBRE_IDENTIFICADORES

    @property
    def ruta_decisiones(self) -> Path:
        return self.carpeta / NOMBRE_DECISIONES

    @property
    def ruta_csv(self) -> Path:
        return self.carpeta / NOMBRE_CRIBADO

    @property
    def ruta_prisma(self) -> Path:
        return self.carpeta / NOMBRE_PRISMA

    # -- Entrada -----------------------------------------------------------

    def leer_registros(self) -> list[dict[str, Any]]:
        if not self.ruta_registros.is_file():
            raise ErrorCribado(
                f"no hay registros que cribar: falta {self.ruta_registros}. "
                f"Lanza antes «tatewari cosechar {self.revision}»."
            )
        with open(self.ruta_registros, encoding="utf-8") as manejador:
            try:
                datos = json.load(manejador)
            except json.JSONDecodeError as error:
                raise ErrorCribado(
                    f"el archivo no es JSON válido: línea {error.lineno}, "
                    f"columna {error.colno}: {error.msg}.",
                    self.ruta_registros,
                ) from error
        if not isinstance(datos, list):
            raise ErrorCribado(
                "debe ser una lista de registros.", self.ruta_registros
            )
        return [r for r in datos if isinstance(r, dict)]

    # -- Ejecución ---------------------------------------------------------

    def calcular(self) -> ResultadoCribado:
        """Criba la revisión **sin escribir nada**.

        Es lo que necesitan las órdenes que solo miran (`pendientes`) o que
        tienen que comprobar algo antes de tocar disco (`decidir`): listar los
        dudosos no debería reescribir el CSV por el camino.
        """
        return cribar(
            self.leer_registros(),
            self.protocolo,
            decisiones_manuales=leer_decisiones(self.ruta_decisiones),
            asignaciones=leer_asignaciones(self.ruta_identificadores),
            revision=self.revision,
        )

    def ejecutar(self) -> ResultadoCribado:
        """Criba la revisión, escribe las salidas y devuelve el resultado."""
        resultado = self.calcular()

        self.carpeta.mkdir(parents=True, exist_ok=True)
        guardar_asignaciones(self.ruta_identificadores, resultado.asignaciones)
        self.escribir_csv(resultado)
        self.escribir_prisma(resultado)
        return resultado

    # -- Salidas -----------------------------------------------------------

    def escribir_csv(self, resultado: ResultadoCribado) -> Path:
        """Escribe `cribado.csv`: una fila por registro único.

        El escapado lo hace el módulo `csv`, que es quien sabe hacerlo: los
        títulos llevan comas y comillas, y armar el CSV a mano con `join` es
        cómo se rompen estos archivos. `newline=""` es obligatorio en Windows,
        si no el módulo escribe ``\\r\\r\\n``.

        Va en UTF-8 **sin** BOM: la excepción del BOM que autoriza AGENTS.md es
        solo para `search_log.csv`.
        """
        self.carpeta.mkdir(parents=True, exist_ok=True)
        with open(self.ruta_csv, "w", encoding="utf-8", newline="") as manejador:
            escritor = csv.DictWriter(
                manejador, fieldnames=list(COLUMNAS_CRIBADO), lineterminator="\n"
            )
            escritor.writeheader()
            for decision in resultado.decisiones:
                escritor.writerow(decision.fila())
        return self.ruta_csv

    def escribir_prisma(self, resultado: ResultadoCribado) -> Path:
        """Escribe `prisma.txt` con el diagrama de flujo."""
        self.carpeta.mkdir(parents=True, exist_ok=True)
        with open(self.ruta_prisma, "w", encoding="utf-8", newline="\n") as manejador:
            manejador.write(resultado.diagrama())
            manejador.write("\n")
        return self.ruta_prisma
