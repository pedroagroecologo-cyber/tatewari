"""Una nota de Obsidian por artículo incluido.

``incluidos.md`` es un solo archivo con todas las fichas: sirve para leer de
corrido, pero no para trabajar un artículo. Este módulo escribe, en la carpeta
``notas/`` de la revisión, **una nota por incluido** y un índice. Si la bóveda
de Obsidian está ligada a ``revisiones/`` (un enlace simbólico, como explica la
guía), las notas aparecen solas en Obsidian cada vez que se exporta.

Cada nota lleva
---------------

- Propiedades de Obsidian (el bloque ``---`` de arriba): DOI, año, revista,
  autores, decisión, clasificación, acceso y etiquetas, para filtrar y buscar.
- El enlace al PDF descargado (``tatewari descargar``), o al texto abierto, o
  el aviso de que hay que pedirlo a la biblioteca.
- El **resumen completo de los autores**, tal cual: no lo reescribe ningún
  modelo (AGENTS.md, regla 2).
- Un apartado ``## Mis notas`` que es de la persona.

Lo que escribe la persona no se pisa
------------------------------------

Exportar se repite cada vez que cambia el cribado. Todo lo que está **debajo de
«## Mis notas»** se lee antes de reescribir la nota y se vuelve a poner tal
cual. Lo de arriba sí se regenera, porque son datos de la revisión. Y una nota
cuyo artículo dejó de estar incluido no se borra: puede tener trabajo dentro.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote

from .descargas import CARPETA_PDF, nombre_de_archivo
from .fuentes import NR

__all__ = [
    "CARPETA_NOTAS",
    "MARCA_MIS_NOTAS",
    "NOMBRE_INDICE",
    "ResultadoNotas",
    "lista_de_autores",
    "nombre_de_nota",
    "nota_markdown",
    "mis_notas_de",
    "escribir_notas",
]

CARPETA_NOTAS = "notas"
NOMBRE_INDICE = "00 Índice.md"
MARCA_MIS_NOTAS = "## Mis notas"
TEXTO_INICIAL = (
    "_Escribe aquí. Tatewari no toca nada de lo que quede debajo de este título, "
    "aunque vuelvas a exportar._"
)

#: Caracteres que no van en un nombre de archivo de Windows ni en un enlace de
#: Obsidian.
_PROHIBIDOS = re.compile(r'[\\/:*?"<>|#^\[\]]+')
_ESPACIOS = re.compile(r"\s+")
LARGO_TITULO = 70


def _texto(valor: Any) -> str:
    if valor is None:
        return NR
    limpio = " ".join(str(valor).split())
    return limpio or NR


def lista_de_autores(autores: Any) -> list[str]:
    """Los autores como lista, venga como lista o como el texto de una lista."""
    if isinstance(autores, (list, tuple)):
        lista = list(autores)
    elif isinstance(autores, str):
        texto = autores.strip()
        if texto in ("", NR):
            return []
        if texto.startswith("["):
            try:
                lista = json.loads(texto.replace("'", '"'))
            except ValueError:
                lista = texto.strip("[]").split(",")
        else:
            lista = texto.split(";")
    else:
        return []
    return [" ".join(str(a).strip().strip("'\"").split()) for a in lista if str(a).strip()]


def nombre_de_nota(identificador: str, registro: Mapping[str, Any]) -> str:
    """«R0001 Lime stabilization for compressed stabilized earth blocks…»."""
    titulo = _ESPACIOS.sub(" ", _PROHIBIDOS.sub(" ", _texto(registro.get("titulo")))).strip()
    if len(titulo) > LARGO_TITULO:
        corte = titulo[:LARGO_TITULO]
        espacio = corte.rfind(" ")
        titulo = (corte[:espacio] if espacio > LARGO_TITULO // 2 else corte).rstrip(" ,;.-")
    return f"{identificador} {titulo}".strip()


def _enlace_relativo(texto: str, ruta: str) -> str:
    """Enlace Markdown relativo, con los espacios codificados para Obsidian."""
    return f"[{texto}]({quote(ruta, safe='/.-_')})"


def _yaml(valor: Any) -> str:
    """Un valor de propiedad, entrecomillado de forma segura."""
    return json.dumps(valor, ensure_ascii=False)


def mis_notas_de(ruta: Path) -> str | None:
    """Lo que la persona escribió debajo de «## Mis notas», o ``None``."""
    if not ruta.is_file():
        return None
    texto = ruta.read_text(encoding="utf-8")
    posicion = texto.find("\n" + MARCA_MIS_NOTAS)
    if posicion < 0:
        return None
    resto = texto[posicion + 1 + len(MARCA_MIS_NOTAS):].strip("\n")
    # Si ya escribió algo, el texto de ejemplo sobra.
    sin_ejemplo = resto.replace(TEXTO_INICIAL, "").strip("\n")
    return sin_ejemplo if sin_ejemplo.strip() else resto


