"""Resolver el texto completo legal de los registros incluidos, con Unpaywall.

Qué hace, y qué no
------------------

Pregunta a Unpaywall por el DOI de cada registro **incluido** y, si existe una
versión en acceso abierto, guarda su URL en el registro. Si no existe, lo anota y
sigue.

**No hay una segunda vía.** Ni Sci-Hub, ni raspar la web de la editorial, ni
rodear el acceso de ninguna manera (AGENTS.md, regla 5). Cuando no hay versión
legal abierta, el registro va a `por-conseguir.md` y el texto se pide a mano por
la biblioteca institucional. Esa es la respuesta completa del programa a ese
caso, y es deliberada.

Solo los incluidos: un dudoso todavía puede caerse y un excluido ya se cayó, así
que gastar peticiones en ellos es gastar la cuota de un servicio gratuito para
nada.

Dónde se guarda
---------------

En dos sitios, y cada uno tiene su razón:

``texto_completo.json``
    El detalle completo de lo que dijo Unpaywall por cada registro: estado,
    versión, licencia, repositorio y la fecha de la consulta. Es también la
    **caché**: un DOI ya resuelto no se vuelve a preguntar salvo que se pida con
    ``--rehacer``. Una revisión de mil artículos son mil peticiones, y repetirlas
    en cada corrida es maltratar un servicio que es gratis.

``registros.json``
    Ahí se escribe el ``oa_url`` en el registro, que es lo que hace que la URL
    aparezca sola en `cribado.csv` y en las fichas exportadas sin más
    fontanería. Es el único campo que este módulo toca del archivo de la
    cosecha; todo lo demás se queda como vino.

La licencia importa
-------------------

Se guarda la licencia que declara Unpaywall porque no todas las versiones
abiertas permiten lo mismo. Que un PDF se pueda descargar no dice nada sobre si
se puede redistribuir, y esa distinción es de quien escribe la revisión, no del
programa.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .config import ErrorConfig
from .dedup import clave_de_registro
from .fuentes import NR
from .fuentes.unpaywall import (
    ESTADO_ABIERTO,
    ESTADO_CERRADO,
    ESTADO_DESCONOCIDO,
    Ubicacion,
    resolver,
)
from .http import ErrorHttp

__all__ = [
    "NOMBRE_TEXTO_COMPLETO",
    "ESTADO_SIN_DOI",
    "Resuelto",
    "ResultadoTextoCompleto",
    "leer_resueltos",
    "guardar_resueltos",
    "resolver_incluidos",
    "aplicar_a_registros",
]

NOMBRE_TEXTO_COMPLETO = "texto_completo.json"

#: Sin DOI no se puede preguntar a Unpaywall. No es un fallo ni un cierre: es
#: que falta el dato con el que se pregunta.
ESTADO_SIN_DOI = "sin_doi"


@dataclass(frozen=True)
class Resuelto:
    """Lo que se sabe del texto completo de un registro."""

    identificador: str
    doi: str = NR
    estado: str = ESTADO_DESCONOCIDO
    oa_url: str = NR
    version: str = NR
    licencia: str = NR
    repositorio: str = NR
    nota: str = NR
    fecha: str = NR

    @property
    def esta_abierto(self) -> bool:
        return self.estado == ESTADO_ABIERTO and self.oa_url != NR

    @classmethod
    def desde_ubicacion(
        cls, identificador: str, ubicacion: Ubicacion, fecha: str
    ) -> "Resuelto":
        return cls(
            identificador=identificador,
            doi=ubicacion.doi,
            estado=ubicacion.estado,
            oa_url=ubicacion.oa_url,
            version=ubicacion.version,
            licencia=ubicacion.licencia,
            repositorio=ubicacion.repositorio,
            nota=ubicacion.nota,
            fecha=fecha,
        )

    def como_json(self) -> dict[str, Any]:
        return {
            "doi": self.doi,
            "estado": self.estado,
            "oa_url": self.oa_url,
            "version": self.version,
            "licencia": self.licencia,
            "repositorio": self.repositorio,
            "nota": self.nota,
            "fecha": self.fecha,
        }

    def linea(self) -> str:
        """Una línea de avance para la CLI."""
        if self.esta_abierto:
            detalle = f"abierto ({self.version}, {self.licencia})"
        elif self.estado == ESTADO_CERRADO:
            detalle = "sin versión abierta: se pide a la biblioteca"
        elif self.estado == ESTADO_SIN_DOI:
            detalle = "sin DOI: no se puede preguntar"
        else:
            detalle = f"desconocido: {self.nota}"
        return f"{self.identificador}  {detalle}"


@dataclass
class ResultadoTextoCompleto:
    """Lo que pasó al resolver los textos completos."""

    consultados: int = 0
    reutilizados: int = 0
    abiertos: int = 0
    cerrados: int = 0
    sin_doi: int = 0
    desconocidos: int = 0
    resueltos: dict[str, Resuelto] = field(default_factory=dict)
    incidencias: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.resueltos)

    def resumen(self) -> str:
        """Texto para la CLI."""
        lineas = [
            f"Registros incluidos   : {self.total}",
            f"Consultados a Unpaywall: {self.consultados} "
            f"({self.reutilizados} ya estaban resueltos)",
            "",
            f"Con acceso abierto    : {self.abiertos}",
            f"Sin versión abierta   : {self.cerrados}",
        ]
        if self.sin_doi:
            lineas.append(f"Sin DOI               : {self.sin_doi}")
        if self.desconocidos:
            lineas.append(f"No resueltos          : {self.desconocidos}")
        if self.cerrados or self.sin_doi:
            lineas.append("")
            lineas.append(
                "Los que no tienen versión abierta van a por-conseguir.md. "
                "Tatewari no elude\nmuros de pago: esos textos se piden a la "
                "biblioteca institucional (AGENTS.md, regla 5)."
            )
        return "\n".join(lineas)


def leer_resueltos(ruta: Path | str) -> dict[str, Resuelto]:
    """Lee `texto_completo.json`. Si no existe, no hay nada resuelto todavía."""
    ruta = Path(ruta)
    if not ruta.is_file():
        return {}
    with open(ruta, encoding="utf-8") as manejador:
        try:
            datos = json.load(manejador)
        except json.JSONDecodeError:
            # Es una caché: se puede recalcular. Lo único que se pierde son unas
            # peticiones a Unpaywall, no información de la revisión.
            return {}
    if not isinstance(datos, dict):
        return {}
    crudos = datos.get("resueltos")
    if not isinstance(crudos, dict):
        return {}

    resueltos: dict[str, Resuelto] = {}
    for identificador, crudo in crudos.items():
        if not isinstance(crudo, dict):
            continue
        resueltos[str(identificador)] = Resuelto(
            identificador=str(identificador),
            doi=str(crudo.get("doi") or NR),
            estado=str(crudo.get("estado") or ESTADO_DESCONOCIDO),
            oa_url=str(crudo.get("oa_url") or NR),
            version=str(crudo.get("version") or NR),
            licencia=str(crudo.get("licencia") or NR),
            repositorio=str(crudo.get("repositorio") or NR),
            nota=str(crudo.get("nota") or NR),
            fecha=str(crudo.get("fecha") or NR),
        )
    return resueltos


def guardar_resueltos(
    ruta: Path | str, resueltos: Mapping[str, Resuelto]
) -> Path:
    """Escribe `texto_completo.json`, ordenado por identificador."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    salida = {
        "fuente": "Unpaywall",
        "actualizado": datetime.now().isoformat(timespec="seconds"),
        "resueltos": {
            identificador: resueltos[identificador].como_json()
            for identificador in sorted(resueltos)
        },
    }
    with open(ruta, "w", encoding="utf-8") as manejador:
        json.dump(salida, manejador, ensure_ascii=False, indent=2)
        manejador.write("\n")
    return ruta


