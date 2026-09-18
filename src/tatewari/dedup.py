"""Deduplicación de registros e identificadores estables.

La cosecha guarda lo que vino, duplicados incluidos: el mismo artículo llega por
varias ecuaciones y por varias fuentes. Aquí se agrupan.

La clave
--------

1. El **DOI normalizado**: sin el prefijo ``https://doi.org/``, sin ``doi:``, en
   minúsculas y sin espacios. Un DOI es único por definición, así que cuando lo
   hay manda él.
2. Si no hay DOI, el **título reducido a letras y números** (`clave_alfanumerica`
   de `texto`). Así «Tanque séptico — caracterización» y «Tanque septico -
   caracterizacion» caen en el mismo grupo, que es el caso real de un preprint y
   su versión publicada.

El identificador estable
------------------------

Cada artículo único recibe un identificador correlativo: ``R0001``, ``R0002``…
Y **se conserva entre cosechas sucesivas**. Esto no es cosmética: una persona
decide a mano sobre ``R0007``, se cosechan cien registros más, y si los
identificadores se recalcularan, ``R0007`` pasaría a ser otro artículo y la
decisión manual se habría despegado de su artículo sin que nadie se enterase.

Por eso la asignación clave -> identificador se guarda en disco
(`identificadores.json`) y solo crece: los identificadores ya dados no se
reordenan ni se reutilizan nunca, ni siquiera si un artículo desaparece de la
cosecha.

Lo que se conserva al fusionar
------------------------------

- ``consulta_origen`` **acumula** todas las ecuaciones por las que llegó el
  artículo. Saber que un artículo apareció en cinco ecuaciones distintas es un
  dato de la revisión, y perderlo al deduplicar es perder información.
- El resto de campos se toman del primer registro visto, y cada ``"NR"`` se
  rellena con el primer valor real que traiga un duplicado posterior. No se
  inventa nada (AGENTS.md, regla 2): se copia un dato que alguna fuente sí
  reportó. Si ninguna lo reportó, se queda en ``"NR"``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .fuentes import CAMPOS_REGISTRO, NR
from .texto import clave_alfanumerica, normalizar

__all__ = [
    "NOMBRE_IDENTIFICADORES",
    "PLANTILLA_IDENTIFICADOR",
    "Grupo",
    "ResultadoDedup",
    "normalizar_doi",
    "clave_de_registro",
    "deduplicar",
    "leer_asignaciones",
    "guardar_asignaciones",
]

NOMBRE_IDENTIFICADORES = "identificadores.json"

#: Cuatro cifras dan hasta 9999 registros únicos y ordenan bien como texto.
#: Si una revisión pasa de ahí, el número crece y el orden alfabético se rompe,
#: pero el identificador sigue siendo único, que es lo que importa.
PLANTILLA_IDENTIFICADOR = "R{:04d}"

#: Prefijos con los que las fuentes adornan un DOI. Se quitan todos.
_PREFIJOS_DOI = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi.org/",
    "doi:",
)


def normalizar_doi(doi: object) -> str:
    """Devuelve el DOI en su forma canónica, o `""` si no hay DOI aprovechable.

    Quita el prefijo de URL, pasa a minúsculas y limpia los espacios. Devuelve
    cadena vacía —no ``"NR"``— cuando no hay nada: así quien llama distingue
    «no hay DOI» de «el DOI es la cadena NR» sin comparar con un centinela.
    """
    if doi is None:
        return ""
    texto = str(doi).strip()
    if not texto or texto == NR:
        return ""
    plano = normalizar(texto)
    for prefijo in _PREFIJOS_DOI:
        if plano.startswith(prefijo):
            plano = plano[len(prefijo) :]
            break
    return plano.strip().strip("/")


def clave_de_registro(registro: Mapping[str, Any], indice: int = 0) -> str:
    """Clave de deduplicación de un registro.

    Devuelve ``"doi:..."`` si hay DOI, ``"titulo:..."`` si no, y
    ``"registro:N"`` si el registro no trae ni DOI ni título: sin ninguno de los
    dos no se puede afirmar que sea el mismo artículo que otro, así que se queda
    solo en su grupo en vez de fundirse con cualquiera.
    """
    doi = normalizar_doi(registro.get("doi"))
    if doi:
        return f"doi:{doi}"
    # Ojo: un título sin reportar vale la cadena "NR", que reducida daría la
    # clave "nr" y fundiría en un solo artículo todos los registros sin título.
    crudo = registro.get("titulo")
    if not _es_nr(crudo):
        titulo = clave_alfanumerica(crudo)
        if titulo:
            return f"titulo:{titulo}"
    return f"registro:{indice}"


@dataclass
class Grupo:
    """Un artículo único y el rastro de por dónde llegó."""

    identificador: str
    clave: str
    registro: dict[str, Any]
    consulta_origen: list[str] = field(default_factory=list)
    copias: int = 1

    def como_registro(self) -> dict[str, Any]:
        """El registro fusionado, con su identificador y sus procedencias."""
        salida = dict(self.registro)
        salida["identificador"] = self.identificador
        salida["clave"] = self.clave
        salida["consulta_origen"] = list(self.consulta_origen) or [NR]
        salida["copias"] = self.copias
        return salida


@dataclass
class ResultadoDedup:
    """Lo que salió de deduplicar una tanda de registros."""

    identificados: int = 0
    grupos: list[Grupo] = field(default_factory=list)
    asignaciones: dict[str, str] = field(default_factory=dict)

    @property
    def unicos(self) -> list[dict[str, Any]]:
        """Los registros únicos, en el orden en que aparecieron."""
        return [grupo.como_registro() for grupo in self.grupos]

    @property
    def duplicados_eliminados(self) -> int:
        """Cuántos registros se fundieron con otro."""
        return self.identificados - len(self.grupos)

    def resumen(self) -> str:
        """Texto para la CLI."""
        return (
            f"Registros identificados : {self.identificados}\n"
            f"Duplicados eliminados   : {self.duplicados_eliminados}\n"
            f"Registros únicos        : {len(self.grupos)}"
        )


def _procedencias(registro: Mapping[str, Any]) -> list[str]:
    """Lee ``consulta_origen`` de un registro, venga como texto o como lista."""
    crudo = registro.get("consulta_origen")
    if crudo is None:
        return []
    valores = crudo if isinstance(crudo, (list, tuple)) else [crudo]
    limpias = []
    for valor in valores:
        texto = str(valor).strip()
        if texto and texto != NR:
            limpias.append(texto)
    return limpias


def _fusionar(grupo: Grupo, registro: Mapping[str, Any]) -> None:
    """Mete `registro` en `grupo` sin perder nada de lo que ya había.

    Los campos que el grupo tenga en ``"NR"`` se rellenan con el primer valor
    real que aparezca; los que ya tengan dato no se tocan, para que el registro
    no cambie de contenido según el orden en que llegaron las ecuaciones.
    """
    grupo.copias += 1
    for campo in CAMPOS_REGISTRO:
        actual = grupo.registro.get(campo, NR)
        nuevo = registro.get(campo, NR)
        if _es_nr(actual) and not _es_nr(nuevo):
            grupo.registro[campo] = nuevo
    for procedencia in _procedencias(registro):
        if procedencia not in grupo.consulta_origen:
            grupo.consulta_origen.append(procedencia)


def _es_nr(valor: Any) -> bool:
    """¿Este valor es un dato no reportado?"""
    if valor is None:
        return True
    if isinstance(valor, str):
        return not valor.strip() or valor.strip() == NR
    if isinstance(valor, (list, tuple)):
        return not valor or all(_es_nr(v) for v in valor)
    return False


def _siguiente_numero(asignaciones: Mapping[str, str]) -> int:
    """El número correlativo más alto ya usado, más uno.

    Se mira el máximo y no la cantidad: si una asignación se borró a mano, su
    identificador no se puede reutilizar, porque podría haber una decisión
    manual apuntando a él.
    """
    mayor = 0
    for identificador in asignaciones.values():
        digitos = str(identificador).lstrip("R")
        if digitos.isdigit():
            mayor = max(mayor, int(digitos))
    return mayor + 1


def deduplicar(
    registros: Iterable[Mapping[str, Any]],
    asignaciones: Mapping[str, str] | None = None,
) -> ResultadoDedup:
    """Agrupa los registros por artículo y les da su identificador estable.

    `asignaciones` es el mapa clave -> identificador de las cosechas anteriores.
    Las claves que ya lo tengan conservan su identificador; las nuevas siguen la
    numeración donde se quedó. El mapa devuelto en `ResultadoDedup.asignaciones`
    incluye las de antes y las nuevas, y es lo que hay que volver a guardar.
    """
    heredadas = dict(asignaciones or {})
    resultado = ResultadoDedup(asignaciones=dict(heredadas))
    siguiente = _siguiente_numero(heredadas)
    por_clave: dict[str, Grupo] = {}

    for indice, crudo in enumerate(registros):
        resultado.identificados += 1
        registro = {
            campo: crudo.get(campo, NR) for campo in CAMPOS_REGISTRO
        }
        clave = clave_de_registro(crudo, indice)

        grupo = por_clave.get(clave)
        if grupo is not None:
            _fusionar(grupo, crudo)
            continue

        identificador = resultado.asignaciones.get(clave)
        if identificador is None:
            identificador = PLANTILLA_IDENTIFICADOR.format(siguiente)
            siguiente += 1
            resultado.asignaciones[clave] = identificador

        grupo = Grupo(
            identificador=identificador,
            clave=clave,
            registro=registro,
            consulta_origen=_procedencias(crudo),
        )
        por_clave[clave] = grupo
        resultado.grupos.append(grupo)

    return resultado


def leer_asignaciones(ruta: Path | str) -> dict[str, str]:
    """Lee `identificadores.json`. Si no existe, devuelve un mapa vacío."""
    ruta = Path(ruta)
    if not ruta.is_file():
        return {}
    with open(ruta, encoding="utf-8") as manejador:
        datos = json.load(manejador)
    if not isinstance(datos, dict):
        return {}
    return {str(clave): str(valor) for clave, valor in datos.items()}


def guardar_asignaciones(ruta: Path | str, asignaciones: Mapping[str, str]) -> None:
    """Guarda el mapa clave -> identificador, ordenado por identificador.

    Ordenado para que el archivo no cambie de orden entre cosechas y el
    control de versiones muestre solo lo que de verdad se añadió.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ordenadas = dict(sorted(asignaciones.items(), key=lambda par: (par[1], par[0])))
    with open(ruta, "w", encoding="utf-8") as manejador:
        json.dump(ordenadas, manejador, ensure_ascii=False, indent=2)
        manejador.write("\n")
