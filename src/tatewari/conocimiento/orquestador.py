"""El orquestador de Knowledge Studio: encadena habilidades y decide quién hace qué.

Tatewari no tenía orquestador; sus órdenes llamaban a funciones directamente.
Este no sustituye nada de lo que había: es el director de un solo flujo, el de
«Tatewari, procesa este documento». Decide:

- qué **habilidad** se usa en cada paso (y lo apunta en el reporte);
- qué **modelo** hace cada tarea, a través del `Enrutador`;
- que las herramientas **deterministas** hagan todo lo que toca archivos, y que
  el modelo solo interprete texto;
- que toda escritura pase por la **jaula** de rutas.

`interpretar_peticion` convierte una frase como «procesa este documento
apuntes.pdf» en una acción. Es una tabla de palabras clave, no un modelo: una
petición de escribir en el Vault no puede depender de que un modelo de 4B
entienda bien la frase.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..texto import normalizar
from .documento import NR, ErrorDocumento
from .enrutador import Enrutador
from .habilidades import habilidad
from .ingesta import TIPOS_ADMITIDOS, huella
from .markdown import leer_nota, render_fuente
from .normalizacion import trocear
from .reporte import ReporteProcesamiento, reporte_vault
from .rutas import ErrorRuta, Jaula, nombre_de_nota, primera_ruta_libre
from .validacion import ResultadoValidacion
from .vault import ErrorVault, Nota, Vault
from .analisis import ResultadoAnalisis, referencias_deterministas

__all__ = ["Orquestador", "Peticion", "interpretar_peticion", "ACCIONES"]

#: Acciones de alto nivel y cómo se pide cada una en lenguaje natural.
ACCIONES = {
    "procesar": "procesar documento",
    "materia": "analizar materia",
    "crear-vault": "crear base de conocimiento",
    "actualizar": "actualizar conocimiento existente",
    "conceptos": "mostrar conceptos detectados",
    "conflictos": "mostrar conflictos",
    "reporte": "generar reporte",
    "validar": "validar el Vault",
}


@dataclass
class Orquestador:
    vault: Vault
    jaula: Jaula
    enrutador: Enrutador | None = None
    sin_modelo: bool = False
    avance: Callable[[str], None] | None = None
    traza: list[str] = field(default_factory=list)

    # -- Habilidades con traza -------------------------------------------

    def _usar(self, nombre: str, *args: Any, **kwargs: Any) -> Any:
        herramienta = habilidad(nombre)
        inicio = time.perf_counter()
        try:
            return herramienta.funcion(*args, **kwargs)
        finally:
            self.traza.append(f"{nombre} ({time.perf_counter() - inicio:.1f} s)")

    def _decir(self, mensaje: str) -> None:
        if self.avance is not None:
            self.avance(mensaje)

    # -- Procesar un documento ---------------------------------------------

    def procesar_documento(self, ruta: Path | str) -> ReporteProcesamiento:
        """«Procesar documento»: del archivo a notas en el Vault, con su reporte."""
        self.traza = []
        ruta = Path(ruta)
        reporte = ReporteProcesamiento(archivo=ruta.name)
        # Se relee el Vault del disco: entre un documento y otro una persona pudo
        # editar o aprobar notas en Obsidian, y eso decide qué se puede tocar.
        self.vault.notas(recargar=True)

        aceptado = self._usar("document_ingest", ruta)
        reporte.tipo = aceptado.tipo
        self._decir(f"Documento aceptado: {ruta.name} ({aceptado.tipo.upper()}).")

        nombre_original = self._guardar_original(aceptado.ruta, aceptado.sha256, reporte)

        documento = self._usar("document_extract", aceptado)
        trozos = trocear(documento)
        reporte.unidades, reporte.unidad = documento.unidades, documento.unidad
        reporte.fragmentos, reporte.trozos = len(documento.fragmentos), len(trozos)
        reporte.avisos.extend(documento.avisos)
        self._decir(
            f"Texto extraído: {documento.unidades} {documento.unidad}, "
            f"{len(trozos)} trozos para el modelo."
        )

        if self.sin_modelo or self.enrutador is None:
            analisis = ResultadoAnalisis(trozos=len(trozos))
            analisis.referencias = referencias_deterministas(documento)
            reporte.avisos.append(
                "Procesado sin modelo: solo se extrajo el texto y las referencias. "
                "Para detectar conceptos, lanza la orden sin --sin-modelo con Ollama en marcha."
            )
            self.traza.append("knowledge_extract (omitida: sin modelo)")
        else:
            analisis = self._usar(
                "knowledge_extract",
                documento,
                trozos,
                self.enrutador,
                avance=lambda i, total, donde: self._decir(f"  [{i}/{total}] analizando {donde}…"),
            )
        reporte.modelo = analisis.modelo
        reporte.trozos_analizados = analisis.trozos_analizados
        reporte.segundos = analisis.segundos
        reporte.referencias = analisis.referencias
        reporte.sin_verificar = analisis.sin_verificar
        reporte.insuficientes = analisis.trozos_insuficientes
        reporte.avisos.extend(analisis.avisos)
        reporte.errores.extend(analisis.errores)
        for objeto in analisis.objetos:
            reporte.por_tipo[objeto.tipo] += 1

        # La nota de la fuente: su nombre se decide antes, para enlazarla.
        nombre_fuente = nombre_de_nota(f"Fuente - {documento.titulo_legible}")
        # Todas las fuentes conocidas, no solo esta: al fundir una nota con lo que
        # ya tenía, sus afirmaciones de documentos anteriores siguen enlazadas.
        notas_fuente = self._notas_fuente()
        notas_fuente[documento.nombre] = nombre_fuente

        acciones = self._usar("knowledge_link", analisis.objetos, self.vault)
        indice = self.vault.indice()
        rutas_nuevas: dict[int, Path] = {}
        reservadas: list[Path] = []
        for n, accion in enumerate(acciones):
            if accion.tipo == "crear":
                ruta_nueva = primera_ruta_libre(
                    self.vault.carpeta_para_tipo(accion.objeto.tipo),
                    nombre_de_nota(accion.objeto.titulo),
                    reservadas,
                )
                reservadas.append(ruta_nueva)
                rutas_nuevas[n] = ruta_nueva
                indice.setdefault(accion.objeto.clave, ruta_nueva.stem)
            elif accion.nota is not None:
                indice.setdefault(accion.objeto.clave, accion.nota.nombre)

        extraidos: list[tuple[str, Any]] = []
        for n, accion in enumerate(acciones):
            objeto = accion.objeto
            try:
                if accion.tipo == "crear":
                    ruta_nota = self._usar(
                        "obsidian_create_note", self.vault, self.jaula, objeto,
                        indice, notas_fuente, ruta=rutas_nuevas[n],
                    )
                    reporte.nuevas.append(ruta_nota.stem)
                    extraidos.append((ruta_nota.stem, objeto))
                    if accion.posibles_duplicados:
                        reporte.duplicados.append((ruta_nota.stem, accion.posibles_duplicados))
                elif accion.tipo == "actualizar":
                    self._usar("obsidian_update_note", self.vault, self.jaula, accion.nota, objeto, indice, notas_fuente)
                    reporte.actualizadas.append(accion.nota.nombre)
                    extraidos.append((accion.nota.nombre, objeto))
                else:
                    self.vault.proponer(self.jaula, accion.nota, objeto, accion.motivo, indice, notas_fuente)
                    reporte.propuestas.append((accion.nota.nombre, accion.motivo))
                    extraidos.append((accion.nota.nombre, objeto))
                if objeto.conflictos:
                    reporte.conflictos.append(accion.nota.nombre if accion.nota else objeto.titulo)
            except (ErrorRuta, ErrorVault, OSError) as error:
                reporte.errores.append(f"No se pudo escribir «{objeto.titulo}»: {error}")

        reporte.nota_fuente = self._escribir_fuente(
            documento, nombre_original, nombre_fuente, extraidos, analisis.referencias, reporte
        )

        self.vault._notas = None
        try:
            self.vault.escribir_indice(self.jaula)
        except (ErrorRuta, OSError) as error:
            reporte.errores.append(f"No se pudo escribir el índice: {error}")

        reporte.herramientas = list(self.traza)
        reporte.ruta_reporte = self._guardar_reporte(reporte, documento.titulo_legible)
        return reporte

    def _notas_fuente(self) -> dict[str, str]:
        """Archivo original -> nombre de su nota de fuente, de todo el Vault."""
        return {
            str(n.frontmatter.get("archivo")): n.nombre
            for n in self.vault.notas()
            if n.tipo == "fuente" and n.frontmatter.get("archivo")
        }

    def _guardar_original(self, origen: Path, sha: str, reporte: ReporteProcesamiento) -> str:
        """Copia el original a la carpeta de materia, si no está ya. Nunca lo mueve."""
        materia = self.vault.carpeta("materia")
        try:
            origen.relative_to(self.vault.raiz)
            return origen.name  # ya está dentro del Vault: se deja donde está
        except ValueError:
            pass
        destino = materia / origen.name
        numero = 2
        while destino.exists():
            if huella(destino) == sha:
                return destino.name  # el mismo documento ya estaba copiado
            destino = materia / f"{origen.stem} ({numero}){origen.suffix}"
            numero += 1
        try:
            self.jaula.copiar(origen, destino)
            self.traza.append("copia del original a la materia")
        except (ErrorRuta, OSError) as error:
            reporte.errores.append(f"No se pudo copiar el original al Vault: {error}")
            return origen.name
        return destino.name

    def _escribir_fuente(self, documento, nombre_original, nombre_fuente, extraidos, referencias, reporte) -> str:
        ruta = self.vault.carpeta("materia") / f"{nombre_fuente}.md"
        if ruta.exists():
            campos, cuerpo, _ = leer_nota(ruta.read_text(encoding="utf-8"))
            from .markdown import huella_cuerpo

            if str(campos.get("tatewari_hash") or "") != huella_cuerpo(cuerpo):
                reporte.avisos.append(
                    f"La nota de fuente [[{nombre_fuente}]] se editó a mano: no se reescribe."
                )
                return nombre_fuente
        try:
            self.jaula.escribir_texto(
                ruta, render_fuente(documento, nombre_original, extraidos, referencias, documento.avisos)
            )
        except (ErrorRuta, OSError) as error:
            reporte.errores.append(f"No se pudo escribir la nota de fuente: {error}")
        return nombre_fuente

    def _guardar_reporte(self, reporte: ReporteProcesamiento, titulo: str) -> Path | None:
        marca = datetime.now().strftime("%Y-%m-%d %H%M")
        destino = primera_ruta_libre(
            self.vault.carpeta("reportes"), nombre_de_nota(f"Reporte {marca} - {titulo}")
        )
        try:
            return self.jaula.escribir_texto(destino, reporte.markdown())
        except (ErrorRuta, OSError) as error:
            reporte.errores.append(f"No se pudo guardar el reporte en el Vault: {error}")
            return None

    # -- Las demás acciones -----------------------------------------------

    def analizar_materia(
        self, carpeta: Path | str | None = None, forzar: bool = False
    ) -> list[ReporteProcesamiento | tuple[str, str]]:
        """«Analizar materia»: procesa todos los documentos de una carpeta.

        Por defecto, la carpeta de materia del Vault. Se saltan los documentos ya
        procesados (misma huella) salvo con `forzar`. Un documento que falla no
        para a los demás: su error va en la lista de resultados.
        """
        carpeta = Path(carpeta) if carpeta else self.vault.carpeta("materia")
        if not carpeta.is_dir():
            raise ErrorVault(f"No existe la carpeta de materia: {carpeta}")
        procesados = {
            str(n.frontmatter.get("sha256")) for n in self.vault.notas() if n.tipo == "fuente"
        }
        resultados: list[ReporteProcesamiento | tuple[str, str]] = []
        for ruta in sorted(carpeta.iterdir()):
            if ruta.suffix.lower() not in TIPOS_ADMITIDOS or not ruta.is_file():
                continue
            if ruta.suffix.lower() == ".md" and ruta.stem.startswith("Fuente - "):
                continue  # es una nota de fuente, no un documento
            try:
                if not forzar and huella(ruta) in procesados:
                    resultados.append((ruta.name, "ya procesado (usa --forzar para repetir)"))
                    continue
                resultados.append(self.procesar_documento(ruta))
            except (ErrorDocumento, ErrorVault, ErrorRuta) as error:
                resultados.append((ruta.name, str(error)))
        return resultados

    def crear_base(self) -> list[Path]:
        """«Crear base de conocimiento»: la estructura del Vault, sin tocar lo que haya."""
        creadas = self.vault.crear_estructura(self.jaula)
        self.vault._notas = None
        self.vault.escribir_indice(self.jaula)
        return creadas

    def actualizar(self) -> ResultadoValidacion:
        """«Actualizar conocimiento existente»: rehace enlaces e índice sin modelo.

        Las notas de Tatewari que siguen intactas se vuelven a escribir con el
        índice actual, así los enlaces que antes apuntaban a notas inexistentes
        pasan a resolverse cuando esas notas ya existen. Las aprobadas y las
        editadas a mano no se tocan.
        """
        from .markdown import render_objeto

        self.vault.notas(recargar=True)
        indice = self.vault.indice()
        fuentes = self._notas_fuente()
        for nota in self.vault.notas():
            if nota.tipo in ("fuente", "propuesta", "indice") or self.vault.motivo_para_no_tocar(nota):
                continue
            objeto = nota.objeto()
            if objeto is not None:
                self.jaula.escribir_texto(nota.ruta, render_objeto(objeto, indice, fuentes))
        self.vault._notas = None
        self.vault.escribir_indice(self.jaula)
        return self.validar()

    def conceptos(self, estado: str | None = None, tipo: str | None = None) -> list[Nota]:
        """«Mostrar conceptos detectados»."""
        notas = [
            n for n in self.vault.notas(recargar=True)
            if n.gestionada and n.tipo not in ("fuente", "propuesta", "indice")
        ]
        if estado:
            notas = [n for n in notas if n.estado == estado.upper()]
        if tipo:
            notas = [n for n in notas if n.tipo == tipo]
        return sorted(notas, key=lambda n: (n.tipo, n.nombre.casefold()))

    def conflictos(self) -> list[Nota]:
        """«Mostrar conflictos»."""
        return [n for n in self.vault.notas(recargar=True) if n.conflictos]

    def validar(self) -> ResultadoValidacion:
        return self._usar("obsidian_validate", self.vault)

    def reporte(self) -> tuple[ResultadoValidacion, Path | None]:
        """«Generar reporte»: valida el Vault y deja el reporte en su carpeta."""
        resultado = self.validar()
        texto = self._usar("knowledge_report", resultado)
        destino = primera_ruta_libre(
            self.vault.carpeta("reportes"),
            nombre_de_nota(f"Reporte del Vault {datetime.now():%Y-%m-%d %H%M}"),
        )
        try:
            return resultado, self.jaula.escribir_texto(destino, texto)
        except (ErrorRuta, OSError):
            return resultado, None


# ---------------------------------------------------------------------------
# «Tatewari, procesa este documento»
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Peticion:
    accion: str
    argumento: str | None = None


_CITADO = re.compile(r"[\"'«“]([^\"'»”]+)[\"'»”]")
_ARCHIVO = re.compile(
    r"(\S+\.(?:pdf|docx|pptx|txt|md|markdown))\b", re.I
)

#: Orden importa: lo más específico primero.
_INTENCIONES = (
    ("conflictos", ("conflicto",)),
    ("conceptos", ("muestra los conceptos", "mostrar conceptos", "lista los conceptos",
                   "que conceptos", "conceptos detectados", "ver conceptos", "muestra conceptos")),
    ("reporte", ("reporte", "informe")),
    ("validar", ("valida",)),
    ("crear-vault", ("crea la base", "crear base", "crear la base", "crea el vault",
                     "crear vault", "crea la estructura", "crear la estructura",
                     "base de conocimiento")),
    ("actualizar", ("actualiza", "actualizar")),
    ("materia", ("materia", "carpeta", "todos los documentos")),
    ("procesar", ("procesa", "procesar", "analiza", "analizar", "lee", "leer", "ingiere")),
)


def interpretar_peticion(texto: str) -> Peticion | None:
    """Convierte una frase en español en una acción. `None` si no la entiende.

    Se busca la ruta primero entre comillas y, si no, como una palabra con
    extensión de documento. «procesa este documento» sin ruta devuelve la acción
    sin argumento, y quien llama lo pide.
    """
    plano = normalizar(texto)
    plano = re.sub(r"^\s*tatewari\s*[,:]?\s*", "", plano)

    citado = _CITADO.search(texto)
    archivo = citado.group(1).strip() if citado else None
    if archivo is None:
        encontrado = _ARCHIVO.search(texto)
        archivo = encontrado.group(1) if encontrado else None

    for accion, claves in _INTENCIONES:
        if any(normalizar(clave) in plano for clave in claves):
            if accion == "materia" and archivo and Path(archivo).suffix:
                # «analiza la materia del archivo X.pdf» es procesar un documento.
                return Peticion("procesar", archivo)
            if accion == "crear-vault" and "procesa" in plano:
                continue
            return Peticion(accion, archivo)
    if archivo and Path(archivo).suffix.lower() in TIPOS_ADMITIDOS:
        return Peticion("procesar", archivo)
    return None
