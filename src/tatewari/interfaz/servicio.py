"""Lo que la interfaz sabe hacer, sin HTTP de por medio.

Las colecciones de la izquierda salen de dos sitios:

- Las **revisiones** de la carpeta de datos: cada una con sus incluidos,
  dudosos y excluidos, tal como los deja el cribado.
- El **Vault** de Obsidian: las notas por estado, las fuentes, los conflictos,
  las propuestas y los borradores de ZEA MAYZ.

Los cambios pasan por el mismo código que la línea de órdenes: una decisión se
guarda en `decisiones.json` y se vuelve a cribar, como `tatewari decidir`; un
cambio de estado es `Vault.cambiar_estado`, con sus mismas reglas (APPROVED y
PUBLISHED solo con el nombre de una persona).
"""

from __future__ import annotations

import csv
import getpass
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from .. import __version__
from ..config import Config
from ..conocimiento.enrutador import TAREAS, Enrutador
from ..conocimiento.ingesta import TAMANO_MAXIMO, TIPOS_ADMITIDOS
from ..conocimiento.markdown import leer_nota
from ..conocimiento.objetos import ESTADOS, TRANSICIONES
from ..conocimiento.orquestador import Orquestador
from ..conocimiento.rutas import CARPETAS_PROHIBIDAS, Jaula
from ..conocimiento.vault import ErrorVault, Nota, Vault
from ..cribado import (
    DECISIONES,
    NOMBRE_CRIBADO,
    NOMBRE_REGISTROS,
    Cribado,
    Decision,
    DecisionManual,
    ErrorCribado,
    anadir_decisiones,
    protocolo_registrado,
)
from ..modelo import ErrorOllama
from ..protocolo import ErrorProtocolo, cargar_protocolo
from ..texto import normalizar

__all__ = ["Servicio", "ErrorInterfaz", "guardar_en_env"]

#: Las colecciones fijas del Vault, en el orden en que se muestran.
_COLECCIONES_VAULT = (
    ("vault:todas", "Todas las notas"),
    *((f"vault:estado:{e}", e) for e in ESTADOS),
    ("vault:conflictos", "Con conflictos"),
    ("vault:fuentes", "Fuentes"),
    ("vault:propuestas", "Propuestas"),
    ("vault:borradores", "Borradores ZEA MAYZ"),
)

_NOMBRES_DECISION = {"incluir": "Incluidos", "dudoso": "Dudosos", "excluir": "Excluidos"}
_TIPOS_NO_CONCEPTO = ("fuente", "propuesta", "indice", "guion", "storyboard", "ilustraciones")
_TIPOS_BORRADOR = ("guion", "storyboard", "ilustraciones")
_BLOQUE_DATOS = re.compile(r"\n?%%.*?%%\s*", re.S)


class ErrorInterfaz(Exception):
    """Algo que la persona pidió no se puede hacer. El mensaje dice por qué."""


def guardar_en_env(ruta_env: Path, clave: str, valor: str) -> Path:
    """Pone `clave=valor` en el `.env`, sustituyendo la línea si ya estaba.

    Si el `.env` no existe se crea a partir de `.env.example` (si está al lado),
    para no perder los comentarios de las demás variables.
    """
    if not ruta_env.exists():
        ejemplo = ruta_env.with_name(".env.example")
        if ejemplo.is_file():
            shutil.copyfile(ejemplo, ruta_env)
    lineas = ruta_env.read_text(encoding="utf-8").splitlines() if ruta_env.exists() else []
    nueva = f"{clave}={valor}"
    for indice, linea in enumerate(lineas):
        if re.match(rf"^\s*{re.escape(clave)}\s*=", linea):
            lineas[indice] = nueva
            break
    else:
        lineas.append(nueva)
    with open(ruta_env, "w", encoding="utf-8", newline="\n") as manejador:
        manejador.write("\n".join(lineas) + "\n")
    return ruta_env