def nota_markdown(
    decision: Any,
    revision: str,
    pdf: str | None = None,
    mis_notas: str | None = None,
) -> str:
    """La nota de un incluido. `pdf` es el nombre del archivo en ``pdf/``."""
    registro = decision.registro
    doi = _texto(registro.get("doi"))
    oa = _texto(registro.get("oa_url"))
    autores = lista_de_autores(registro.get("autores"))
    anio = _texto(registro.get("anio"))
    clasificacion = _texto(getattr(decision, "clasificacion", NR))
    acceso = "pdf" if pdf else ("abierto" if oa != NR else "por conseguir")

    propiedades = [
        "---",
        f"id: {_yaml(decision.identificador)}",
        f"revision: {_yaml(revision)}",
        f"titulo: {_yaml(_texto(registro.get('titulo')))}",
        f"autores: {_yaml(autores)}",
        f"anio: {anio if anio.isdigit() else _yaml(anio)}",
        f"revista: {_yaml(_texto(registro.get('revista')))}",
        f"doi: {_yaml(doi)}",
        f"decision: {_yaml(_texto(getattr(decision, 'decision', 'incluir')))}",
        f"clasificacion: {_yaml(clasificacion)}",
        f"acceso: {_yaml(acceso)}",
        f"tags: {_yaml(['tatewari', f'tatewari/{revision}'])}",
        "---",
    ]

    if pdf:
        texto_completo = _enlace_relativo(f"📄 {pdf}", f"../{CARPETA_PDF}/{pdf}")
    elif oa != NR:
        texto_completo = f"[acceso abierto]({oa}) (no se bajó solo: ábrelo y guárdalo en `pdf/`)"
    else:
        texto_completo = "sin versión abierta: pídelo a la biblioteca o al autor (está en `por-conseguir.md`)"

    cuerpo = [
        f"# {_texto(registro.get('titulo'))}",
        "",
        f"**Autores:** {'; '.join(autores) if autores else NR}  ",
        f"**Año:** {anio} · **Revista:** {_texto(registro.get('revista'))}  ",
        f"**DOI:** " + (f"[{doi}](https://doi.org/{doi})" if doi != NR else NR) + "  ",
        f"**Texto completo:** {texto_completo}  ",
        f"**Tatewari:** {_texto(getattr(decision, 'decision', 'incluir'))} — "
        f"{_texto(getattr(decision, 'motivo', NR))} "
        f"(decidido por {_texto(getattr(decision, 'decidido_por', NR))})",
        "",
        "## Resumen de los autores",
        "",
        _texto(registro.get("resumen")) if _texto(registro.get("resumen")) != NR
        else "_El registro no trae resumen (NR)._",
        "",
        MARCA_MIS_NOTAS,
        "",
        mis_notas if mis_notas else TEXTO_INICIAL,
    ]
    return "\n".join(propiedades + [""] + cuerpo) + "\n"


@dataclass
class ResultadoNotas:
    carpeta: Path
    escritas: int = 0
    con_pdf: int = 0
    conservadas: int = 0
    nombres: list[str] = field(default_factory=list)


def _indice(decisiones: list[Any], nombres: Mapping[str, str], revision: str) -> str:
    grupos: dict[str, list[Any]] = {}
    for decision in decisiones:
        grupos.setdefault(_texto(getattr(decision, "clasificacion", NR)), []).append(decision)
    lineas = [
        f"# Índice · {revision}",
        "",
        f"{len(decisiones)} artículos incluidos, agrupados por la clasificación del protocolo.",
        "Cada nota tiene un apartado «Mis notas» que Tatewari no toca.",
        "",
    ]
    for grupo in sorted(grupos, key=lambda g: (g == NR, g)):
        lineas.append(f"## {grupo if grupo != NR else 'Sin clasificación'}")
        lineas.append("")
        for decision in grupos[grupo]:
            nombre = nombres[decision.identificador]
            anio = _texto(decision.registro.get("anio"))
            lineas.append(f"- {_enlace_relativo(nombre, nombre + '.md')} ({anio})")
        lineas.append("")
    return "\n".join(lineas)


def escribir_notas(
    decisiones: Iterable[Any],
    carpeta: Path | str,
    revision: str,
) -> ResultadoNotas:
    """Escribe una nota por decisión y el índice en ``carpeta/notas``."""
    carpeta = Path(carpeta)
    destino = carpeta / CARPETA_NOTAS
    destino.mkdir(parents=True, exist_ok=True)
    resultado = ResultadoNotas(carpeta=destino)
    lista = list(decisiones)
    nombres: dict[str, str] = {}
    for decision in lista:
        nombre = nombre_de_nota(decision.identificador, decision.registro)
        nombres[decision.identificador] = nombre
        ruta = destino / f"{nombre}.md"
        archivo_pdf = nombre_de_archivo(decision.identificador, decision.registro)
        pdf = archivo_pdf if (carpeta / CARPETA_PDF / archivo_pdf).is_file() else None
        previas = mis_notas_de(ruta)
        if previas and previas.strip() != TEXTO_INICIAL:
            resultado.conservadas += 1
        ruta.write_text(
            nota_markdown(decision, revision, pdf, previas), encoding="utf-8", newline="\n"
        )
        resultado.escritas += 1
        resultado.con_pdf += 1 if pdf else 0
        resultado.nombres.append(nombre)
    (destino / NOMBRE_INDICE).write_text(
        _indice(lista, nombres, revision) + "\n", encoding="utf-8", newline="\n"
    )
    return resultado
