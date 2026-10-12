"""El Vault de Obsidian: estructura, lectura, búsqueda y escritura de notas.

Tatewari opera **directamente sobre los archivos** del Vault. No controla la
aplicación ni depende de ningún complemento: todo es Markdown estándar con
enlaces ``[[...]]``, frontmatter YAML y comentarios ``%%``, que es lo que
Obsidian entiende de serie.

La estructura
-------------

Por defecto, la del proyecto ZEA MAYZ: ``00_INBOX`` … ``09_LIBRO``. Pero no se
impone. Si el Vault trae ``.tatewari/vault.json``, sus carpetas mandan:

    {
      "carpetas": {"conceptos": "Conocimiento", "materia": "Documentos"},
      "destino_por_tipo": {"persona": "conceptos"}
    }

Lo que no se diga ahí toma el valor por defecto.

Las tres formas de escribir
---------------------------

- **Crear** una nota nueva, cuando no existe nada con ese nombre ni alias.
- **Actualizar** fundiendo lo nuevo con lo que había, solo si la nota la escribió
  Tatewari, sigue en ``DRAFT`` o ``REVIEW`` y nadie la ha tocado a mano.
- **Proponer**: en cualquier otro caso. La nota no se toca y la propuesta queda
  en la bandeja de entrada para que una persona decida. El conocimiento aprobado
  **nunca** se sobrescribe en silencio.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..texto import normalizar
from .documento import NR
from .markdown import (
    AVISO_BORRADOR,
    aviso_aprobado,
    enlaces_de,
    escribir_frontmatter,
    huella_cuerpo,
    leer_nota,
    leer_plantilla,
    plantilla_para_obsidian,
    render_objeto,
)
from .objetos import (
    ESTADOS,
    ESTADOS_PROTEGIDOS,
    ObjetoConocimiento,
    ahora,
    clave_de_nombre,
    comprobar_transicion,
)
from .rutas import CARPETAS_PROHIBIDAS, ErrorRuta, Jaula, nombre_de_nota, primera_ruta_libre

__all__ = [
    "ESTRUCTURA_POR_DEFECTO",
    "DESTINO_POR_TIPO",
    "ErrorVault",
    "Nota",
    "Vault",
    "NOMBRE_INDICE",
]

ESTRUCTURA_POR_DEFECTO = {
    "inbox": "00_INBOX",
    "materia": "01_MATERIA",
    "conceptos": "02_CONCEPTOS",
    "personajes": "03_PERSONAJES",
    "territorio": "04_TERRITORIO",
    "guion": "05_GUION",
    "storyboard": "06_STORYBOARD",
    "referencias": "07_REFERENCIAS",
    "ilustraciones": "08_ILUSTRACIONES",
    "libro": "09_LIBRO",
    "plantillas": "_plantillas",
    "reportes": "00_INBOX/reportes",
    "propuestas": "00_INBOX/propuestas",
}

#: Tipo de objeto -> carpeta. Lo que no esté aquí va a «conceptos».
DESTINO_POR_TIPO = {
    "persona": "personajes",
    "lugar": "territorio",
    "referencia": "referencias",
}

NOMBRE_INDICE = "Índice de conocimiento"
_CONFIG = Path(".tatewari") / "vault.json"

#: Carpetas del Vault que no se leen como notas de conocimiento.
_NO_NOTAS = {"plantillas", "reportes", "propuestas"}


class ErrorVault(Exception):
    """El Vault no existe, no está configurado o no se puede usar."""


@dataclass
class Nota:
    """Una nota del Vault ya leída."""

    ruta: Path
    frontmatter: dict[str, Any]
    cuerpo: str
    datos: dict[str, Any] | None

    @property
    def nombre(self) -> str:
        return self.ruta.stem

    @property
    def gestionada(self) -> bool:
        """¿La escribió Tatewari? Tiene su identificador y su bloque de datos."""
        return bool(self.frontmatter.get("tatewari_id")) and self.datos is not None

    @property
    def estado(self) -> str:
        return str(self.frontmatter.get("estado") or NR)

    @property
    def tipo(self) -> str:
        return str(self.frontmatter.get("tipo") or NR)

    @property
    def alias(self) -> list[str]:
        crudo = self.frontmatter.get("aliases") or self.frontmatter.get("alias") or []
        return [str(a) for a in crudo] if isinstance(crudo, list) else [str(crudo)]

    @property
    def intacta(self) -> bool:
        """¿El cuerpo sigue siendo el que escribió Tatewari? Si no, es de una persona."""
        guardada = str(self.frontmatter.get("tatewari_hash") or "")
        return bool(guardada) and guardada == huella_cuerpo(self.cuerpo)

    @property
    def claves(self) -> set[str]:
        """Todas las formas de nombrarla: archivo, título, alias."""
        nombres = {self.nombre, *self.alias}
        if self.datos and self.datos.get("titulo"):
            nombres.add(str(self.datos["titulo"]))
        encabezado = re.search(r"^#\s+(.+)$", self.cuerpo, re.M)
        if encabezado:
            nombres.add(encabezado.group(1).strip())
        return {clave_de_nombre(n) for n in nombres if n.strip()} - {""}

    def objeto(self) -> ObjetoConocimiento | None:
        return ObjetoConocimiento.desde_dict(self.datos) if self.datos else None

    @property
    def conflictos(self) -> list[dict[str, Any]]:
        return list((self.datos or {}).get("conflictos") or [])

    @property
    def texto_plano(self) -> str:
        """El cuerpo sin marcas, para comparar contenidos."""
        return normalizar(re.sub(r"[#>*\[\]|%`_-]", " ", self.cuerpo))


@dataclass
class Vault:
    raiz: Path
    carpetas: dict[str, str] = field(default_factory=lambda: dict(ESTRUCTURA_POR_DEFECTO))
    destino_por_tipo: dict[str, str] = field(default_factory=lambda: dict(DESTINO_POR_TIPO))
    _notas: list[Nota] | None = field(default=None, repr=False)

    # -- Configuración -----------------------------------------------------

    @classmethod
    def cargar(cls, raiz: Path | str | None, crear: bool = False) -> "Vault":
        """Abre un Vault. Con `crear`, acepta una carpeta que todavía no existe."""
        if raiz is None or not str(raiz).strip():
            raise ErrorVault(
                "No hay ningún Vault de Obsidian configurado. Pon su ruta en "
                "TATEWARI_OBSIDIAN_VAULT dentro de tu archivo .env, o pásala con "
                "--vault RUTA."
            )
        raiz = Path(raiz).expanduser().resolve()
        if raiz.exists() and not raiz.is_dir():
            raise ErrorVault(f"La ruta del Vault no es una carpeta: {raiz}")
        if not raiz.exists() and not crear:
            raise ErrorVault(
                f"No existe el Vault: {raiz}\n"
                f"Crea la estructura con:  python -m tatewari conocimiento crear-vault "
                f"--vault \"{raiz}\""
            )
        vault = cls(raiz=raiz)
        configuracion = raiz / _CONFIG
        if configuracion.is_file():
            try:
                with open(configuracion, encoding="utf-8") as manejador:
                    datos = json.load(manejador)
            except (OSError, ValueError) as error:
                raise ErrorVault(
                    f"No se pudo leer la configuración del Vault ({configuracion}): {error}"
                ) from error
            if isinstance(datos, dict):
                vault.carpetas.update({str(k): str(v) for k, v in (datos.get("carpetas") or {}).items()})
                vault.destino_por_tipo.update(
                    {str(k): str(v) for k, v in (datos.get("destino_por_tipo") or {}).items()}
                )
        return vault

    def carpeta(self, nombre: str) -> Path:
        relativa = self.carpetas.get(nombre, nombre)
        return self.raiz / Path(*relativa.replace("\\", "/").split("/"))

    def carpeta_para_tipo(self, tipo: str) -> Path:
        return self.carpeta(self.destino_por_tipo.get(tipo, "conceptos"))

    def crear_estructura(self, jaula: Jaula) -> list[Path]:
        """Crea las carpetas, las plantillas y la configuración que falten.

        No toca nada que ya exista: se puede lanzar sobre un Vault con notas.
        """
        creadas = []
        for nombre in self.carpetas:
            carpeta = self.carpeta(nombre)
            if not carpeta.exists():
                jaula.crear_carpeta(carpeta)
                creadas.append(carpeta)
        for plantilla in ("concepto", "fuente", "personaje", "lugar", "proceso"):
            destino = self.carpeta("plantillas") / f"{plantilla.capitalize()}.md"
            if not destino.exists():
                jaula.escribir_texto(destino, plantilla_para_obsidian(leer_plantilla(plantilla)))
                creadas.append(destino)
        configuracion = self.raiz / _CONFIG
        if not configuracion.exists():
            # `.tatewari` no es una carpeta prohibida: es la configuración de Tatewari.
            jaula.escribir_texto(
                configuracion,
                json.dumps(
                    {"carpetas": self.carpetas, "destino_por_tipo": self.destino_por_tipo},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
            )
            creadas.append(configuracion)
        return creadas

    # -- Lectura -----------------------------------------------------------

    def _excluida(self, ruta: Path) -> bool:
        relativa = ruta.relative_to(self.raiz)
        if any(parte.lower() in CARPETAS_PROHIBIDAS or parte == ".tatewari" for parte in relativa.parts):
            return True
        for nombre in _NO_NOTAS:
            carpeta = self.carpeta(nombre)
            try:
                ruta.relative_to(carpeta)
                return True
            except ValueError:
                continue
        return False

    def notas(self, recargar: bool = False) -> list[Nota]:
        """Todas las notas de conocimiento del Vault. Se lee una vez y se recuerda."""
        if self._notas is not None and not recargar:
            return self._notas
        notas = []
        if self.raiz.is_dir():
            for ruta in sorted(self.raiz.rglob("*.md")):
                if self._excluida(ruta):
                    continue
                try:
                    texto = ruta.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                frontmatter, cuerpo, datos = leer_nota(texto)
                notas.append(Nota(ruta=ruta, frontmatter=frontmatter, cuerpo=cuerpo, datos=datos))
        self._notas = notas
        return notas

    def indice(self) -> dict[str, str]:
        """Clave de nombre o alias -> nombre de archivo de la nota."""
        indice: dict[str, str] = {}
        for nota in self.notas():
            for clave in nota.claves:
                indice.setdefault(clave, nota.nombre)
        return indice

    def buscar(self, nombre: str, alias: Iterable[str] = ()) -> Nota | None:
        """La nota que se llama así o tiene ese alias. Tolera un plural simple."""
        buscadas = {clave_de_nombre(n) for n in (nombre, *alias) if n}
        buscadas |= {c[:-2] for c in buscadas if c.endswith("es")}
        buscadas |= {c[:-1] for c in buscadas if c.endswith("s")}
        buscadas.discard("")
        materia = self.carpeta("materia")
        for nota in self.notas():
            # Los documentos de la materia y sus notas de fuente no son conceptos:
            # un apunte titulado «Suelo» no es la nota del concepto Suelo.
            if nota.tipo == "fuente" or _dentro(nota.ruta, materia):
                continue
            claves = nota.claves
            claves |= {c[:-1] for c in claves if c.endswith("s")}
            if buscadas & claves:
                return nota
        return None

    def buscar_texto(self, consulta: str, limite: int = 20) -> list[tuple[Nota, int]]:
        """Notas que contienen las palabras de la consulta, por número de aciertos."""
        palabras = [p for p in normalizar(consulta).split() if len(p) > 2]
        if not palabras:
            return []
        resultados = []
        for nota in self.notas():
            texto = nota.texto_plano
            aciertos = sum(texto.count(p) for p in palabras)
            if aciertos:
                resultados.append((nota, aciertos))
        resultados.sort(key=lambda par: (-par[1], par[0].nombre))
        return resultados[:limite]

    # -- Escritura ---------------------------------------------------------

    def ruta_nueva(self, objeto: ObjetoConocimiento) -> Path:
        return primera_ruta_libre(
            self.carpeta_para_tipo(objeto.tipo), nombre_de_nota(objeto.titulo)
        )

    def crear_nota(
        self,
        jaula: Jaula,
        objeto: ObjetoConocimiento,
        indice: Mapping[str, str],
        notas_fuente: Mapping[str, str],
        ruta: Path | None = None,
    ) -> Path:
        """obsidian_create_note: escribe una nota nueva. Nunca pisa una existente.

        `ruta` permite reservar el nombre antes de escribir (el orquestador lo
        hace para que las notas nuevas se enlacen entre sí). Si ya existe un
        archivo ahí, se busca el siguiente nombre libre.
        """
        if objeto.estado not in ("DRAFT", "REVIEW"):
            raise ErrorVault("Una nota generada solo puede nacer en DRAFT o en REVIEW.")
        if ruta is None or ruta.exists():
            ruta = self.ruta_nueva(objeto)
        return jaula.escribir_texto(ruta, render_objeto(objeto, indice, notas_fuente))

    def actualizar_nota(
        self,
        jaula: Jaula,
        nota: Nota,
        objeto: ObjetoConocimiento,
        indice: Mapping[str, str],
        notas_fuente: Mapping[str, str],
    ) -> Path:
        """obsidian_update_note: reescribe una nota **solo** si Tatewari puede.

        Lanza `ErrorVault` si la nota está aprobada, publicada, no es de
        Tatewari o alguien la editó a mano: en esos casos hay que proponer.
        """
        motivo = self.motivo_para_no_tocar(nota)
        if motivo:
            raise ErrorVault(f"No se actualiza «{nota.nombre}»: {motivo}")
        return jaula.escribir_texto(nota.ruta, render_objeto(objeto, indice, notas_fuente))

    @staticmethod
    def motivo_para_no_tocar(nota: Nota) -> str:
        """Por qué Tatewari no puede reescribir esta nota, o cadena vacía si puede."""
        if not nota.gestionada:
            return "no la escribió Tatewari; es una nota de una persona"
        if nota.estado in ESTADOS_PROTEGIDOS:
            return f"está en {nota.estado} y el conocimiento aprobado no se reescribe"
        if not nota.intacta:
            return "alguien la editó a mano después de que Tatewari la escribiera"
        return ""

    def proponer(
        self,
        jaula: Jaula,
        nota: Nota,
        objeto: ObjetoConocimiento,
        motivo: str,
        indice: Mapping[str, str],
        notas_fuente: Mapping[str, str],
    ) -> Path:
        """Deja una propuesta de actualización en la bandeja. La nota no se toca."""
        propuesta = render_objeto(objeto, indice, notas_fuente)
        # La propuesta no es una nota de conocimiento: sin datos ni frontmatter
        # gestionado, para que no se confunda con la nota real.
        _, cuerpo, _ = leer_nota(propuesta)
        cuerpo = re.sub(r"\n?%%.*?%%\s*$", "", cuerpo, flags=re.S).rstrip()
        texto = (
            escribir_frontmatter(
                {
                    "tipo": "propuesta",
                    "nota": nota.nombre,
                    "creado": ahora(),
                    "tags": ["knowledge-studio", "propuesta"],
                }
            )
            + f"# Propuesta para [[{nota.nombre}]]\n\n"
            + f"> [!question] Tatewari no ha modificado [[{nota.nombre}]]\n"
            + f"> Motivo: {motivo}.\n"
            + "> Abajo está lo que propone a partir del documento nuevo. Copia lo que te "
            "sirva a la nota y borra esta propuesta.\n\n"
            + cuerpo.replace(f"# {objeto.titulo}", "## Contenido propuesto", 1)
            + "\n"
        )
        destino = primera_ruta_libre(self.carpeta("propuestas"), nombre_de_nota(f"Propuesta - {nota.nombre}"))
        return jaula.escribir_texto(destino, texto)

    def cambiar_estado(self, jaula: Jaula, nombre: str, nuevo: str, autor: str) -> Nota:
        """Cambia el estado de una nota. Solo toca el frontmatter.

        APPROVED y PUBLISHED exigen un autor humano. Se anota quién y cuándo.
        """
        nota = self.buscar(nombre)
        if nota is None:
            raise ErrorVault(f"No hay ninguna nota llamada «{nombre}» en el Vault.")
        comprobar_transicion(nota.estado if nota.estado in ESTADOS else "DRAFT", nuevo, autor)
        texto = nota.ruta.read_text(encoding="utf-8")
        campos, cuerpo, datos = leer_nota(texto)
        campos["estado"] = nuevo
        campos["actualizado"] = ahora()
        if nuevo in ESTADOS_PROTEGIDOS:
            campos[f"{nuevo.lower()}_por"] = autor
            campos[f"{nuevo.lower()}_en"] = ahora()
        if datos is not None:
            datos["estado"] = nuevo
            # El estado vive en dos sitios; el bloque de datos también se actualiza
            # para que una fusión posterior no lo devuelva al anterior.
            cuerpo = re.sub(
                r"(%%\s*tatewari-datos\s*\n)(.*?)(\n%%\s*)$",
                lambda m: m.group(1) + json.dumps(datos, ensure_ascii=False, indent=1) + m.group(3),
                cuerpo,
                flags=re.S,
            )
        # El aviso visible del estado también se actualiza, si es el de Tatewari.
        intacta = str(campos.get("tatewari_hash") or "") == huella_cuerpo(cuerpo)
        cuerpo = re.sub(r"(> \[!info\] Estado: )\w+", rf"\g<1>{nuevo}", cuerpo, count=1)
        aprobada = re.compile(r"^> (?:Aprobado|Publicado) por .* Tatewari ya no reescribe esta nota\.$", re.M)
        if nuevo in ESTADOS_PROTEGIDOS:
            linea = aviso_aprobado(nuevo, autor, str(campos[f"{nuevo.lower()}_en"]))
            if AVISO_BORRADOR in cuerpo:
                cuerpo = cuerpo.replace(AVISO_BORRADOR, linea, 1)
            else:
                cuerpo = aprobada.sub(lambda _: linea, cuerpo, count=1)
        else:
            cuerpo = aprobada.sub(lambda _: AVISO_BORRADOR, cuerpo, count=1)
        if intacta:
            campos["tatewari_hash"] = huella_cuerpo(cuerpo)
        jaula.escribir_texto(nota.ruta, escribir_frontmatter(campos) + cuerpo)
        self._notas = None
        return self.buscar(nota.nombre) or nota

    # -- Índice para la vista de grafo ------------------------------------

    def escribir_indice(self, jaula: Jaula) -> Path:
        """Una nota que enlaza todo el conocimiento, agrupado por tipo y estado.

        Obsidian calcula los enlaces entrantes solo; este índice le da a la vista
        de grafo un centro desde el que se ve todo, y sirve de sumario.
        """
        por_tipo: dict[str, list[Nota]] = {}
        for nota in self.notas():
            if nota.gestionada and nota.tipo not in ("fuente", "propuesta"):
                por_tipo.setdefault(nota.tipo, []).append(nota)
        fuentes = [n for n in self.notas() if n.tipo == "fuente"]
        lineas = [
            f"# {NOMBRE_INDICE}",
            "",
            "> [!info] Generado por Tatewari. Se rehace entero cada vez: no lo edites a mano.",
            "",
        ]
        for tipo in sorted(por_tipo):
            lineas.append(f"## {tipo.capitalize()}")
            lineas.append("")
            for nota in sorted(por_tipo[tipo], key=lambda n: n.nombre.casefold()):
                lineas.append(f"- [[{nota.nombre}]] · {nota.estado}")
            lineas.append("")
        if fuentes:
            lineas.append("## Fuentes")
            lineas.append("")
            lineas.extend(f"- [[{n.nombre}]]" for n in sorted(fuentes, key=lambda n: n.nombre.casefold()))
            lineas.append("")
        texto = escribir_frontmatter({"tipo": "indice", "tags": ["knowledge-studio", "indice"], "actualizado": ahora()})
        return jaula.escribir_texto(self.raiz / f"{NOMBRE_INDICE}.md", texto + "\n".join(lineas))

    def enlaces_pendientes(self) -> dict[str, list[str]]:
        """Destinos de ``[[...]]`` que no son ninguna nota: destino -> notas que lo citan."""
        existentes = {n.nombre.casefold() for n in self.notas()}
        # Un enlace puede apuntar a cualquier archivo del Vault: una plantilla, un
        # reporte o un adjunto como «apuntes.pdf», que se enlaza con su extensión.
        for ruta in _otras_md(self.raiz):
            existentes.add(ruta.name.casefold())
            if ruta.suffix.lower() == ".md":
                existentes.add(ruta.stem.casefold())
        pendientes: dict[str, list[str]] = {}
        for nota in self.notas():
            for destino in enlaces_de(nota.cuerpo):
                if Path(destino).name.casefold() not in existentes and destino.casefold() not in existentes:
                    pendientes.setdefault(destino, []).append(nota.nombre)
        return pendientes


def _dentro(ruta: Path, carpeta: Path) -> bool:
    try:
        ruta.relative_to(carpeta)
        return True
    except ValueError:
        return False


def _otras_md(raiz: Path) -> list[Path]:
    """Todos los archivos del Vault, para que un enlace a un PDF o una plantilla cuente."""
    if not raiz.is_dir():
        return []
    return [p for p in raiz.rglob("*") if p.is_file() and ".obsidian" not in p.parts]


__all__ += ["ErrorRuta"]