@dataclass
class Servicio:
    """El estado de una sesión de la interfaz: configuración, Vault y modelos."""

    config: Config
    vault_ruta: Path | None = None
    enrutador: Enrutador | None = None
    usuario: str = field(default_factory=lambda: getpass.getuser() or "NR")
    _vault: Vault | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.vault_ruta is None:
            self.vault_ruta = self.config.vault
        if self.enrutador is None:
            self.enrutador = Enrutador.desde_config(self.config)

    # -- Vault ---------------------------------------------------------------

    def vault(self) -> Vault | None:
        """El Vault configurado, o `None` si no hay o no existe todavía."""
        if self.vault_ruta is None:
            return None
        if self._vault is None:
            try:
                self._vault = Vault.cargar(self.vault_ruta)
            except ErrorVault:
                return None
        return self._vault

    def jaula(self) -> Jaula:
        vault = self.vault()
        raices = [self.config.datos] + ([vault.raiz] if vault else [])
        return Jaula.para(*raices)

    def orquestador(self, avance: Callable[[str], None] | None = None) -> Orquestador:
        vault = self.vault()
        if vault is None:
            raise ErrorInterfaz(
                "No hay ningún Vault de Obsidian configurado. Elige su carpeta en "
                "«Configurar Vault»."
            )
        return Orquestador(vault=vault, jaula=self.jaula(), enrutador=self.enrutador, avance=avance)

    def elegir_vault(self, ruta: str, recordar: bool = False) -> dict[str, Any]:
        """Usa otra carpeta como Vault, creando su estructura si hace falta."""
        ruta_limpia = Path(ruta.strip().strip('"')).expanduser()
        if not ruta.strip() or not ruta_limpia.is_absolute():
            raise ErrorInterfaz("Escribe la ruta completa de la carpeta, por ejemplo C:/Users/tu/Documents/Vault.")
        try:
            vault = Vault.cargar(ruta_limpia, crear=True)
        except ErrorVault as error:
            raise ErrorInterfaz(str(error)) from error
        self.vault_ruta = vault.raiz
        self._vault = vault
        creadas = self.orquestador().crear_base()
        guardado = None
        if recordar:
            destino = self.config.origen_env or (Path.cwd() / ".env")
            guardado = str(guardar_en_env(destino, "TATEWARI_OBSIDIAN_VAULT", str(vault.raiz)))
        return {"vault": str(vault.raiz), "creadas": len(creadas), "env": guardado}

    # -- Estado general ------------------------------------------------------

    def estado(self) -> dict[str, Any]:
        vault = self.vault()
        return {
            "version": __version__,
            "usuario": self.usuario,
            "datos": str(self.config.datos),
            "vault": str(vault.raiz) if vault else None,
            "vault_configurado": str(self.vault_ruta) if self.vault_ruta else None,
            "estados": list(ESTADOS),
            "transiciones": {k: list(v) for k, v in TRANSICIONES.items()},
            "decisiones": list(DECISIONES),
            "tipos_admitidos": sorted(TIPOS_ADMITIDOS),
        }

    def modelos(self) -> dict[str, Any]:
        """Qué modelo hace cada tarea y cuáles están ya cargados en la tarjeta."""
        try:
            tareas = {tarea: self.enrutador.modelo(tarea) for tarea in TAREAS}
        except ErrorOllama as error:
            return {"ok": False, "error": str(error), "tareas": {}, "en_memoria": []}
        cliente = self.enrutador.cliente("extraccion")
        return {
            "ok": True,
            "error": "",
            "direccion": cliente.direccion,
            "tareas": tareas,
            "en_memoria": list(cliente.en_memoria()),
        }

    def precargar(self) -> str:
        """Carga el modelo de extracción en la tarjeta para que el primer documento no espere."""
        return self.enrutador.cliente("extraccion").precargar()

    # -- Colecciones -----------------------------------------------------------

    def revisiones(self) -> list[str]:
        datos = self.config.datos
        if not datos.is_dir():
            return []
        return sorted(
            p.name
            for p in datos.iterdir()
            if p.is_dir() and ((p / NOMBRE_REGISTROS).is_file() or (p / NOMBRE_CRIBADO).is_file())
        )

    def colecciones(self) -> list[dict[str, Any]]:
        grupos: list[dict[str, Any]] = []
        revisiones = []
        for nombre in self.revisiones():
            try:
                filas = self._filas_revision(nombre)
            except ErrorInterfaz:
                filas = []
            cuentas = {d: sum(1 for f in filas if f["decision"] == d) for d in DECISIONES}
            revisiones.append(
                {
                    "id": f"rev:{nombre}",
                    "nombre": nombre,
                    "cuenta": len(filas),
                    "hijos": [
                        {"id": f"rev:{nombre}:{d}", "nombre": _NOMBRES_DECISION[d], "cuenta": cuentas[d], "marca": d}
                        for d in DECISIONES
                    ],
                }
            )
        grupos.append({"id": "revisiones", "nombre": "Revisiones sistemáticas", "hijos": revisiones})

        vault = self.vault()
        if vault is None:
            grupos.append({"id": "vault", "nombre": "Vault de Obsidian", "sin_configurar": True, "hijos": []})
        else:
            hijos = []
            for identificador, nombre in _COLECCIONES_VAULT:
                hijos.append(
                    {
                        "id": identificador,
                        "nombre": nombre,
                        "cuenta": len(self._notas_de(identificador)),
                        "marca": identificador.rsplit(":", 1)[-1],
                    }
                )
            grupos.append({"id": "vault", "nombre": vault.raiz.name, "ruta": str(vault.raiz), "hijos": hijos})
        return grupos

    # -- Elementos ---------------------------------------------------------------

    def elementos(self, coleccion: str, consulta: str = "") -> list[dict[str, Any]]:
        if coleccion.startswith("rev:"):
            partes = coleccion.split(":")
            filas = self._filas_revision(partes[1])
            if len(partes) > 2:
                filas = [f for f in filas if f["decision"] == partes[2]]
            filas = [self._resumen_fila(f) for f in filas]
        elif coleccion.startswith("vault:"):
            filas = [self._resumen_nota(n) for n in self._notas_de(coleccion)]
        else:
            raise ErrorInterfaz(f"No conozco la colección «{coleccion}».")
        palabras = [p for p in _plano(consulta).split() if p]
        if palabras:
            filas = [f for f in filas if all(p in f["_busqueda"] for p in palabras)]
        for fila in filas:
            fila.pop("_busqueda", None)
        return filas

    def elemento(self, coleccion: str, identificador: str) -> dict[str, Any]:
        if coleccion.startswith("rev:"):
            revision = coleccion.split(":")[1]
            for fila in self._filas_revision(revision):
                if fila["id"] == identificador:
                    return {"clase": "registro", "revision": revision, **fila}
            raise ErrorInterfaz(f"No hay ningún registro {identificador} en «{revision}».")
        if coleccion.startswith("vault:"):
            return self._detalle_nota(self._nota_por_id(identificador))
        raise ErrorInterfaz(f"No conozco la colección «{coleccion}».")

    def buscar_nota(self, nombre: str) -> dict[str, Any]:
        """Para seguir un [[enlace]] desde la ficha de una nota."""
        vault = self._exigir_vault()
        nota = vault.buscar(nombre.split("|", 1)[0].split("#", 1)[0])
        if nota is None:
            raise ErrorInterfaz(f"«{nombre}» todavía no tiene nota en el Vault.")
        return self._detalle_nota(nota)

    # -- Cambios ----------------------------------------------------------------

    def decidir(self, revision: str, identificador: str, decision: str, motivo: str, autor: str) -> dict[str, Any]:
        """Lo mismo que `tatewari decidir`: guarda la decisión y vuelve a cribar."""
        if decision not in DECISIONES:
            raise ErrorInterfaz(f"La decisión tiene que ser una de: {', '.join(DECISIONES)}.")
        motivo = motivo.strip()
        if not motivo:
            raise ErrorInterfaz("El motivo no puede estar vacío: una decisión sin motivo no es auditable.")
        autor = autor.strip() or self.usuario
        cribado = self._cribado(revision)
        if cribado is None:
            raise ErrorInterfaz(
                f"No sé con qué protocolo se cosechó «{revision}», así que no puedo volver a "
                f"cribarla. Usa «tatewari decidir {revision} … --protocolo RUTA»."
            )
        try:
            cribado.calcular().buscar(identificador)
        except KeyError as error:
            raise ErrorInterfaz(f"No hay ningún registro {identificador} en «{revision}».") from error
        except ErrorCribado as error:
            raise ErrorInterfaz(str(error)) from error
        anadir_decisiones(
            cribado.ruta_decisiones,
            {
                identificador: DecisionManual(
                    identificador=identificador,
                    decision=decision,
                    motivo=motivo,
                    autor=autor,
                    fecha=date.today().isoformat(),
                )
            },
        )
        try:
            cribado.ejecutar()
        except ErrorCribado as error:
            raise ErrorInterfaz(str(error)) from error
        return self.elemento(f"rev:{revision}", identificador)

    def cambiar_estado(self, identificador: str, nuevo: str, autor: str) -> dict[str, Any]:
        vault = self._exigir_vault()
        nota = self._nota_por_id(identificador)
        try:
            cambiada = vault.cambiar_estado(self.jaula(), nota.nombre, nuevo, autor.strip())
        except Exception as error:  # ErrorEstado, ErrorVault, ErrorRuta: el mensaje ya es claro
            raise ErrorInterfaz(str(error)) from error
        return self._detalle_nota(cambiada)

    def guardar_subida(self, nombre: str, contenido: bytes) -> Path:
        """Guarda un documento subido desde el navegador en una carpeta temporal propia.

        El orquestador lo copia después a la materia del Vault con su nombre;
        esta copia se borra al terminar el trabajo.
        """
        limpio = Path(nombre.replace("\\", "/")).name.strip()
        extension = Path(limpio).suffix.lower()
        if extension not in TIPOS_ADMITIDOS:
            admitidos = ", ".join(sorted(TIPOS_ADMITIDOS))
            raise ErrorInterfaz(f"«{limpio}» no se admite. Formatos: {admitidos}.")
        if not contenido:
            raise ErrorInterfaz(f"«{limpio}» está vacío.")
        if len(contenido) > TAMANO_MAXIMO:
            raise ErrorInterfaz(f"«{limpio}» pasa de {TAMANO_MAXIMO // (1024 * 1024)} MB.")
        limpio = re.sub(r'[<>:"|?*\x00-\x1f]', "_", limpio) or f"documento{extension}"
        carpeta = self.config.datos / "_interfaz" / "subidas" / uuid.uuid4().hex
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / limpio
        destino.write_bytes(contenido)
        return destino

    def ruta_de_archivo(self, relativa: str) -> Path:
        """Un archivo del Vault que el navegador puede abrir (el PDF original, p. ej.).

        Solo dentro del Vault, nunca en `.obsidian`, `.git` ni la papelera.
        """
        vault = self._exigir_vault()
        raiz = vault.raiz.resolve()
        ruta = (raiz / relativa).resolve()
        try:
            partes = ruta.relative_to(raiz).parts
        except ValueError as error:
            raise ErrorInterfaz("Ese archivo está fuera del Vault.") from error
        if any(p.lower() in CARPETAS_PROHIBIDAS for p in partes) or not ruta.is_file():
            raise ErrorInterfaz("Ese archivo no existe en el Vault.")
        return ruta

    # -- Revisiones: lectura --------------------------------------------------

    def _cribado(self, revision: str) -> Cribado | None:
        carpeta = self._carpeta_revision(revision)
        ruta = protocolo_registrado(carpeta)
        if ruta is None:
            return None
        try:
            protocolo = cargar_protocolo(ruta)
        except (FileNotFoundError, ErrorProtocolo):
            return None
        return Cribado(revision=revision, protocolo=protocolo, config=self.config)

    def _carpeta_revision(self, revision: str) -> Path:
        if revision not in self.revisiones():
            raise ErrorInterfaz(f"No hay ninguna revisión «{revision}» en {self.config.datos}.")
        return self.config.datos / revision

    def _filas_revision(self, revision: str) -> list[dict[str, Any]]:
        """Los registros de una revisión con su decisión.

        Si se conoce el protocolo, se criba en memoria (sin escribir nada): así se
        tienen también los resúmenes. Si no, se lee `cribado.csv`.
        """
        cribado = self._cribado(revision)
        if cribado is not None:
            try:
                return [_fila_de_decision(d) for d in cribado.calcular().decisiones]
            except ErrorCribado:
                pass
        ruta = self._carpeta_revision(revision) / NOMBRE_CRIBADO
        if not ruta.is_file():
            return []
        with open(ruta, encoding="utf-8", newline="") as manejador:
            return [_fila_de_csv(f) for f in csv.DictReader(manejador)]

    @staticmethod
    def _resumen_fila(fila: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": fila["id"],
            "titulo": fila["titulo"],
            "autores": fila["autores_corto"],
            "anio": fila["anio"],
            "revista": fila["revista"],
            "marca": fila["decision"],
            "etiqueta": fila["decision"],
            "quien": fila["decidido_por"],
            "_busqueda": _plano(" ".join(str(fila.get(k, "")) for k in ("id", "titulo", "autores", "resumen", "revista", "doi"))),
        }

    # -- Vault: lectura -------------------------------------------------------

    def _exigir_vault(self) -> Vault:
        vault = self.vault()
        if vault is None:
            raise ErrorInterfaz("No hay ningún Vault de Obsidian configurado.")
        return vault

    def _notas_de(self, coleccion: str) -> list[Nota]:
        vault = self.vault()
        if vault is None:
            return []
        if coleccion == "vault:propuestas":
            return _notas_de_carpeta(vault.carpeta("propuestas"))
        notas = vault.notas(recargar=True)
        if coleccion == "vault:todas":
            return [n for n in notas if n.tipo != "indice"]
        if coleccion.startswith("vault:estado:"):
            estado = coleccion.rsplit(":", 1)[1]
            return [n for n in notas if n.gestionada and n.estado == estado and n.tipo not in _TIPOS_NO_CONCEPTO]
        if coleccion == "vault:conflictos":
            return [n for n in notas if n.conflictos]
        if coleccion == "vault:fuentes":
            return [n for n in notas if n.tipo == "fuente"]
        if coleccion == "vault:borradores":
            return [n for n in notas if n.tipo in _TIPOS_BORRADOR]
        raise ErrorInterfaz(f"No conozco la colección «{coleccion}».")

    def _id_de(self, nota: Nota) -> str:
        return nota.ruta.relative_to(self._exigir_vault().raiz).as_posix()

    def _nota_por_id(self, identificador: str) -> Nota:
        vault = self._exigir_vault()
        ruta = (vault.raiz / identificador).resolve()
        try:
            ruta.relative_to(vault.raiz.resolve())
        except ValueError as error:
            raise ErrorInterfaz("Esa nota está fuera del Vault.") from error
        for nota in vault.notas(recargar=True) + _notas_de_carpeta(vault.carpeta("propuestas")):
            if nota.ruta.resolve() == ruta:
                return nota
        raise ErrorInterfaz(f"No encuentro la nota «{identificador}». ¿La has movido o borrado?")

    def _tipo_de(self, nota: Nota) -> str:
        """El tipo para mostrar. Un .md en la materia sin tipo es un documento original."""
        if nota.tipo != "NR":
            return nota.tipo
        try:
            nota.ruta.relative_to(self._exigir_vault().carpeta("materia"))
            return "documento original"
        except ValueError:
            return ""

    def _resumen_nota(self, nota: Nota) -> dict[str, Any]:
        fuentes = nota.frontmatter.get("fuentes") or []
        return {
            "id": self._id_de(nota),
            "titulo": nota.nombre,
            "autores": ", ".join(str(f) for f in fuentes[:2]) if isinstance(fuentes, list) else str(fuentes),
            "anio": str(nota.frontmatter.get("actualizado") or nota.frontmatter.get("creado") or "")[:10],
            "revista": self._tipo_de(nota),
            "marca": nota.estado if nota.estado != "NR" else "",
            "etiqueta": nota.estado if nota.estado != "NR" else "",
            "quien": "conflicto" if nota.conflictos else "",
            "_busqueda": _plano(f"{nota.nombre} {' '.join(nota.alias)} {nota.cuerpo[:4000]}"),
        }

    def _detalle_nota(self, nota: Nota) -> dict[str, Any]:
        vault = self._exigir_vault()
        cuerpo = _BLOQUE_DATOS.sub("\n", nota.cuerpo).strip()
        original = None
        if nota.tipo == "fuente" and nota.frontmatter.get("archivo"):
            candidato = nota.ruta.parent / str(nota.frontmatter["archivo"])
            if candidato.is_file():
                original = candidato.relative_to(vault.raiz).as_posix()
        estado = nota.estado if nota.estado in ESTADOS else ""
        return {
            "clase": "nota",
            "id": self._id_de(nota),
            "nombre": nota.nombre,
            "tipo": self._tipo_de(nota),
            "estado": estado,
            "transiciones": list(TRANSICIONES.get(estado, ())) if nota.gestionada else [],
            "gestionada": nota.gestionada,
            "intacta": nota.intacta,
            "alias": nota.alias,
            "fuentes": list(nota.frontmatter.get("fuentes") or []),
            "confianza": nota.frontmatter.get("confianza"),
            "generado_por": nota.frontmatter.get("generado_por"),
            "aprobado_por": nota.frontmatter.get("approved_por") or nota.frontmatter.get("published_por"),
            "conflictos": nota.conflictos,
            "cuerpo": cuerpo,
            "ruta": str(nota.ruta),
            "obsidian": "obsidian://open?path=" + quote(str(nota.ruta), safe=""),
            "original": original,
        }


