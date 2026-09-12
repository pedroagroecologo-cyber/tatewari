"""Carga y validación del protocolo de búsqueda en JSON.

El protocolo es el contrato de datos de toda la revisión: de él salen las
ecuaciones de búsqueda, el cribado y la clasificación. Si está mal, todo lo
demás está mal en silencio, así que aquí se valida a fondo y se falla pronto.

Esquema
-------

    {
      "titulo": "...",
      "ventana": [2016, 2026],
      "idiomas": ["es", "en"],
      "tipos": ["article", "review"],
      "bloques":   { "nombre_bloque": ["término", "..."] },
      "exclusion": ["término", "..."],
      "grupos":    { "nombre_grupo": ["término", "..."] },
      "clasificacion": [ { "etiqueta": "...", "todos": ["nombre_bloque"] } ],
      "consulta": { "eje": "nombre_bloque", "cruce": ["término", "..."] },
      "reglas": {
        "sinResumen": "dudoso",
        "incluir": [ { "todos": [], "alguno_de": [[]], "ninguno": [], "motivo": "" } ],
        "dudoso":  [ { "todos": [], "alguno_de": [[]], "ninguno": [], "motivo": "" } ]
      }
    }

Semántica de una regla
----------------------

Una regla **se cumple** para un registro cuando se dan las tres condiciones a
la vez:

- ``todos``: están presentes **todos** los bloques de la lista.
- ``alguno_de``: de **cada** sublista hay presente **al menos uno**.
- ``ninguno``: no está presente **ninguno** de los de la lista.

Los tres campos son opcionales, pero al menos uno debe aparecer: una regla sin
ninguna condición se cumpliría siempre, que casi nunca es lo que se quiere.
Una lista ausente no impone condición; ``motivo`` es texto libre que se copia
tal cual a la bitácora.

La evaluación de las reglas contra registros concretos es cribado, y llega en
un encargo posterior. Aquí solo se valida la forma.

Nombres
-------

Los nombres citados en ``clasificacion``, en ``consulta.eje`` y dentro de las
reglas deben estar definidos en ``bloques`` o en ``grupos``. Citar un nombre
que no existe es un **error**, no una advertencia: es una condición que jamás
se cumpliría y que dejaría el cribado mudo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "Protocolo",
    "Regla",
    "Reglas",
    "Clasificacion",
    "Consulta",
    "ErrorProtocolo",
    "cargar_protocolo",
    "validar_protocolo",
    "VALORES_SIN_RESUMEN",
]

VALORES_SIN_RESUMEN = ("incluir", "dudoso", "excluir")

_CAMPOS_OBLIGATORIOS = ("titulo", "ventana", "idiomas", "tipos", "bloques")
_CAMPOS_CONOCIDOS = (
    "titulo",
    "ventana",
    "idiomas",
    "tipos",
    "bloques",
    "exclusion",
    "grupos",
    "clasificacion",
    "consulta",
    "reglas",
)
_CAMPOS_REGLA = ("todos", "alguno_de", "ninguno", "motivo")
_CONDICIONES_REGLA = ("todos", "alguno_de", "ninguno")


class ErrorProtocolo(Exception):
    """El protocolo no cumple el esquema.

    Reúne **todos** los problemas encontrados, no solo el primero: corregir un
    protocolo de uno en uno es un suplicio.
    """

    def __init__(self, errores: list[str], ruta: Path | None = None) -> None:
        self.errores = list(errores)
        self.ruta = ruta
        super().__init__(str(self))

    def __str__(self) -> str:
        origen = f" en {self.ruta}" if self.ruta is not None else ""
        plural = "es" if len(self.errores) != 1 else ""
        cabecera = (
            f"El protocolo{origen} tiene {len(self.errores)} "
            f"error{plural} de validación:"
        )
        detalle = "\n".join(f"  {i}. {e}" for i, e in enumerate(self.errores, 1))
        return f"{cabecera}\n{detalle}"


@dataclass(frozen=True)
class Regla:
    """Una condición de inclusión o de duda. Ver la semántica en el módulo."""

    todos: tuple[str, ...] = ()
    alguno_de: tuple[tuple[str, ...], ...] = ()
    ninguno: tuple[str, ...] = ()
    motivo: str = "NR"


@dataclass(frozen=True)
class Reglas:
    """Las reglas de cribado del protocolo."""

    sin_resumen: str = "dudoso"
    incluir: tuple[Regla, ...] = ()
    dudoso: tuple[Regla, ...] = ()


@dataclass(frozen=True)
class Clasificacion:
    """Etiqueta temática que se aplica si están presentes todos sus nombres."""

    etiqueta: str
    todos: tuple[str, ...] = ()


@dataclass(frozen=True)
class Consulta:
    """Cómo se arman las ecuaciones: un bloque eje cruzado con unos términos."""

    eje: str
    cruce: tuple[str, ...] = ()


@dataclass(frozen=True)
class Protocolo:
    """Protocolo de búsqueda ya validado."""

    titulo: str
    ventana: tuple[int, int]
    idiomas: tuple[str, ...]
    tipos: tuple[str, ...]
    bloques: dict[str, tuple[str, ...]]
    exclusion: tuple[str, ...] = ()
    grupos: dict[str, tuple[str, ...]] = field(default_factory=dict)
    clasificacion: tuple[Clasificacion, ...] = ()
    consulta: Consulta | None = None
    reglas: Reglas = field(default_factory=Reglas)
    ruta: Path | None = None

    @property
    def nombres_definidos(self) -> set[str]:
        """Nombres citables en reglas y clasificación: bloques más grupos."""
        return set(self.bloques) | set(self.grupos)

    def terminos_de(self, nombre: str) -> tuple[str, ...]:
        """Términos de un bloque o de un grupo."""
        if nombre in self.bloques:
            return self.bloques[nombre]
        if nombre in self.grupos:
            return self.grupos[nombre]
        raise KeyError(f"No existe el bloque ni el grupo: {nombre}")

    @property
    def numero_de_ecuaciones(self) -> int:
        """Ecuaciones previstas: cada término del eje por cada término del cruce.

        Sin ``consulta`` no hay ecuaciones. Con un cruce vacío queda una
        ecuación por término del eje.
        """
        if self.consulta is None:
            return 0
        terminos_eje = len(self.terminos_de(self.consulta.eje))
        return terminos_eje * max(1, len(self.consulta.cruce))

    def resumen(self) -> str:
        """Resumen legible del protocolo, para la CLI."""
        lineas = [
            f"Título  : {self.titulo}",
            f"Ventana : {self.ventana[0]}-{self.ventana[1]}",
            f"Idiomas : {', '.join(self.idiomas)}",
            f"Tipos   : {', '.join(self.tipos)}",
            "",
            f"Bloques ({len(self.bloques)}):",
        ]
        ancho = max((len(n) for n in self.bloques), default=0)
        for nombre, terminos in self.bloques.items():
            lineas.append(f"  {nombre.ljust(ancho)}  {len(terminos):>3} términos")
        if self.grupos:
            lineas.append("")
            lineas.append(f"Grupos ({len(self.grupos)}):")
            ancho_grupo = max(len(n) for n in self.grupos)
            for nombre, terminos in self.grupos.items():
                lineas.append(
                    f"  {nombre.ljust(ancho_grupo)}  {len(terminos):>3} términos"
                )
        lineas.append("")
        lineas.append(f"Términos de exclusión      : {len(self.exclusion)}")
        lineas.append(f"Etiquetas de clasificación : {len(self.clasificacion)}")
        lineas.append(
            f"Reglas                     : {len(self.reglas.incluir)} de "
            f"inclusión, {len(self.reglas.dudoso)} de duda "
            f"(sin resumen -> {self.reglas.sin_resumen})"
        )
        if self.consulta is not None:
            eje = self.consulta.eje
            lineas.append("")
            lineas.append(
                f"Consulta : eje {eje} ({len(self.terminos_de(eje))} términos) "
                f"x cruce ({len(self.consulta.cruce)} términos)"
            )
        lineas.append(f"Ecuaciones previstas : {self.numero_de_ecuaciones}")
        return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------


def _tipo(valor: Any) -> str:
    """Nombre legible en español del tipo de un valor, para los mensajes."""
    nombres = {
        dict: "un objeto",
        list: "una lista",
        str: "un texto",
        int: "un número entero",
        float: "un número decimal",
        bool: "un booleano",
        type(None): "un nulo",
    }
    return nombres.get(type(valor), f"un {type(valor).__name__}")


def _es_cadena_util(valor: Any) -> bool:
    return isinstance(valor, str) and bool(valor.strip())


def _validar_lista_de_cadenas(
    valor: Any,
    campo: str,
    errores: list[str],
    *,
    permitir_vacia: bool = True,
) -> tuple[str, ...]:
    """Comprueba que ``valor`` es una lista de textos no vacíos."""
    if not isinstance(valor, list):
        errores.append(f"{campo}: debe ser una lista de textos, no {_tipo(valor)}.")
        return ()
    if not valor and not permitir_vacia:
        errores.append(f"{campo}: la lista no puede estar vacía.")
        return ()
    limpios: list[str] = []
    for indice, elemento in enumerate(valor):
        if not _es_cadena_util(elemento):
            errores.append(
                f"{campo}[{indice}]: se esperaba un texto no vacío y se "
                f"encontró {elemento!r}."
            )
            continue
        limpios.append(elemento.strip())
    return tuple(limpios)


def _validar_diccionario_de_listas(
    valor: Any,
    campo: str,
    errores: list[str],
    *,
    obligatorio: bool,
) -> dict[str, tuple[str, ...]]:
    """Comprueba que ``valor`` es un objeto de nombre -> lista de términos."""
    if valor is None:
        if obligatorio:
            errores.append(f"{campo}: falta el campo obligatorio.")
        return {}
    if not isinstance(valor, dict):
        errores.append(
            f"{campo}: debe ser un objeto de nombre -> lista de términos, "
            f"no {_tipo(valor)}."
        )
        return {}
    if obligatorio and not valor:
        errores.append(f"{campo}: no puede estar vacío.")
    resultado: dict[str, tuple[str, ...]] = {}
    for nombre, terminos in valor.items():
        if not _es_cadena_util(nombre):
            errores.append(f"{campo}: hay un nombre vacío o que no es texto.")
            continue
        resultado[nombre] = _validar_lista_de_cadenas(
            terminos, f"{campo}.{nombre}", errores, permitir_vacia=False
        )
    return resultado


def _validar_nombres(
    nombres: tuple[str, ...],
    campo: str,
    definidos: set[str],
    errores: list[str],
) -> None:
    """Comprueba que cada nombre citado existe en ``bloques`` o en ``grupos``."""
    for indice, nombre in enumerate(nombres):
        if nombre not in definidos:
            errores.append(
                f"{campo}[{indice}]: el bloque {nombre!r} no existe en "
                f'"bloques" ni en "grupos".'
            )


def _validar_ventana(valor: Any, errores: list[str]) -> tuple[int, int]:
    campo = "ventana"
    if valor is None:
        errores.append(f"{campo}: falta el campo obligatorio.")
        return (0, 0)
    if not isinstance(valor, list) or len(valor) != 2:
        errores.append(
            f"{campo}: debe ser una lista de dos años, por ejemplo [2016, 2026]."
        )
        return (0, 0)
    anios: list[int] = []
    for indice, elemento in enumerate(valor):
        if isinstance(elemento, bool) or not isinstance(elemento, int):
            errores.append(
                f"{campo}[{indice}]: se esperaba un año entero y se encontró "
                f"{elemento!r}."
            )
            anios.append(0)
            continue
        if not 1500 <= elemento <= 2200:
            errores.append(f"{campo}[{indice}]: el año {elemento} está fuera de rango.")
        anios.append(elemento)
    if anios[0] and anios[1] and anios[0] > anios[1]:
        errores.append(
            f"{campo}: el año inicial ({anios[0]}) es posterior al final ({anios[1]})."
        )
    return (anios[0], anios[1])


def _validar_regla(
    datos: Any,
    campo: str,
    definidos: set[str],
    errores: list[str],
) -> Regla | None:
    if not isinstance(datos, dict):
        errores.append(f"{campo}: cada regla debe ser un objeto, no {_tipo(datos)}.")
        return None

    for clave in datos:
        if clave not in _CAMPOS_REGLA:
            errores.append(
                f"{campo}: campo desconocido {clave!r}. Los permitidos son: "
                f"{', '.join(_CAMPOS_REGLA)}."
            )

    if not any(clave in datos for clave in _CONDICIONES_REGLA):
        errores.append(
            f"{campo}: la regla no tiene ninguna condición. Debe llevar al menos "
            f'uno de "todos", "alguno_de" o "ninguno".'
        )

    todos: tuple[str, ...] = ()
    if "todos" in datos:
        todos = _validar_lista_de_cadenas(datos["todos"], f"{campo}.todos", errores)
        _validar_nombres(todos, f"{campo}.todos", definidos, errores)

    alguno_de: list[tuple[str, ...]] = []
    if "alguno_de" in datos:
        bruto = datos["alguno_de"]
        if not isinstance(bruto, list):
            errores.append(
                f"{campo}.alguno_de: debe ser una lista de listas de nombres, "
                f"no {_tipo(bruto)}."
            )
        else:
            for indice, sublista in enumerate(bruto):
                subcampo = f"{campo}.alguno_de[{indice}]"
                if not isinstance(sublista, list):
                    errores.append(
                        f'{subcampo}: cada elemento de "alguno_de" debe ser a su '
                        f"vez una lista de nombres, no {_tipo(sublista)}."
                    )
                    continue
                nombres = _validar_lista_de_cadenas(
                    sublista, subcampo, errores, permitir_vacia=False
                )
                _validar_nombres(nombres, subcampo, definidos, errores)
                alguno_de.append(nombres)

    ninguno: tuple[str, ...] = ()
    if "ninguno" in datos:
        ninguno = _validar_lista_de_cadenas(
            datos["ninguno"], f"{campo}.ninguno", errores
        )
        _validar_nombres(ninguno, f"{campo}.ninguno", definidos, errores)

    motivo = "NR"
    if "motivo" in datos:
        if not _es_cadena_util(datos["motivo"]):
            errores.append(f"{campo}.motivo: debe ser un texto no vacío.")
        else:
            motivo = datos["motivo"].strip()

    return Regla(
        todos=todos,
        alguno_de=tuple(alguno_de),
        ninguno=ninguno,
        motivo=motivo,
    )


def _validar_clasificacion(
    valor: Any, definidos: set[str], errores: list[str]
) -> tuple[Clasificacion, ...]:
    if not isinstance(valor, list):
        errores.append(
            f"clasificacion: debe ser una lista de objetos, no {_tipo(valor)}."
        )
        return ()
    etiquetas: list[Clasificacion] = []
    for indice, elemento in enumerate(valor):
        campo = f"clasificacion[{indice}]"
        if not isinstance(elemento, dict):
            errores.append(f"{campo}: debe ser un objeto, no {_tipo(elemento)}.")
            continue
        for clave in elemento:
            if clave not in ("etiqueta", "todos"):
                errores.append(
                    f"{campo}: campo desconocido {clave!r}. Los permitidos son: "
                    f"etiqueta, todos."
                )
        etiqueta = ""
        if not _es_cadena_util(elemento.get("etiqueta")):
            errores.append(f"{campo}.etiqueta: debe ser un texto no vacío.")
        else:
            etiqueta = elemento["etiqueta"].strip()
        nombres = _validar_lista_de_cadenas(
            elemento.get("todos", []),
            f"{campo}.todos",
            errores,
            permitir_vacia=False,
        )
        _validar_nombres(nombres, f"{campo}.todos", definidos, errores)
        etiquetas.append(Clasificacion(etiqueta=etiqueta, todos=nombres))
    return tuple(etiquetas)


def _validar_consulta(
    valor: Any, definidos: set[str], errores: list[str]
) -> Consulta | None:
    if not isinstance(valor, dict):
        errores.append(f"consulta: debe ser un objeto, no {_tipo(valor)}.")
        return None
    for clave in valor:
        if clave not in ("eje", "cruce"):
            errores.append(
                f"consulta: campo desconocido {clave!r}. Los permitidos son: "
                f"eje, cruce."
            )
    eje = ""
    if not _es_cadena_util(valor.get("eje")):
        errores.append(
            "consulta.eje: debe ser el nombre de un bloque, como texto no vacío."
        )
    else:
        eje = valor["eje"].strip()
        if eje not in definidos:
            errores.append(
                f'consulta.eje: el bloque {eje!r} no existe en "bloques" ni en '
                f'"grupos".'
            )
    cruce = _validar_lista_de_cadenas(valor.get("cruce", []), "consulta.cruce", errores)
    if eje not in definidos:
        return None
    return Consulta(eje=eje, cruce=cruce)


def _validar_reglas(valor: Any, definidos: set[str], errores: list[str]) -> Reglas:
    if not isinstance(valor, dict):
        errores.append(f"reglas: debe ser un objeto, no {_tipo(valor)}.")
        return Reglas()
    for clave in valor:
        if clave not in ("sinResumen", "incluir", "dudoso"):
            errores.append(
                f"reglas: campo desconocido {clave!r}. Los permitidos son: "
                f"sinResumen, incluir, dudoso."
            )

    sin_resumen = "dudoso"
    if "sinResumen" in valor:
        crudo = valor["sinResumen"]
        if crudo not in VALORES_SIN_RESUMEN:
            errores.append(
                f"reglas.sinResumen: debe ser uno de "
                f"{', '.join(VALORES_SIN_RESUMEN)}; se encontró {crudo!r}."
            )
        else:
            sin_resumen = crudo

    listas: dict[str, tuple[Regla, ...]] = {}
    for nombre_lista in ("incluir", "dudoso"):
        leidas: list[Regla] = []
        if nombre_lista in valor:
            contenido = valor[nombre_lista]
            if not isinstance(contenido, list):
                errores.append(
                    f"reglas.{nombre_lista}: debe ser una lista de reglas, "
                    f"no {_tipo(contenido)}."
                )
            else:
                for indice, regla_bruta in enumerate(contenido):
                    regla = _validar_regla(
                        regla_bruta,
                        f"reglas.{nombre_lista}[{indice}]",
                        definidos,
                        errores,
                    )
                    if regla is not None:
                        leidas.append(regla)
        listas[nombre_lista] = tuple(leidas)

    return Reglas(
        sin_resumen=sin_resumen,
        incluir=listas["incluir"],
        dudoso=listas["dudoso"],
    )


def validar_protocolo(datos: Any, ruta: Path | None = None) -> Protocolo:
    """Valida un protocolo ya deserializado y devuelve el objeto ``Protocolo``.

    Lanza ``ErrorProtocolo`` con **todos** los errores encontrados. Los
    mensajes señalan el campo exacto, en notación de punto y corchete
    (``reglas.incluir[0].todos[2]``).
    """
    errores: list[str] = []

    if not isinstance(datos, dict):
        raise ErrorProtocolo(
            [f"La raíz del protocolo debe ser un objeto JSON, no {_tipo(datos)}."],
            ruta,
        )

    for clave in datos:
        if clave not in _CAMPOS_CONOCIDOS:
            errores.append(
                f"Campo desconocido en la raíz: {clave!r}. Los permitidos son: "
                f"{', '.join(_CAMPOS_CONOCIDOS)}."
            )
    for clave in _CAMPOS_OBLIGATORIOS:
        if clave not in datos:
            errores.append(f"{clave}: falta el campo obligatorio.")

    titulo = ""
    if "titulo" in datos:
        if not _es_cadena_util(datos["titulo"]):
            errores.append("titulo: debe ser un texto no vacío.")
        else:
            titulo = datos["titulo"].strip()

    ventana = _validar_ventana(datos.get("ventana"), errores)

    idiomas: tuple[str, ...] = ()
    if "idiomas" in datos:
        idiomas = _validar_lista_de_cadenas(
            datos["idiomas"], "idiomas", errores, permitir_vacia=False
        )

    tipos: tuple[str, ...] = ()
    if "tipos" in datos:
        tipos = _validar_lista_de_cadenas(
            datos["tipos"], "tipos", errores, permitir_vacia=False
        )

    bloques = _validar_diccionario_de_listas(
        datos.get("bloques"), "bloques", errores, obligatorio=True
    )
    grupos = _validar_diccionario_de_listas(
        datos.get("grupos"), "grupos", errores, obligatorio=False
    )
    for nombre in sorted(set(bloques) & set(grupos)):
        errores.append(
            f'grupos.{nombre}: el nombre ya está usado en "bloques". Un nombre '
            f"citado en una regla tiene que ser inequívoco."
        )
    definidos = set(bloques) | set(grupos)

    exclusion: tuple[str, ...] = ()
    if "exclusion" in datos:
        exclusion = _validar_lista_de_cadenas(datos["exclusion"], "exclusion", errores)

    clasificacion: tuple[Clasificacion, ...] = ()
    if "clasificacion" in datos:
        clasificacion = _validar_clasificacion(
            datos["clasificacion"], definidos, errores
        )

    consulta: Consulta | None = None
    if "consulta" in datos:
        consulta = _validar_consulta(datos["consulta"], definidos, errores)

    reglas = Reglas()
    if "reglas" in datos:
        reglas = _validar_reglas(datos["reglas"], definidos, errores)

    if errores:
        raise ErrorProtocolo(errores, ruta)

    return Protocolo(
        titulo=titulo,
        ventana=ventana,
        idiomas=idiomas,
        tipos=tipos,
        bloques=bloques,
        exclusion=exclusion,
        grupos=grupos,
        clasificacion=clasificacion,
        consulta=consulta,
        reglas=reglas,
        ruta=ruta,
    )


def cargar_protocolo(ruta: Path | str) -> Protocolo:
    """Lee un protocolo desde un archivo JSON y lo valida.

    Lanza ``FileNotFoundError`` si no existe y ``ErrorProtocolo`` si el JSON
    está mal formado o el contenido no cumple el esquema.
    """
    ruta = Path(ruta)
    if not ruta.is_file():
        raise FileNotFoundError(f"No existe el protocolo: {ruta}")
    with open(ruta, encoding="utf-8") as manejador:
        try:
            datos = json.load(manejador)
        except json.JSONDecodeError as error:
            raise ErrorProtocolo(
                [
                    f"El archivo no es JSON válido: línea {error.lineno}, "
                    f"columna {error.colno}: {error.msg}."
                ],
                ruta,
            ) from error
    return validar_protocolo(datos, ruta)