def resolver_incluidos(
    decisiones: Sequence[Any],
    cliente: Any,
    correo: str,
    resueltos: Mapping[str, Resuelto] | None = None,
    rehacer: bool = False,
    avance: Callable[[int, int, Resuelto], None] | None = None,
) -> ResultadoTextoCompleto:
    """Resuelve el texto completo de cada decisión de la lista.

    `resueltos` es lo que ya se sabía de corridas anteriores; sin `rehacer`, esos
    no se vuelven a preguntar. Un fallo de red en un DOI no tumba la tanda: se
    anota como incidencia y se sigue con el siguiente.
    """
    previos = dict(resueltos or {})
    resultado = ResultadoTextoCompleto()
    ahora = datetime.now().isoformat(timespec="seconds")
    total = len(decisiones)

    for indice, decision in enumerate(decisiones, start=1):
        identificador = decision.identificador
        doi = str(decision.registro.get("doi") or NR).strip()

        anterior = previos.get(identificador)
        if anterior is not None and not rehacer:
            resultado.resueltos[identificador] = anterior
            resultado.reutilizados += 1
            _contar(resultado, anterior)
            if avance is not None:
                avance(indice, total, anterior)
            continue

        if not doi or doi == NR:
            resuelto = Resuelto(
                identificador=identificador,
                estado=ESTADO_SIN_DOI,
                nota=(
                    "El registro no trae DOI, así que no se puede preguntar a "
                    "Unpaywall. Se busca a mano por título."
                ),
                fecha=ahora,
            )
        else:
            try:
                ubicacion = resolver(doi, cliente, correo)
                resuelto = Resuelto.desde_ubicacion(identificador, ubicacion, ahora)
            except ErrorConfig:
                # Sin correo no hay consulta posible, y eso no se arregla
                # saltando al siguiente DOI: se corta aquí.
                raise
            except ErrorHttp as error:
                resuelto = Resuelto(
                    identificador=identificador,
                    doi=doi,
                    estado=ESTADO_DESCONOCIDO,
                    nota=f"No se pudo consultar Unpaywall: {error}",
                    fecha=ahora,
                )
                resultado.incidencias.append(f"{identificador}: {error}")
            resultado.consultados += 1

        resultado.resueltos[identificador] = resuelto
        _contar(resultado, resuelto)
        if avance is not None:
            avance(indice, total, resuelto)

    return resultado


