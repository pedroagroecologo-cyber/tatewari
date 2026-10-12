"""La biblioteca acumulativa: SQLite como acervo que sobrevive a las revisiones.

Por qué existe
--------------

Una revisión vive en su carpeta y se basta a sí misma: `registros.json`,
`cribado.csv`, `decisiones.json`. Eso está bien para una revisión y mal para
veinte. En cuanto hay varias, aparecen preguntas que ninguna carpeta puede
contestar sola: ¿este artículo ya lo había leído en otra revisión? ¿qué tengo
sobre humedales publicado después de 2020, venga de donde venga? ¿qué he
decidido, en total, sobre este DOI?

Esta es esa capa. Una base SQLite en la que las revisiones se vuelcan y se
acumulan, con deduplicación entre ellas.

Qué es fuente de verdad, y qué no
----------------------------------

Aquí hay una tensión real con AGENTS.md y conviene tenerla escrita.

Las reglas 3 y 4 obligan a conservar la ecuación literal de cada búsqueda y la
auditoría registrada de cada exclusión. Eso vive en archivos que solo crecen
—`search_log.csv`, `decisiones.json`, `auditoria.json`— y ahí se queda. Esta
base **no los sustituye**: los refleja para poder preguntarles cosas.

La regla, en una línea:

    La base se reconstruye desde los archivos de evidencia;
    los archivos de evidencia no se reconstruyen desde la base.

Por eso existe `reconstruir()`. Si el archivo `.sqlite3` se corrompe, se borra y
se rehace recorriendo `revisiones/`, y no se ha perdido nada. Al revés no: si se
pierde `search_log.csv`, la revisión deja de ser reproducible y ninguna consulta
SQL lo arregla.

Lo único que esta base guarda y no está en ninguna otra parte son las
anotaciones y las etiquetas puestas a mano. Esas se respaldan aparte.

Los identificadores
-------------------

Una revisión numera `R0001`, `R0002`… y **otra revisión vuelve a empezar por
`R0001` hablando de otro artículo**. Si la biblioteca reusara esos números, dos
revisiones se pisarían en silencio, que es la peor forma de romperse.

Así que la biblioteca tiene su propia numeración, `B00001`, y la tabla
`equivalencia` guarda a qué identificador local corresponde en cada revisión.
El rastro PRISMA de cada revisión sigue siendo válido tal cual está escrito, y
aquí se sabe que el `R0007` de `demo` y el `R0031` de `humedales` son el mismo
artículo.

La deduplicación no se reimplementa
-----------------------------------

Se reusan `dedup.normalizar_doi()` y `texto.clave_alfanumerica()` tal cual. Si
la biblioteca dedujera duplicados con un criterio propio, tendríamos dos
respuestas distintas a la misma pregunta según a quién se le pregunte, y la del
cribado y la del acervo acabarían divergiendo.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .dedup import NOMBRE_IDENTIFICADORES, normalizar_doi
from .fuentes import CAMPOS_REGISTRO, NR
from .texto import clave_alfanumerica

__all__ = [
    "NOMBRE_BIBLIOTECA",
    "VERSION_ESQUEMA",
    "PLANTILLA_REFERENCIA",
    "ErrorBiblioteca",
    "ResumenImportacion",
    "Biblioteca",
    "abrir",
    "reconstruir",
]

#: Nombre del archivo dentro de la carpeta de datos.
NOMBRE_BIBLIOTECA = "biblioteca.sqlite3"

#: Versión del esquema. Sube cuando `esquema.sql` cambie de forma incompatible.
VERSION_ESQUEMA = 1

#: Cinco cifras: la biblioteca acumula varias revisiones, así que se queda corta
#: mucho después que la numeración por revisión de `dedup.py`.
PLANTILLA_REFERENCIA = "B{:05d}"

#: El archivo con el esquema, al lado de este módulo.
RUTA_ESQUEMA = Path(__file__).resolve().parent / "esquema.sql"

#: Campos que se copian del registro a la tabla. Son los de `fuentes`, más los
#: bibliográficos que hacen falta para citar y que hoy ninguna fuente rellena:
#: se quedan en "NR" hasta que alguna los dé.
CAMPOS_EXTRA = ("volumen", "numero", "paginas", "oa_estado")

#: Cómo se traduce la decisión del cribado al estado de la tabla. El cribado
#: escribe en infinitivo ("incluir") y aquí se guarda en participio, que es lo
#: que se lee bien en una consulta.
_ESTADOS = {
    "incluir": "incluido",
    "incluido": "incluido",
    "excluir": "excluido",
    "excluido": "excluido",
    "dudoso": "dudoso",
    "duda": "dudoso",
}


class ErrorBiblioteca(Exception):
    """Algo impidió leer o escribir en la biblioteca."""


@dataclass
class ResumenImportacion:
    """Lo que dejó una importación, para contarlo por la CLI."""

    revision: str = ""
    referencias_nuevas: int = 0
    referencias_vistas: int = 0
    autores: int = 0
    decisiones: int = 0
    ecuaciones: int = 0
    etiquetas: int = 0
    huecos: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def referencias(self) -> int:
        """Cuántas referencias tocó la importación, nuevas o ya conocidas."""
        return self.referencias_nuevas + self.referencias_vistas

    def resumen(self) -> str:
        """Texto para la CLI."""
        lineas = [
            f"Revisión              : {self.revision}",
            f"Referencias nuevas    : {self.referencias_nuevas}",
            f"Ya estaban            : {self.referencias_vistas}",
            f"Decisiones            : {self.decisiones}",
            f"Ecuaciones            : {self.ecuaciones}",
            f"Etiquetas             : {self.etiquetas}",
            f"Huecos (0 resultados) : {self.huecos}",
        ]
        for aviso in self.avisos:
            lineas.append(f"Aviso: {aviso}")
        return "\n".join(lineas)


def _ahora() -> str:
    """Marca de tiempo ISO 8601 sin microsegundos."""
    return datetime.now().replace(microsecond=0).isoformat()


def _es_nr(valor: Any) -> bool:
    """¿Este valor es un dato no reportado?

    Misma semántica que en `dedup._es_nr`, repetida aquí para no importar un
    privado de otro módulo: una lista vacía o de puros "NR" también es "NR".
    """
    if valor is None:
        return True
    if isinstance(valor, str):
        return not valor.strip() or valor.strip() == NR
    if isinstance(valor, (list, tuple)):
        return not valor or all(_es_nr(v) for v in valor)
    return False


def _texto(valor: Any) -> str:
    """El valor como texto, o "NR" si no hay dato."""
    if _es_nr(valor):
        return NR
    if isinstance(valor, (list, tuple)):
        return " | ".join(str(v).strip() for v in valor if not _es_nr(v))
    return str(valor).strip()


def _autores_de(valor: Any) -> list[str]:
    """Normaliza la lista de autores, venga como lista o como texto con barras.

    `registros.json` los trae como lista; `cribado.csv` los trae separados por
    ``|``, porque una coma dentro de un CSV es otra cosa.
    """
    if _es_nr(valor):
        return []
    crudos: Iterable[Any]
    if isinstance(valor, (list, tuple)):
        crudos = valor
    else:
        crudos = str(valor).split("|")
    limpios = []
    for crudo in crudos:
        nombre = str(crudo).strip()
        if nombre and nombre != NR:
            limpios.append(nombre)
    return limpios


def _siguiente_numero(conexion: sqlite3.Connection) -> int:
    """El número correlativo más alto ya usado, más uno.

    Se mira el máximo y no el total: si una referencia se borró, su
    identificador no se puede reutilizar, porque podría haber una decisión
    apuntando a él.
    """
    fila = conexion.execute(
        "SELECT MAX(CAST(SUBSTR(id, 2) AS INTEGER)) FROM referencia"
    ).fetchone()
    mayor = fila[0] if fila and fila[0] is not None else 0
    return int(mayor) + 1


class Biblioteca:
    """El acervo acumulado, sobre SQLite.

    Se usa como gestor de contexto, que es lo que garantiza que la conexión se
    cierre incluso si algo falla a mitad de una importación::

        with Biblioteca(ruta) as biblio:
            biblio.importar_revision(carpeta)

    Todas las escrituras de un método van en una sola transacción: una
    importación a medias dejaría la base diciendo que una revisión está cargada
    cuando solo entró parte, y eso es peor que no tenerla.
    """

    def __init__(self, ruta: Path | str) -> None:
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        try:
            # `isolation_level=None` pone a sqlite3 en autoconfirmación: cada
            # sentencia suelta se guarda sola. Sin esto, un `alta_referencia`
            # fuera de una importación abriría una transacción que nadie cierra
            # y se perdería entera al cerrar la conexión. Las operaciones que
            # deben ser atómicas abren su transacción explícita en
            # `_transaccion()`.
            self.conexion = sqlite3.connect(self.ruta, isolation_level=None)
        except sqlite3.Error as error:  # pragma: no cover - depende del sistema
            raise ErrorBiblioteca(
                f"No se pudo abrir la biblioteca en {self.ruta}: {error}"
            ) from error
        self.conexion.row_factory = sqlite3.Row
        # `foreign_keys` no persiste en el archivo: hay que pedirlo en cada
        # conexión, y sin él las claves foráneas del esquema son decorativas.
        self.conexion.execute("PRAGMA foreign_keys = ON")
        # WAL sí persiste. Permite que una interfaz lea mientras la CLI escribe.
        self.conexion.execute("PRAGMA journal_mode = WAL")
        self._crear_esquema()

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def __enter__(self) -> "Biblioteca":
        return self

    def __exit__(self, *_excepcion: object) -> None:
        self.cerrar()

    def cerrar(self) -> None:
        """Cierra la conexión."""
        self.conexion.close()

    @contextmanager
    def _transaccion(self) -> Iterator[None]:
        """Agrupa varias escrituras en una sola transacción.

        Una importación a medias dejaría la base diciendo que una revisión está
        cargada cuando solo entró parte de ella, y eso es peor que no tenerla.
        `BEGIN IMMEDIATE` toma el bloqueo de escritura desde el principio, para
        fallar pronto si otro proceso tiene la base abierta en vez de a mitad.
        """
        self.conexion.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conexion.execute("ROLLBACK")
            raise
        self.conexion.execute("COMMIT")

    def _crear_esquema(self) -> None:
        """Crea las tablas si faltan y comprueba la versión del esquema."""
        try:
            with open(RUTA_ESQUEMA, encoding="utf-8") as manejador:
                ddl = manejador.read()
        except OSError as error:
            raise ErrorBiblioteca(
                f"No se pudo leer el esquema en {RUTA_ESQUEMA}: {error}"
            ) from error

        self.conexion.executescript(ddl)
        fila = self.conexion.execute("SELECT version FROM esquema_version").fetchone()
        if fila is None:
            self.conexion.execute(
                "INSERT INTO esquema_version (version) VALUES (?)",
                (VERSION_ESQUEMA,),
            )
            return

        version = int(fila["version"])
        if version > VERSION_ESQUEMA:
            raise ErrorBiblioteca(
                f"La biblioteca {self.ruta} usa el esquema versión {version} y "
                f"esta copia de Tatewari entiende hasta la {VERSION_ESQUEMA}. "
                "Actualiza Tatewari, o abre otra biblioteca."
            )
        if version < VERSION_ESQUEMA:
            raise ErrorBiblioteca(
                f"La biblioteca {self.ruta} usa el esquema versión {version} y "
                f"hace falta la {VERSION_ESQUEMA}. Bórrala y vuelve a "
                "construirla con «biblioteca reconstruir»: se rehace entera "
                "desde las carpetas de revisiones."
            )

    # ------------------------------------------------------------------
    # Alta de referencias
    # ------------------------------------------------------------------

    def alta_referencia(self, registro: Mapping[str, Any]) -> tuple[str, bool]:
        """Da de alta un registro, o lo funde con el que ya estuviera.

        Devuelve `(identificador, es_nueva)`. La deduplicación es la misma que
        la del cribado: DOI normalizado si lo hay, clave alfanumérica del título
        si no. Un registro sin DOI **y** sin título no se puede afirmar que sea
        el mismo que ningún otro, así que entra solo.

        Al fundir, los campos que ya tenían dato no se tocan y los que estaban
        en "NR" se rellenan con el primer valor real que aparezca. Así una
        referencia no cambia de contenido según el orden en que se importen las
        revisiones.
        """
        doi = normalizar_doi(registro.get("doi"))
        titulo = registro.get("titulo")
        clave = clave_alfanumerica(titulo) if not _es_nr(titulo) else ""

        existente = self._buscar_existente(doi, clave)
        ahora = _ahora()

        if existente is None:
            identificador = PLANTILLA_REFERENCIA.format(
                _siguiente_numero(self.conexion)
            )
            columnas = {
                "id": identificador,
                "doi": doi or None,
                "clave_titulo": clave,
                "alta": ahora,
                "visto": ahora,
            }
            for campo in CAMPOS_REGISTRO:
                if campo in ("doi", "autores"):
                    continue
                columnas[campo] = _texto(registro.get(campo))
            for campo in CAMPOS_EXTRA:
                columnas[campo] = _texto(registro.get(campo))

            nombres = ", ".join(columnas)
            marcas = ", ".join("?" for _ in columnas)
            self.conexion.execute(
                f"INSERT INTO referencia ({nombres}) VALUES ({marcas})",
                tuple(columnas.values()),
            )
            self._guardar_autores(identificador, _autores_de(registro.get("autores")))
            return identificador, True

        identificador = existente["id"]
        self._fusionar(existente, registro, ahora)
        return identificador, False

    def _buscar_existente(self, doi: str, clave: str) -> sqlite3.Row | None:
        """La referencia que ya represente a este artículo, si la hay."""
        if doi:
            fila = self.conexion.execute(
                "SELECT * FROM referencia WHERE doi = ?", (doi,)
            ).fetchone()
            if fila is not None:
                return fila
            # Un registro pudo entrar antes sin DOI y llegar ahora con él. Se
            # busca por título para no crear un duplicado que nadie pidió.
        if clave:
            return self.conexion.execute(
                "SELECT * FROM referencia WHERE clave_titulo = ?", (clave,)
            ).fetchone()
        return None

    def _fusionar(
        self, existente: sqlite3.Row, registro: Mapping[str, Any], ahora: str
    ) -> None:
        """Rellena con `registro` lo que a `existente` le falte. Nada se pisa."""
        cambios: dict[str, Any] = {"visto": ahora}

        doi = normalizar_doi(registro.get("doi"))
        if doi and not existente["doi"]:
            cambios["doi"] = doi

        for campo in list(CAMPOS_REGISTRO) + list(CAMPOS_EXTRA):
            if campo in ("doi", "autores"):
                continue
            nuevo = _texto(registro.get(campo))
            if nuevo != NR and existente[campo] == NR:
                cambios[campo] = nuevo

        asignaciones = ", ".join(f"{campo} = ?" for campo in cambios)
        self.conexion.execute(
            f"UPDATE referencia SET {asignaciones} WHERE id = ?",
            (*cambios.values(), existente["id"]),
        )

        # Los autores solo se escriben si no había ninguno: una lista parcial
        # que sobrescribiera una completa perdería datos en silencio.
        autores = _autores_de(registro.get("autores"))
        if autores:
            fila = self.conexion.execute(
                "SELECT COUNT(*) AS total FROM autor WHERE referencia_id = ?",
                (existente["id"],),
            ).fetchone()
            if fila["total"] == 0:
                self._guardar_autores(existente["id"], autores)

    def _guardar_autores(self, referencia_id: str, autores: Sequence[str]) -> None:
        """Escribe la lista de autores conservando el orden."""
        self.conexion.executemany(
            "INSERT OR REPLACE INTO autor (referencia_id, orden, nombre) "
            "VALUES (?, ?, ?)",
            [(referencia_id, orden, nombre) for orden, nombre in enumerate(autores)],
        )

    # ------------------------------------------------------------------
    # Importación de una revisión
    # ------------------------------------------------------------------

    def importar_revision(
        self, carpeta: Path | str, nombre: str | None = None
    ) -> ResumenImportacion:
        """Vuelca una carpeta de revisión entera en la biblioteca.

        Lee, en este orden y saltándose lo que no exista:

        - `estado.json`   para el nombre de la revisión y la ruta del protocolo
        - `cribado.csv`   registros deduplicados con su decisión y clasificación
        - `registros.json` como respaldo, si aún no se ha cribado
        - `decisiones.json` decisiones manuales y del modelo, que mandan sobre
          las del filtro
        - `search_log.csv` las ecuaciones literales, y de ahí los huecos

        Volver a importar la misma revisión es seguro: las referencias se funden
        en vez de duplicarse y las decisiones se reemplazan por las del archivo,
        que es la evidencia.
        """
        carpeta = Path(carpeta)
        if not carpeta.is_dir():
            raise ErrorBiblioteca(f"No existe la carpeta de revisión: {carpeta}")

        estado = self._leer_json(carpeta / "estado.json") or {}
        revision = nombre or str(estado.get("revision") or carpeta.name)
        resumen = ResumenImportacion(revision=revision)

        with self._transaccion():
            self._registrar_revision(revision, carpeta, estado)

            locales = self._importar_registros(carpeta, revision, resumen)
            if not locales:
                resumen.avisos.append(
                    "No se encontró ni cribado.csv ni registros.json: no se "
                    "importó ninguna referencia."
                )
            self._importar_decisiones(carpeta, revision, locales, resumen)
            self._importar_ecuaciones(carpeta, revision, resumen)

        return resumen

    def _registrar_revision(
        self, revision: str, carpeta: Path, estado: Mapping[str, Any]
    ) -> None:
        """Alta o actualización de la revisión en el índice."""
        # El fixture es sintético y no debe acabar citado ni exportado. Se marca
        # aquí para que el exportador pueda negarse más adelante.
        sintetica = 1 if self._parece_sintetica(carpeta) else 0
        self.conexion.execute(
            "INSERT INTO revision (nombre, protocolo, protocolo_sha, carpeta, "
            "                      sintetica, importada) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(nombre) DO UPDATE SET "
            "  protocolo = excluded.protocolo, "
            "  carpeta   = excluded.carpeta, "
            "  sintetica = excluded.sintetica, "
            "  importada = excluded.importada",
            (
                revision,
                _texto(estado.get("protocolo")),
                NR,
                str(carpeta),
                sintetica,
                _ahora(),
            ),
        )

    @staticmethod
    def _parece_sintetica(carpeta: Path) -> bool:
        """¿Esta revisión salió del fixture de pruebas?

        El fixture lleva la marca en el título de cada registro, y el README es
        explícito: no debe citarse ni exportarse a un gestor bibliográfico.
        Detectarlo aquí es lo que permite que el exportador se niegue.
        """
        bitacora = carpeta / "search_log.csv"
        if not bitacora.is_file():
            return False
        try:
            with open(bitacora, encoding="utf-8-sig", newline="") as manejador:
                for fila in csv.DictReader(manejador):
                    if "fixture" in (fila.get("observaciones") or "").lower():
                        return True
        except OSError:
            return False
        return False

    def _importar_registros(
        self, carpeta: Path, revision: str, resumen: ResumenImportacion
    ) -> dict[str, str]:
        """Da de alta las referencias. Devuelve el mapa id_local -> id_biblioteca."""
        cribado = carpeta / "cribado.csv"
        if cribado.is_file():
            locales = self._desde_cribado(cribado, revision, resumen)
            # `cribado.csv` no lleva columna de resumen: se escribió para leerse
            # en Excel y el resumen no cabe ahí. Pero sin resumen la búsqueda
            # por texto solo ve títulos y el informe se queda mudo, así que se
            # completa desde la cosecha cruda. `_fusionar` solo rellena lo que
            # esté en "NR", de modo que esto no pisa nada de lo ya importado.
            self._enriquecer(carpeta, resumen)
            return locales
        registros = carpeta / "registros.json"
        if registros.is_file():
            return self._desde_registros(carpeta, revision, resumen)
        return {}

    def _enriquecer(self, carpeta: Path, resumen: ResumenImportacion) -> None:
        """Rellena desde `registros.json` los campos que el CSV no traía."""
        crudos = self._leer_json(carpeta / "registros.json")
        if not isinstance(crudos, list):
            return
        for crudo in crudos:
            if not isinstance(crudo, Mapping):
                continue
            _, nueva = self.alta_referencia(crudo)
            if nueva:
                # Un registro de la cosecha que no aparece en el cribado es raro
                # —significa que el CSV está desfasado respecto a la cosecha—
                # pero entra igual: perderlo en silencio sería peor.
                resumen.referencias_nuevas += 1
                resumen.avisos.append(
                    "Hay registros en registros.json que no están en "
                    "cribado.csv; puede que el cribado esté desfasado."
                )

    def _desde_cribado(
        self, ruta: Path, revision: str, resumen: ResumenImportacion
    ) -> dict[str, str]:
        """Lee `cribado.csv`: ya viene deduplicado y con decisión y clasificación."""
        locales: dict[str, str] = {}
        with open(ruta, encoding="utf-8", newline="") as manejador:
            for fila in csv.DictReader(manejador):
                id_local = (fila.get("identificador") or "").strip()
                if not id_local:
                    continue
                identificador, nueva = self.alta_referencia(fila)
                locales[id_local] = identificador
                if nueva:
                    resumen.referencias_nuevas += 1
                else:
                    resumen.referencias_vistas += 1
                self._equivaler(revision, id_local, identificador)
                self._decidir_desde_filtro(revision, identificador, fila, resumen)
                self._etiquetar_clasificacion(revision, identificador, fila, resumen)
        return locales

    def _desde_registros(
        self, carpeta: Path, revision: str, resumen: ResumenImportacion
    ) -> dict[str, str]:
        """Respaldo cuando aún no se ha cribado: cosecha cruda más identificadores.

        Se deduplica con `dedup.deduplicar()`, el mismo código que usa el
        cribado, para que los identificadores locales coincidan con los que
        tendrá la revisión cuando se cribe.
        """
        from .dedup import deduplicar, leer_asignaciones

        crudos = self._leer_json(carpeta / "registros.json") or []
        if not isinstance(crudos, list):
            resumen.avisos.append("registros.json no contiene una lista; se ignoró.")
            return {}

        asignaciones = leer_asignaciones(carpeta / NOMBRE_IDENTIFICADORES)
        resultado = deduplicar(crudos, asignaciones)

        locales: dict[str, str] = {}
        for registro in resultado.unicos:
            id_local = str(registro.get("identificador") or "").strip()
            identificador, nueva = self.alta_referencia(registro)
            if nueva:
                resumen.referencias_nuevas += 1
            else:
                resumen.referencias_vistas += 1
            if id_local:
                locales[id_local] = identificador
                self._equivaler(revision, id_local, identificador)
        return locales

    def _equivaler(self, revision: str, id_local: str, referencia_id: str) -> None:
        """Ata el identificador local de la revisión al de la biblioteca."""
        self.conexion.execute(
            "INSERT OR REPLACE INTO equivalencia (revision, id_local, referencia_id) "
            "VALUES (?, ?, ?)",
            (revision, id_local, referencia_id),
        )

    def _decidir_desde_filtro(
        self,
        revision: str,
        referencia_id: str,
        fila: Mapping[str, Any],
        resumen: ResumenImportacion,
    ) -> None:
        """Guarda la decisión que trae `cribado.csv`."""
        estado = _ESTADOS.get(str(fila.get("decision") or "").strip().lower())
        if estado is None:
            return
        decidido = str(fila.get("decidido_por") or "filtro").strip().lower()
        origen = "regla"
        if decidido.startswith("modelo"):
            origen = "modelo"
        elif decidido not in ("filtro", "regla", ""):
            origen = "humano"
        self.conexion.execute(
            "INSERT OR REPLACE INTO decision "
            "(revision, referencia_id, estado, motivo, origen, regla, fecha) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                revision,
                referencia_id,
                estado,
                _texto(fila.get("motivo")),
                origen,
                _texto(fila.get("regla")),
                _ahora(),
            ),
        )
        resumen.decisiones += 1

    def _etiquetar_clasificacion(
        self,
        revision: str,
        referencia_id: str,
        fila: Mapping[str, Any],
        resumen: ResumenImportacion,
    ) -> None:
        """Convierte la columna `clasificacion` en una etiqueta del eje homónimo.

        Es la única dimensión que existe hoy, y es determinista: la asignó una
        coincidencia de términos del protocolo, no un modelo. Los ejes ad hoc
        (región, clima, escala) llegan en un encargo posterior y entrarán por
        esta misma tabla.
        """
        valor = _texto(fila.get("clasificacion"))
        if valor == NR:
            return
        self.conexion.execute(
            "INSERT OR IGNORE INTO dimension (revision, nombre, tipo, descripcion) "
            "VALUES (?, ?, ?, ?)",
            (
                revision,
                "clasificacion",
                "determinista",
                "Categoría del protocolo, por coincidencia de términos.",
            ),
        )
        self.conexion.execute(
            "INSERT OR REPLACE INTO etiqueta "
            "(revision, referencia_id, dimension, valor, origen, verificado, fecha) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (revision, referencia_id, "clasificacion", valor, "termino", 0, _ahora()),
        )
        resumen.etiquetas += 1

    def _importar_decisiones(
        self,
        carpeta: Path,
        revision: str,
        locales: Mapping[str, str],
        resumen: ResumenImportacion,
    ) -> None:
        """Aplica `decisiones.json`, que manda sobre lo que dijera el filtro.

        Una decisión humana o del modelo sobre un dudoso es posterior al filtro
        y lo sobrescribe: eso es exactamente la regla 4, el filtro propone y no
        decide.
        """
        datos = self._leer_json(carpeta / "decisiones.json")
        if not isinstance(datos, dict):
            return
        for id_local, cruda in datos.items():
            if not isinstance(cruda, Mapping):
                continue
            referencia_id = locales.get(str(id_local))
            if referencia_id is None:
                resumen.avisos.append(
                    f"decisiones.json menciona {id_local}, que no aparece entre "
                    "los registros importados; esa decisión se saltó."
                )
                continue
            estado = _ESTADOS.get(str(cruda.get("decision") or "").strip().lower())
            if estado is None:
                continue
            autor = str(cruda.get("autor") or "").strip().lower()
            origen = "modelo" if autor.startswith("modelo") else "humano"
            self.conexion.execute(
                "INSERT OR REPLACE INTO decision "
                "(revision, referencia_id, estado, motivo, origen, regla, fecha) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    revision,
                    referencia_id,
                    estado,
                    _texto(cruda.get("motivo")),
                    origen,
                    NR,
                    _texto(cruda.get("fecha")),
                ),
            )

    def _importar_ecuaciones(
        self, carpeta: Path, revision: str, resumen: ResumenImportacion
    ) -> None:
        """Refleja `search_log.csv` y anota como hueco lo que salió en cero.

        El CSV se lee en `utf-8-sig`: se escribe con BOM para que Excel no
        destroce los acentos, y sin `-sig` el BOM acabaría pegado al nombre de
        la primera columna (AGENTS.md, regla 8).
        """
        ruta = carpeta / "search_log.csv"
        if not ruta.is_file():
            return
        with open(ruta, encoding="utf-8-sig", newline="") as manejador:
            for fila in csv.DictReader(manejador):
                literal = _texto(fila.get("ecuacion"))
                if literal == NR:
                    continue
                try:
                    resultados = int(str(fila.get("resultados") or 0).strip() or 0)
                except ValueError:
                    resultados = 0
                try:
                    numero = int(str(fila.get("N") or 0).strip() or 0)
                except ValueError:
                    numero = 0
                fuente = _texto(fila.get("base"))
                self.conexion.execute(
                    "INSERT OR REPLACE INTO ecuacion "
                    "(revision, numero, fuente, literal, url, eje, valor_eje, "
                    " resultados, fecha) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        revision,
                        numero,
                        fuente,
                        literal,
                        _texto(fila.get("url")),
                        NR,
                        NR,
                        resultados,
                        _texto(fila.get("fecha")),
                    ),
                )
                resumen.ecuaciones += 1

                if resultados == 0:
                    # Mientras no haya ejes de barrido, el hueco se indexa por la
                    # ecuación misma. Cuando los haya, se indexará por (eje, valor)
                    # y esto quedará como el caso general.
                    self.conexion.execute(
                        "INSERT OR REPLACE INTO hueco "
                        "(revision, dimension, valor, ecuaciones, resultados, fecha) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (revision, "ecuacion", literal, 1, 0, _texto(fila.get("fecha"))),
                    )
                    resumen.huecos += 1

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------

    def buscar(
        self,
        texto: str | None = None,
        revision: str | None = None,
        estado: str | None = None,
        dimension: str | None = None,
        valor: str | None = None,
        anio_desde: int | None = None,
        limite: int = 50,
    ) -> list[dict[str, Any]]:
        """Busca referencias. Todos los filtros son opcionales y se acumulan.

        `texto` busca en título y resumen con LIKE. No es FTS: para un acervo de
        unos miles de registros LIKE sobra, y FTS5 no está compilado en todas
        las builds de Python de Windows, así que depender de él sería cambiar
        una comodidad por un fallo en la máquina de alguien.
        """
        condiciones: list[str] = []
        parametros: list[Any] = []
        tablas = "referencia AS r"

        if revision is not None or estado is not None:
            tablas += " JOIN decision AS d ON d.referencia_id = r.id"
            if revision is not None:
                condiciones.append("d.revision = ?")
                parametros.append(revision)
            if estado is not None:
                condiciones.append("d.estado = ?")
                parametros.append(estado)

        if dimension is not None:
            tablas += " JOIN etiqueta AS e ON e.referencia_id = r.id"
            condiciones.append("e.dimension = ?")
            parametros.append(dimension)
            if valor is not None:
                condiciones.append("e.valor = ?")
                parametros.append(valor)

        if texto:
            condiciones.append("(r.titulo LIKE ? OR r.resumen LIKE ?)")
            patron = f"%{texto}%"
            parametros.extend([patron, patron])

        if anio_desde is not None:
            # El año es TEXT porque puede valer "NR"; el CAST deja fuera esos.
            condiciones.append("CAST(r.anio AS INTEGER) >= ?")
            parametros.append(anio_desde)

        donde = f" WHERE {' AND '.join(condiciones)}" if condiciones else ""
        consulta = (
            f"SELECT DISTINCT r.* FROM {tablas}{donde} "
            "ORDER BY CAST(r.anio AS INTEGER) DESC, r.id LIMIT ?"
        )
        parametros.append(limite)

        filas = self.conexion.execute(consulta, tuple(parametros)).fetchall()
        return [self._con_autores(fila) for fila in filas]

    def _con_autores(self, fila: sqlite3.Row) -> dict[str, Any]:
        """Una fila de `referencia` como diccionario, con sus autores."""
        registro = dict(fila)
        autores = self.conexion.execute(
            "SELECT nombre FROM autor WHERE referencia_id = ? ORDER BY orden",
            (fila["id"],),
        ).fetchall()
        registro["autores"] = [autor["nombre"] for autor in autores] or [NR]
        registro["doi"] = registro.get("doi") or NR
        return registro

    def revisiones(self) -> list[dict[str, Any]]:
        """Las revisiones importadas, con cuántas referencias tiene cada una."""
        filas = self.conexion.execute(
            "SELECT v.nombre, v.carpeta, v.sintetica, v.importada, "
            "       COUNT(e.id_local) AS referencias "
            "FROM revision AS v "
            "LEFT JOIN equivalencia AS e ON e.revision = v.nombre "
            "GROUP BY v.nombre ORDER BY v.nombre"
        ).fetchall()
        return [dict(fila) for fila in filas]

    def huecos(self, revision: str | None = None) -> list[dict[str, Any]]:
        """Las búsquedas que se lanzaron y no devolvieron nada.

        Es un hallazgo, no una omisión: que una región o un término no tenga
        literatura es información, y el informe la publica como tal.
        """
        if revision is None:
            filas = self.conexion.execute(
                "SELECT * FROM hueco ORDER BY revision, dimension, valor"
            ).fetchall()
        else:
            filas = self.conexion.execute(
                "SELECT * FROM hueco WHERE revision = ? ORDER BY dimension, valor",
                (revision,),
            ).fetchall()
        return [dict(fila) for fila in filas]

    def contar(self) -> dict[str, int]:
        """Cuántas filas hay en cada tabla que importa."""
        cuentas: dict[str, int] = {}
        for tabla in ("referencia", "revision", "decision", "ecuacion", "etiqueta", "hueco"):
            fila = self.conexion.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()
            cuentas[tabla] = int(fila["n"])
        return cuentas

    def resumen(self) -> str:
        """Texto para la CLI."""
        cuentas = self.contar()
        por_estado = self.conexion.execute(
            "SELECT estado, COUNT(*) AS n FROM decision GROUP BY estado"
        ).fetchall()
        lineas = [
            f"Biblioteca  : {self.ruta}",
            f"Referencias : {cuentas['referencia']}",
            f"Revisiones  : {cuentas['revision']}",
            f"Ecuaciones  : {cuentas['ecuacion']}",
            f"Etiquetas   : {cuentas['etiqueta']}",
            f"Huecos      : {cuentas['hueco']}",
        ]
        for fila in por_estado:
            lineas.append(f"  {fila['estado']:<10}: {fila['n']}")
        return "\n".join(lineas)

    # ------------------------------------------------------------------
    # Utilidades internas
    # ------------------------------------------------------------------

    @staticmethod
    def _leer_json(ruta: Path) -> Any:
        """Lee un JSON, o devuelve `None` si no existe o está roto.

        Un archivo ilegible no puede tumbar una importación entera: la revisión
        puede tener todo lo demás en orden, y quien llama anota el aviso.
        """
        if not ruta.is_file():
            return None
        try:
            with open(ruta, encoding="utf-8") as manejador:
                return json.load(manejador)
        except (OSError, json.JSONDecodeError):
            return None


def abrir(datos: Path | str) -> Biblioteca:
    """Abre —creándola si hace falta— la biblioteca de una carpeta de datos."""
    return Biblioteca(Path(datos) / NOMBRE_BIBLIOTECA)


def reconstruir(
    datos: Path | str, revisiones: Path | str | None = None
) -> list[ResumenImportacion]:
    """Borra la biblioteca y la rehace desde las carpetas de revisiones.

    Esta función es la que hace que la base sea desechable, y por tanto la que
    permite tratarla como fuente de verdad sin riesgo: lo que se pierde al
    borrarla vuelve a entrar desde los archivos de evidencia, que son los que
    manda conservar AGENTS.md.

    Lo único que **no** vuelve son las anotaciones y etiquetas puestas a mano,
    porque no están en ninguna otra parte. Mientras no exista el respaldo de
    esas, conviene reconstruir solo cuando haga falta de verdad.
    """
    datos = Path(datos)
    raiz = Path(revisiones) if revisiones is not None else datos
    archivo = datos / NOMBRE_BIBLIOTECA

    for sufijo in ("", "-wal", "-shm"):
        candidato = archivo.with_name(archivo.name + sufijo)
        if candidato.exists():
            candidato.unlink()

    resumenes: list[ResumenImportacion] = []
    with Biblioteca(archivo) as biblioteca:
        for carpeta in sorted(_carpetas_de_revision(raiz)):
            resumenes.append(biblioteca.importar_revision(carpeta))
    return resumenes


def _carpetas_de_revision(raiz: Path) -> Iterator[Path]:
    """Las subcarpetas que parecen una revisión.

    El criterio es tener alguno de los archivos que produce una revisión. Así
    una carpeta suelta dentro de `revisiones/` no se importa como si lo fuera.
    """
    if not raiz.is_dir():
        return
    for carpeta in raiz.iterdir():
        if not carpeta.is_dir():
            continue
        for nombre in ("cribado.csv", "registros.json", "estado.json"):
            if (carpeta / nombre).is_file():
                yield carpeta
                break