# ---------------------------------------------------------------------------
# Ayudas
# ---------------------------------------------------------------------------


def _plano(texto: str) -> str:
    return normalizar(texto or "")


def _autores(valor: Any) -> list[str]:
    if isinstance(valor, list):
        return [str(a) for a in valor if str(a).strip()]
    texto = str(valor or "").strip()
    if not texto or texto == "NR":
        return []
    return [a.strip() for a in re.split(r"[|;]", texto) if a.strip()]


def _corto(autores: list[str]) -> str:
    if not autores:
        return ""
    primero = autores[0].split(",")[0]
    return primero if len(autores) == 1 else f"{primero} et al."


def _texto(valor: Any) -> str:
    return "" if valor is None or str(valor) == "NR" else str(valor)


def _fila_de_decision(decision: Decision) -> dict[str, Any]:
    registro = decision.registro or {}
    autores = _autores(registro.get("autores"))
    return {
        "id": decision.identificador,
        "titulo": _texto(registro.get("titulo")) or "(sin título)",
        "autores": autores,
        "autores_corto": _corto(autores),
        "anio": _texto(registro.get("anio")),
        "revista": _texto(registro.get("revista")),
        "idioma": _texto(registro.get("idioma")),
        "tipo": _texto(registro.get("tipo")),
        "doi": _texto(registro.get("doi")),
        "oa_url": _texto(registro.get("oa_url")),
        "resumen": _texto(registro.get("resumen")),
        "decision": decision.decision,
        "motivo": decision.motivo,
        "categoria": decision.categoria,
        "decidido_por": decision.decidido_por,
        "decision_filtro": decision.decision_filtro or decision.decision,
        "motivo_filtro": decision.motivo_filtro or decision.motivo,
    }