def _contar(resultado: ResultadoTextoCompleto, resuelto: Resuelto) -> None:
    if resuelto.esta_abierto:
        resultado.abiertos += 1
    elif resuelto.estado == ESTADO_CERRADO:
        resultado.cerrados += 1
    elif resuelto.estado == ESTADO_SIN_DOI:
        resultado.sin_doi += 1
    else:
        resultado.desconocidos += 1


def aplicar_a_registros(
    registros: list[dict[str, Any]],
    resueltos: Mapping[str, Resuelto],
    asignaciones: Mapping[str, str],
) -> int:
    """Escribe el ``oa_url`` resuelto en los registros crudos de la cosecha.

    Los registros de `registros.json` vienen **con duplicados** y sin
    identificador: el enlace entre uno y otro es la clave de deduplicación, que
    es lo que `asignaciones` traduce a identificador. Todas las copias del mismo
    artículo reciben la misma URL.

    Solo se toca `oa_url`, y solo si Unpaywall encontró algo. Devuelve cuántos
    registros cambiaron, para que quien llama sepa si hace falta reescribir el
    archivo.
    """
    cambiados = 0
    for indice, registro in enumerate(registros):
        clave = clave_de_registro(registro, indice)
        identificador = asignaciones.get(clave)
        if identificador is None:
            continue
        resuelto = resueltos.get(identificador)
        if resuelto is None or not resuelto.esta_abierto:
            continue
        if registro.get("oa_url") == resuelto.oa_url:
            continue
        registro["oa_url"] = resuelto.oa_url
        cambiados += 1
    return cambiados
