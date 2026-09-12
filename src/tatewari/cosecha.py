"""Cosecha reanudable, con bitácora.

Una cosecha completa son decenas de ecuaciones y miles de peticiones. Si se
corta a la mitad —y se corta— hay que poder retomarla sin repetir lo ya hecho
ni perder el rastro de lo que se hizo. De ahí las tres piezas de este módulo:

`estado.json`
    Qué ecuaciones ya se ejecutaron. Cada llamada procesa un lote (8 ecuaciones
    por defecto) y dice cuántas faltan. Volver a llamar continúa donde se quedó.

`search_log.csv`
    Una fila por ecuación, con la **URL literal** que se pidió. Sin ella la
    búsqueda no es reproducible y la revisión deja de ser sistemática
    (AGENTS.md, regla 3).

`registros.json`
    Los registros cosechados, **con sus duplicados**. Deduplicar es otro
    encargo; aquí no se toca nada.

Modos sin red
-------------

- ``--seco``: no pide nada, solo devuelve las ecuaciones con su URL literal
  para pegarlas en el navegador y comprobarlas antes de gastar red.
- ``--fixture RUTA``: sirve un archivo local como respuesta. El archivo se
  sirve como respuesta de la **primera** ecuación del lote; si el lote lleva
  más, esas quedan registradas con 0 resultados y la observación de que el
  fixture ya se había servido. Por eso, en modo fixture el lote es de una sola
  ecuación salvo que se pida otra cosa.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Config
from .fuentes import CAMPOS_REGISTRO, NR, crossref, openalex, registro_en_blanco
from .http import ErrorHttp
from .protocolo import Protocolo

__all__ = [
    "Cosecha",
    "Ecuacion",
    "ResumenLote",
    "FUENTES",
    "COLUMNAS_BITACORA",
    "LOTE_POR_DEFECTO",
    "INTENTOS_MAXIMOS",
    "CODIFICACION_BITACORA",
    "ErrorCosecha",
]

LOTE_POR_DEFECTO = 8
PAGINAS_POR_DEFECTO = 5

#: Intentos antes de dar una ecuación por perdida. Una ecuación rota no puede
#: atascar la cosecha en bucle.
INTENTOS_MAXIMOS = 3

NOMBRE_ESTADO = "estado.json"
NOMBRE_BITACORA = "search_log.csv"
NOMBRE_REGISTROS = "registros.json"

#: La bitácora se escribe en UTF-8 **con BOM**. Es la única excepción al
#: encoding="utf-8" de la regla 8 de AGENTS.md, y está documentada allí: Excel
#: en Windows abre un CSV sin BOM con la página de códigos local y destroza los
#: acentos de la columna de observaciones. El BOM es lo que le dice a Excel que
#: el archivo es UTF-8. El resto de archivos del proyecto siguen en UTF-8 puro.
CODIFICACION_BITACORA = "utf-8-sig"

COLUMNAS_BITACORA = (
    "N",
    "fecha",
    "base",
    "ecuacion",
    "url",
    "idiomas",
    "ventana",
    "resultados",
    "observaciones",
)

#: Fuentes disponibles. Solo las que permite AGENTS.md, regla 5.
FUENTES = {
    "openalex": openalex,
    "crossref": crossref,
}


class ErrorCosecha(Exception):
    """La cosecha no puede ni empezar (protocolo sin consulta, fuente rara…)."""


@dataclass(frozen=True)
class Ecuacion:
    """Una ecuación del plan, con su URL literal ya resuelta."""

    numero: int
    texto: str
    url: str
    base: str


@dataclass
class ResumenLote:
    """Lo que pasó en una llamada a la cosecha."""

    revision: str
    carpeta: Path
    base: str
    total: int
    procesadas: int = 0
    registros_nuevos: int = 0
    sin_resumen: int = 0
    con_error: int = 0
    perdidas: int = 0
    pendientes: int = 0
    seco: bool = False
    detenido_por_cuota: bool = False
    cuota: str = ""
    ecuaciones: list[Ecuacion] = field(default_factory=list)
    incidencias: list[str] = field(default_factory=list)

    def resumen(self) -> str:
        """Texto para la CLI."""
        if self.seco:
            lineas = [
                "Modo seco: no se ha tocado la red.",
                f"Revisión : {self.revision}",
                f"Base     : {self.base}",
                f"Ecuaciones previstas : {self.total}",
            ]
            return "\n".join(lineas)

        lineas = [
            f"Revisión  : {self.revision}",
            f"Base      : {self.base}",
            f"Carpeta   : {self.carpeta}",
            "",
            f"Ecuaciones procesadas en este lote : {self.procesadas}",
            f"Registros cosechados en este lote  : {self.registros_nuevos}",
        ]
        if self.registros_nuevos:
            porcentaje = 100 * self.sin_resumen / self.registros_nuevos
            lineas.append(
                f"  de ellos, sin resumen            : {self.sin_resumen} "
                f"({porcentaje:.0f} %)"
            )
        if self.con_error:
            lineas.append(f"Ecuaciones con error               : {self.con_error}")
        if self.perdidas:
            lineas.append(
                f"Ecuaciones dadas por perdidas      : {self.perdidas} "
                f"(agotaron los {INTENTOS_MAXIMOS} intentos)"
            )
        lineas.append(
            f"Pendientes                         : {self.pendientes} de {self.total}"
        )
        if self.cuota:
            lineas.append("")
            lineas.append(self.cuota)

        lineas.append("")
        if self.detenido_por_cuota:
            lineas.append(
                "Lote interrumpido: queda poca cuota en la fuente. Lo hecho está "
                "guardado; vuelve a lanzar la orden cuando la cuota se reponga."
            )
        elif self.pendientes:
            lineas.append(
                "Vuelve a lanzar la misma orden para continuar donde se quedó."
            )
        else:
            lineas.append("Cosecha completa.")

        if self.con_error:
            lineas.append(
                "Las ecuaciones con error quedan anotadas en la bitácora. Para "
                "reintentarlas, lanza la orden con --reintentar."
            )
        return "\n".join(lineas)


class Cosecha:
    """Orquesta la cosecha de una revisión y guarda su rastro en disco."""

    def __init__(
        self,
        revision: str,
        protocolo: Protocolo,
        config: Config,
        fuente: str = "openalex",
        cliente: Any | None = None,
    ) -> None:
        if fuente not in FUENTES:
            raise ErrorCosecha(
                f"Fuente desconocida: {fuente!r}. Las disponibles son: "
                f"{', '.join(sorted(FUENTES))}."
            )
        self.revision = revision
        self.protocolo = protocolo
        self.config = config
        self.nombre_fuente = fuente
        self.fuente = FUENTES[fuente]
        self._cliente = cliente

    # -- Rutas -------------------------------------------------------------

    @property
    def carpeta(self) -> Path:
        return self.config.datos / self.revision

    @property
    def ruta_estado(self) -> Path:
        return self.carpeta / NOMBRE_ESTADO

    @property
    def ruta_bitacora(self) -> Path:
        return self.carpeta / NOMBRE_BITACORA

    @property
    def ruta_registros(self) -> Path:
        return self.carpeta / NOMBRE_REGISTROS

    # -- Plan --------------------------------------------------------------

    def ecuaciones(self) -> list[Ecuacion]:
        """Despliega el protocolo en ecuaciones numeradas con su URL literal."""
        # El texto de la ecuación sale del protocolo y es el mismo para todas
        # las bases; lo que cambia de una a otra es cómo se arma la URL.
        textos = openalex.construir_ecuaciones(self.protocolo)

        if not textos:
            raise ErrorCosecha(
                'El protocolo no tiene "consulta", así que no hay ecuaciones que '
                "lanzar. Añade un bloque eje y una lista de cruce."
            )

        correo = self.config.mailto
        return [
            Ecuacion(
                numero=indice,
                texto=texto,
                url=self.fuente.construir_url(texto, self.protocolo, correo),
                base=self.fuente.NOMBRE,
            )
            for indice, texto in enumerate(textos, start=1)
        ]

    # -- Estado ------------------------------------------------------------

    def cargar_estado(self) -> dict[str, Any]:
        """Lee `estado.json`, o devuelve un estado nuevo si no existe."""
        if not self.ruta_estado.is_file():
            return {
                "revision": self.revision,
                "protocolo": str(self.protocolo.ruta) if self.protocolo.ruta else NR,
                "fuente": self.nombre_fuente,
                "creado": _ahora(),
                "actualizado": _ahora(),
                "total_ecuaciones": 0,
                "hechas": {},
            }
        with open(self.ruta_estado, encoding="utf-8") as manejador:
            estado = json.load(manejador)
        estado.setdefault("hechas", {})
        return estado

    def guardar_estado(self, estado: dict[str, Any]) -> None:
        estado["actualizado"] = _ahora()
        self.carpeta.mkdir(parents=True, exist_ok=True)
        with open(self.ruta_estado, "w", encoding="utf-8") as manejador:
            json.dump(estado, manejador, ensure_ascii=False, indent=2)
            manejador.write("\n")

    # -- Ejecución ---------------------------------------------------------

    def plan_seco(self, max_consultas: int | None = None) -> ResumenLote:
        """Devuelve las ecuaciones con su URL literal. No toca la red."""
        todas = self.ecuaciones()
        mostradas = todas if max_consultas is None else todas[: max(0, max_consultas)]
        return ResumenLote(
            revision=self.revision,
            carpeta=self.carpeta,
            base=self.fuente.NOMBRE,
            total=len(todas),
            seco=True,
            ecuaciones=mostradas,
        )

    def ejecutar(
        self,
        max_consultas: int | None = None,
        max_paginas: int = PAGINAS_POR_DEFECTO,
        fixture: Path | None = None,
        reintentar: bool = False,
    ) -> ResumenLote:
        """Procesa un lote de ecuaciones pendientes y guarda el rastro.

        Con `reintentar`, las ecuaciones que fallaron vuelven a la cola, salvo
        las que ya agotaron `INTENTOS_MAXIMOS`: una ecuación rota no puede
        atascar la cosecha en bucle.
        """
        todas = self.ecuaciones()
        estado = self.cargar_estado()
        estado["total_ecuaciones"] = len(todas)
        estado["fuente"] = self.nombre_fuente

        hechas = estado["hechas"]
        pendientes = [
            e for e in todas if _toca_procesar(hechas.get(str(e.numero)), reintentar)
        ]

        tope = LOTE_POR_DEFECTO if max_consultas is None else max(0, max_consultas)
        lote = pendientes[:tope]

        resumen = ResumenLote(
            revision=self.revision,
            carpeta=self.carpeta,
            base=self.fuente.NOMBRE,
            total=len(todas),
            ecuaciones=lote,
        )

        registros_fixture: list[dict[str, Any]] | None = None
        fixture_servido = False
        if fixture is not None:
            registros_fixture = cargar_fixture(fixture)

        self.carpeta.mkdir(parents=True, exist_ok=True)
        nuevos: list[dict[str, Any]] = []

        for ecuacion in lote:
            fecha = _ahora()
            observaciones = ""
            registros: list[dict[str, Any]] = []
            resultados: int | str = 0
            url = ecuacion.url

            if registros_fixture is not None:
                if fixture_servido:
                    observaciones = (
                        f"Sin red: el fixture {fixture.name} ya se sirvió en una "
                        f"ecuación anterior de este lote."
                    )
                else:
                    registros = [dict(r) for r in registros_fixture]
                    fixture_servido = True
                    observaciones = (
                        f"Sin red: respuesta tomada del fixture local {fixture.name}. "
                        f"La URL queda anotada como la que se habría pedido."
                    )
                resultados = len(registros)
            else:
                try:
                    resultado = self.fuente.buscar(
                        ecuacion.texto,
                        self.protocolo,
                        self._exigir_cliente(),
                        self.config.mailto,
                        max_paginas=max_paginas,
                    )
                    registros = resultado.registros
                    resultados = len(registros)
                    url = resultado.url_literal if resultado.urls else ecuacion.url
                    if resultado.paginas >= max_paginas and resultado.total_declarado != NR:
                        observaciones = (
                            f"Tope de {max_paginas} páginas alcanzado; la base "
                            f"declara {resultado.total_declarado} resultados."
                        )
                except ErrorHttp as error:
                    # Un error en una ecuación no tumba la cosecha entera.
                    resultados = NR
                    observaciones = f"Error: {error}"
                    resumen.con_error += 1
                    resumen.incidencias.append(f"Ecuación {ecuacion.numero}: {error}")

            nuevos.extend(registros)
            resumen.procesadas += 1
            resumen.sin_resumen += sum(1 for r in registros if r.get("resumen") == NR)

            previo = hechas.get(str(ecuacion.numero)) or {}
            intentos = int(previo.get("intentos", 0)) + 1
            if resultados == NR and intentos >= INTENTOS_MAXIMOS:
                resumen.perdidas += 1
                observaciones += (
                    f" Agotados los {INTENTOS_MAXIMOS} intentos: se da por perdida."
                )

            hechas[str(ecuacion.numero)] = {
                "ecuacion": ecuacion.texto,
                "url": url,
                "base": ecuacion.base,
                "fecha": fecha,
                "intentos": intentos,
                "resultados": resultados,
                "observaciones": observaciones or NR,
            }

            if self._quedarse_sin_cuota(max_paginas):
                resumen.detenido_por_cuota = True
                break

            self.anotar_en_bitacora(
                numero=ecuacion.numero,
                fecha=fecha,
                base=ecuacion.base,
                ecuacion=ecuacion.texto,
                url=url,
                resultados=resultados,
                observaciones=observaciones,
            )

        if nuevos:
            self.anexar_registros(nuevos)
        resumen.registros_nuevos = len(nuevos)

        self.guardar_estado(estado)
        resumen.pendientes = sum(
            1 for e in todas if _toca_procesar(hechas.get(str(e.numero)), reintentar)
        )
        if self._cliente is not None and getattr(self._cliente, "cuota", None):
            resumen.cuota = self._cliente.cuota.resumen()
        return resumen

    def _quedarse_sin_cuota(self, max_paginas: int) -> bool:
        """¿Queda cuota para otra ecuación entera?

        Se para **antes** de agotarla, no después: una ecuación a medias deja
        la bitácora diciendo que se buscó algo que en realidad no se buscó
        entero.
        """
        cuota = getattr(self._cliente, "cuota", None)
        if cuota is None or not cuota.hay_datos:
            return False
        peticiones = cuota.peticiones_restantes
        if peticiones is None:
            return False
        return peticiones < max_paginas

    def _exigir_cliente(self) -> Any:
        if self._cliente is None:
            raise ErrorCosecha(
                "No hay cliente HTTP configurado para salir a la red. Usa --seco "
                "o --fixture si no quieres consultar la API."
            )
        return self._cliente

    # -- Salidas -----------------------------------------------------------

    def anotar_en_bitacora(
        self,
        numero: int,
        fecha: str,
        base: str,
        ecuacion: str,
        url: str,
        resultados: int | str,
        observaciones: str = "",
    ) -> None:
        """Añade una fila a `search_log.csv`, creando la cabecera si hace falta."""
        self.carpeta.mkdir(parents=True, exist_ok=True)
        nuevo = not self.ruta_bitacora.is_file()

        inicio, fin = self.protocolo.ventana
        fila = {
            "N": numero,
            "fecha": fecha,
            "base": base,
            "ecuacion": ecuacion,
            "url": url,
            "idiomas": "|".join(self.protocolo.idiomas),
            "ventana": f"{inicio}-{fin}",
            "resultados": resultados,
            "observaciones": observaciones or NR,
        }

        # newline="" es obligatorio en Windows: sin él, el módulo csv escribe
        # \r\r\n y el archivo sale con una línea en blanco entre filas.
        with open(
            self.ruta_bitacora, "a", encoding=CODIFICACION_BITACORA, newline=""
        ) as manejador:
            escritor = csv.DictWriter(manejador, fieldnames=list(COLUMNAS_BITACORA))
            if nuevo:
                escritor.writeheader()
            escritor.writerow(fila)

    def anexar_registros(self, registros: list[dict[str, Any]]) -> None:
        """Añade registros a `registros.json`, **sin deduplicar**.

        Deduplicar es otro encargo. Aquí se guarda lo que vino, duplicados
        incluidos, que es justo lo que el paso siguiente necesita ver.
        """
        acumulado = self.leer_registros()
        acumulado.extend(registros)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        with open(self.ruta_registros, "w", encoding="utf-8") as manejador:
            json.dump(acumulado, manejador, ensure_ascii=False, indent=2)
            manejador.write("\n")

    def leer_registros(self) -> list[dict[str, Any]]:
        if not self.ruta_registros.is_file():
            return []
        with open(self.ruta_registros, encoding="utf-8") as manejador:
            datos = json.load(manejador)
        return datos if isinstance(datos, list) else []

    def leer_bitacora(self) -> list[dict[str, str]]:
        """Lee `search_log.csv`. Sobre todo para las pruebas y para informes."""
        if not self.ruta_bitacora.is_file():
            return []
        with open(
            self.ruta_bitacora, encoding=CODIFICACION_BITACORA, newline=""
        ) as manejador:
            return list(csv.DictReader(manejador))


def cargar_fixture(ruta: Path) -> list[dict[str, Any]]:
    """Carga registros de un archivo local en vez de la API.

    Admite dos formas:

    - una **lista** de registros ya normalizados, como `fixtures/demo.json`;
    - un **objeto** con ``results``, es decir una página cruda de OpenAlex, que
      se normaliza aquí mismo.
    """
    ruta = Path(ruta)
    if not ruta.is_file():
        raise ErrorCosecha(f"No existe el fixture: {ruta}")

    with open(ruta, encoding="utf-8") as manejador:
        datos = json.load(manejador)

    if isinstance(datos, dict) and "results" in datos:
        return [openalex.normalizar_obra(obra) for obra in datos.get("results") or []]

    if not isinstance(datos, list):
        raise ErrorCosecha(
            f"El fixture {ruta} debe ser una lista de registros o un objeto con "
            f'"results".'
        )

    return [_completar_registro(registro) for registro in datos]


def _completar_registro(registro: Any) -> dict[str, Any]:
    """Rellena con "NR" los campos que falten, sin inventar ninguno."""
    completo = registro_en_blanco()
    if isinstance(registro, dict):
        for campo in CAMPOS_REGISTRO:
            if campo in registro and registro[campo] not in (None, ""):
                completo[campo] = registro[campo]
    return completo


def _fallo(entrada: Any) -> bool:
    """¿Esta entrada de `estado.json` es una ecuación que falló?"""
    return isinstance(entrada, dict) and entrada.get("resultados") == NR


def _toca_procesar(entrada: Any, reintentar: bool) -> bool:
    """¿Hay que lanzar esta ecuación en este lote?

    Nunca procesada, o falló y se pidió reintentar y aún le quedan intentos.
    """
    if entrada is None:
        return True
    if not reintentar or not _fallo(entrada):
        return False
    return int(entrada.get("intentos", 1)) < INTENTOS_MAXIMOS


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")