def _fila_de_csv(fila: dict[str, str]) -> dict[str, Any]:
    autores = _autores(fila.get("autores"))
    return {
        "id": fila.get("identificador", ""),
        "titulo": _texto(fila.get("titulo")) or "(sin título)",
        "autores": autores,
        "autores_corto": _corto(autores),
        "anio": _texto(fila.get("anio")),
        "revista": _texto(fila.get("revista")),
        "idioma": _texto(fila.get("idioma")),
        "tipo": _texto(fila.get("tipo")),
        "doi": _texto(fila.get("doi")),
        "oa_url": _texto(fila.get("oa_url")),
        "resumen": "",
        "decision": fila.get("decision", ""),
        "motivo": fila.get("motivo", ""),
        "categoria": fila.get("categoria", ""),
        "decidido_por": fila.get("decidido_por", ""),
        "decision_filtro": fila.get("decision_filtro", ""),
        "motivo_filtro": fila.get("motivo_filtro", ""),
    }


def _notas_de_carpeta(carpeta: Path) -> list[Nota]:
    if not carpeta.is_dir():
        return []
    notas = []
    for ruta in sorted(carpeta.glob("*.md")):
        try:
            frontmatter, cuerpo, datos = leer_nota(ruta.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        notas.append(Nota(ruta=ruta, frontmatter=frontmatter, cuerpo=cuerpo, datos=datos))
    return notas
