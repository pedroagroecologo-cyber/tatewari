"""Exportación: BibTeX y fichas en Markdown.

Cuatro archivos, y cada uno existe para un momento concreto del trabajo:

``incluidos.bib``
    Para meter la bibliografía en Zotero o en Mendeley y citar desde el
    procesador de textos.

``incluidos.md``
    Una ficha por artículo, para leer de corrido sin abrir el CSV.

``revision-manual.md``
    Los dudosos, con el motivo del filtro y de quién fue la decisión, con la
    orden de `decidir` ya escrita al lado de cada uno. Es la lista de tareas de
    la persona que revisa.

``por-conseguir.md``
    Los incluidos **sin** versión en acceso abierto, con su DOI, para pedirlos a
    la biblioteca. Tatewari no elude muros de pago (AGENTS.md, regla 5): esos
    textos se consiguen a mano, uno por uno, con la credencial institucional.

La clave de BibTeX
------------------

``PruebaUno2021R0001``: apellido del primer autor, año, identificador. El
identificador va dentro a propósito, y es lo que hace la clave **estable y
única**: dos artículos del mismo autor y año no chocan, y la clave de un
artículo no cambia entre exportaciones aunque se cosechen cien registros más.
Una cita en un manuscrito sigue apuntando a lo mismo el mes que viene.

Los campos que faltan
---------------------

Un campo no reportado **se omite** del `.bib` y se anota en `note`, que queda
así: ``Campos no reportados (NR): año, revista.``

Es la única forma de cumplir las dos cosas a la vez. Escribir ``year = {NR}``
seguiría la regla 2 de AGENTS.md al pie de la letra, pero Zotero y Mendeley
leerían «NR» como si fuera una fecha y la ficha entraría con la fecha
corrompida; omitir el campo sin más perdería el dato de que **se sabe** que no
está. Con la omisión más la nota, no se inventa nada, no se pierde nada, y el
archivo abre limpio en los dos gestores.

El escapado de LaTeX
--------------------

Un título con un ``&`` o un ``_`` sin escapar rompe el archivo al importarlo. Se
escapan los diez caracteres especiales de LaTeX, y la barra invertida **primero**,
porque si no se escaparían las barras que acabamos de meter nosotros.

El texto se deja en UTF-8 y no se convierte a macros (``\\'o`` por «ó»): Zotero y
Mendeley leen UTF-8 desde hace años, y convertir acentos a macros es la vía
rápida para destrozar un título en español.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .fuentes import NR
from .texto import normalizar

__all__ = [
    "NOMBRE_BIB",
    "NOMBRE_INCLUIDOS",
    "NOMBRE_REVISION",
    "NOMBRE_POR_CONSEGUIR",
    "LIMITE_RESUMEN",
    "ResultadoExportacion",
    "clave_bibtex",
    "escapar_latex",
    "entrada_bibtex",
    "bibtex_de",
    "ficha_markdown",
    "incluidos_markdown",
    "revision_manual_markdown",
    "por_conseguir_markdown",
    "exportar",
]

NOMBRE_BIB = "incluidos.bib"
NOMBRE_INCLUIDOS = "incluidos.md"
NOMBRE_REVISION = "revision-manual.md"
NOMBRE_POR_CONSEGUIR = "por-conseguir.md"

#: Caracteres del resumen que entran en una ficha. Una ficha es para decidir si
#: vale la pena abrir el artículo, no para sustituirlo.
LIMITE_RESUMEN = 700

#: Los diez caracteres especiales de LaTeX y su forma escapada.
#:
#: Se aplica en **una sola pasada** con `str.translate`, y eso no es un detalle
#: de estilo: reemplazando uno por uno, la barra invertida (que se convierte en
#: ``\textbackslash{}``) mete un par de llaves que la regla de las llaves
#: escaparía después, dando ``\textbackslash\{\}``, que ya no es la orden de
#: LaTeX que queríamos. Con una pasada, lo que se inserta no se vuelve a mirar.
_ESCAPES_LATEX = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

_TRADUCCION_LATEX = str.maketrans(_ESCAPES_LATEX)

#: Lo que se admite en una clave de BibTeX. Se deja solo ASCII alfanumérico:
#: una clave con acentos o guiones es legal en biblatex y un problema en algún
#: gestor, y aquí no se gana nada arriesgando.
_NO_CLAVE = re.compile(r"[^A-Za-z0-9]+")

#: Tipos de documento del protocolo y su entrada de BibTeX. Una revisión es un
#: artículo de revista: BibTeX no tiene `@review`.
_TIPOS_BIBTEX = {
    "article": "article",
    "review": "article",
    "journal-article": "article",
    "book": "book",
    "book-chapter": "incollection",
    "proceedings-article": "inproceedings",
    "dissertation": "phdthesis",
    "report": "techreport",
    "posted-content": "misc",
    "preprint": "misc",
}

#: Nombre legible de cada campo, para la nota de campos no reportados.
_NOMBRES_CAMPOS = {
    "author": "autores",
    "title": "título",
    "journal": "revista",
    "year": "año",
    "doi": "DOI",
    "language": "idioma",
}


def _es_nr(valor: Any) -> bool:
    """¿Este campo no viene reportado?"""
    if valor is None:
        return True
    if isinstance(valor, str):
        return not valor.strip() or valor.strip() == NR
    if isinstance(valor, (list, tuple)):
        return not valor or all(_es_nr(v) for v in valor)
    return False


def _texto(valor: Any, si_falta: str = NR) -> str:
    """El valor como texto limpio, o `si_falta` si no hay nada."""
    if _es_nr(valor):
        return si_falta
    return " ".join(str(valor).split())


# ---------------------------------------------------------------------------
# BibTeX
# ---------------------------------------------------------------------------


def escapar_latex(texto: object) -> str:
    """Escapa los caracteres especiales de LaTeX de `texto`.

    Sin esto, un título con «Remoción de N & P» o con «flujo_vertical» rompe el
    archivo al importarlo en Zotero. El texto se deja en UTF-8: los acentos no se
    convierten a macros.

    Se escapa también en el DOI y en la URL. Puede sorprender —un ``_`` escapado
    dentro de un DOI se ve raro en el archivo— pero es lo correcto: Zotero y
    Mendeley deshacen el escapado al importar, y sin él un ``%`` de una URL
    porcentocodificada abriría un comentario de LaTeX que se comería el resto de
    la línea, incluida la llave de cierre. Eso sí rompe el archivo.
    """
    return _texto(texto, si_falta="").translate(_TRADUCCION_LATEX)


def _apellido(autores: Any) -> str:
    """El apellido del primer autor, listo para una clave.

    Los autores llegan como ``"Prueba Uno, A."``, así que el apellido es lo que
    va antes de la coma. Si no hay coma, se toma la última palabra, que es lo que
    suele ser el apellido en «Ana Prueba Uno».
    """
    if _es_nr(autores):
        return "SinAutor"
    primero = autores[0] if isinstance(autores, (list, tuple)) else autores
    texto = _texto(primero, si_falta="")
    if _es_nr(texto):
        return "SinAutor"
    if "," in texto:
        apellido = texto.split(",", 1)[0]
    else:
        partes = texto.split()
        apellido = partes[-1] if partes else ""
    # Sin acentos y sin nada que no sea ASCII alfanumérico.
    limpio = _NO_CLAVE.sub("", normalizar(apellido).title())
    return limpio or "SinAutor"


def clave_bibtex(registro: Mapping[str, Any]) -> str:
    """La clave de cita: apellido del primer autor, año e identificador.

    El identificador es lo que la hace única y estable. Ver la cabecera del
    módulo.
    """
    anio = registro.get("anio")
    parte_anio = str(anio) if isinstance(anio, int) and not isinstance(anio, bool) else ""
    identificador = _NO_CLAVE.sub("", _texto(registro.get("identificador"), ""))
    clave = f"{_apellido(registro.get('autores'))}{parte_anio}{identificador}"
    return clave or "SinClave"


def _autores_bibtex(autores: Any) -> str:
    """Los autores separados por ``and``, que es como los une BibTeX."""
    if _es_nr(autores):
        return ""
    lista = autores if isinstance(autores, (list, tuple)) else [autores]
    limpios = [escapar_latex(a) for a in lista if not _es_nr(a)]
    return " and ".join(limpios)


def entrada_bibtex(
    registro: Mapping[str, Any], clasificacion: str = NR, decidido_por: str = ""
) -> str:
    """Una entrada de BibTeX de un registro.

    Los campos sin reportar se omiten y se listan en `note`. El título va entre
    dobles llaves para que el gestor no le cambie las mayúsculas: «DQO» y «UASB»
    tienen que seguir en mayúsculas después de importar.
    """
    tipo = _TIPOS_BIBTEX.get(_texto(registro.get("tipo"), "").lower(), "misc")
    clave = clave_bibtex(registro)

    campos: list[tuple[str, str]] = []
    faltantes: list[str] = []

    autores = _autores_bibtex(registro.get("autores"))
    if autores:
        campos.append(("author", f"{{{autores}}}"))
    else:
        faltantes.append(_NOMBRES_CAMPOS["author"])

    titulo = escapar_latex(registro.get("titulo"))
    if titulo:
        # Dobles llaves: protege las mayúsculas del título entero.
        campos.append(("title", f"{{{{{titulo}}}}}"))
    else:
        faltantes.append(_NOMBRES_CAMPOS["title"])

    revista = escapar_latex(registro.get("revista"))
    if revista:
        campos.append(("journal", f"{{{revista}}}"))
    else:
        faltantes.append(_NOMBRES_CAMPOS["journal"])

    anio = registro.get("anio")
    if isinstance(anio, int) and not isinstance(anio, bool):
        campos.append(("year", f"{{{anio}}}"))
    else:
        faltantes.append(_NOMBRES_CAMPOS["year"])

    doi = _texto(registro.get("doi"), "")
    if doi:
        campos.append(("doi", f"{{{escapar_latex(doi)}}}"))
    else:
        faltantes.append(_NOMBRES_CAMPOS["doi"])

    idioma = _texto(registro.get("idioma"), "")
    if idioma:
        campos.append(("language", f"{{{escapar_latex(idioma)}}}"))

    url = _texto(registro.get("oa_url"), "")
    if url:
        campos.append(("url", f"{{{escapar_latex(url)}}}"))

    # La nota reúne el rastro: de dónde sale la ficha y qué no se sabe de ella.
    notas = [f"Tatewari {_texto(registro.get('identificador'), NR)}"]
    if not _es_nr(clasificacion):
        notas.append(f"Clasificación: {escapar_latex(clasificacion)}")
    if decidido_por:
        notas.append(f"Decidido por: {escapar_latex(decidido_por)}")
    if faltantes:
        notas.append(f"Campos no reportados (NR): {', '.join(faltantes)}")
    campos.append(("note", f"{{{'. '.join(notas)}.}}"))

    ancho = max(len(nombre) for nombre, _ in campos)
    lineas = [f"@{tipo}{{{clave},"]
    lineas.extend(
        f"  {nombre.ljust(ancho)} = {valor}," for nombre, valor in campos
    )
    lineas.append("}")
    return "\n".join(lineas)


def bibtex_de(decisiones: Sequence[Any], revision: str = NR, fecha: str = "") -> str:
    """El archivo BibTeX completo de una lista de decisiones.

    La cabecera va en comentarios ``%``, que es lo que BibTeX ignora: Zotero y
    Mendeley los saltan sin quejarse.
    """
    lineas = [
        f"% Tatewari — bibliografía de los registros incluidos",
        f"% Revisión : {revision}",
        f"% Generado : {fecha or datetime.now().isoformat(timespec='seconds')}",
        f"% Entradas : {len(decisiones)}",
        "%",
        "% Las claves son estables: apellido del primer autor, año e",
        "% identificador de Tatewari. No cambian entre exportaciones.",
        "",
    ]
    for decision in decisiones:
        lineas.append(
            entrada_bibtex(
                decision.registro,
                clasificacion=getattr(decision, "clasificacion", NR),
                decidido_por=getattr(decision, "decidido_por", ""),
            )
        )
        lineas.append("")
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _recortar(texto: object, limite: int = LIMITE_RESUMEN) -> str:
    """Recorta el resumen a `limite` caracteres, cortando en un espacio."""
    limpio = _texto(texto)
    if limpio == NR or len(limpio) <= limite:
        return limpio
    cortado = limpio[:limite]
    espacio = cortado.rfind(" ")
    if espacio > limite // 2:
        cortado = cortado[:espacio]
    return cortado.rstrip(" ,;:.") + "…"


def _autores_legibles(autores: Any) -> str:
    if _es_nr(autores):
        return NR
    lista = autores if isinstance(autores, (list, tuple)) else [autores]
    limpios = [_texto(a) for a in lista if not _es_nr(a)]
    return "; ".join(limpios) or NR


def _enlace_doi(doi: Any) -> str:
    """El DOI como enlace, o ``NR``. No se inventa un DOI que no está."""
    limpio = _texto(doi, "")
    if not limpio:
        return NR
    return f"[{limpio}](https://doi.org/{limpio})"


def ficha_markdown(decision: Any, limite: int = LIMITE_RESUMEN) -> str:
    """La ficha de un artículo: todo lo que hace falta para decidir si se lee."""
    registro = decision.registro
    oa = _texto(registro.get("oa_url"), "")
    lineas = [
        f"### {decision.identificador} — {_texto(registro.get('titulo'))}",
        "",
        f"- **Año**: {_texto(registro.get('anio'))}",
        f"- **Idioma**: {_texto(registro.get('idioma'))}",
        f"- **Revista**: {_texto(registro.get('revista'))}",
        f"- **Autores**: {_autores_legibles(registro.get('autores'))}",
        f"- **DOI**: {_enlace_doi(registro.get('doi'))}",
        f"- **Clasificación**: {_texto(getattr(decision, 'clasificacion', NR))}",
        f"- **Decidido por**: {_texto(getattr(decision, 'decidido_por', NR))}",
        f"- **Texto completo**: "
        + (f"[acceso abierto]({oa})" if oa else "sin versión abierta localizada"),
        "",
        f"**Resumen**: {_recortar(registro.get('resumen'), limite)}",
        "",
    ]
    return "\n".join(lineas)


def _cabecera(titulo: str, revision: str, fecha: str, cuantos: int, que: str) -> list[str]:
    return [
        f"# {titulo}",
        "",
        f"- **Revisión**: {revision}",
        f"- **Generado**: {fecha}",
        f"- **{que}**: {cuantos}",
        "",
    ]


def incluidos_markdown(
    decisiones: Sequence[Any],
    revision: str = NR,
    fecha: str = "",
    limite: int = LIMITE_RESUMEN,
) -> str:
    """Una ficha por artículo incluido."""
    fecha = fecha or datetime.now().isoformat(timespec="seconds")
    lineas = _cabecera(
        "Registros incluidos", revision, fecha, len(decisiones), "Artículos"
    )
    if not decisiones:
        lineas.append(
            "Todavía no hay ningún registro incluido. Lanza «tatewari cribar» "
            "sobre una revisión cosechada."
        )
        return "\n".join(lineas) + "\n"

    for decision in decisiones:
        lineas.append(ficha_markdown(decision, limite))
    return "\n".join(lineas)


def revision_manual_markdown(
    dudosos: Sequence[Any],
    revision: str = NR,
    fecha: str = "",
    limite: int = LIMITE_RESUMEN,
) -> str:
    """Los dudosos, listos para resolver a mano.

    Cada uno lleva el motivo del filtro, de quién fue la decisión y la orden de
    `decidir` ya escrita: es la diferencia entre una lista y una lista de tareas.
    """
    fecha = fecha or datetime.now().isoformat(timespec="seconds")
    lineas = _cabecera(
        "Revisión manual: registros dudosos",
        revision,
        fecha,
        len(dudosos),
        "Pendientes",
    )
    lineas.extend(
        [
            "El cribado automático **propone, no decide** (AGENTS.md, regla 4).",
            "Estos registros no están descartados: esperan a una persona.",
            "",
            "Para resolver uno, copia la orden que va debajo de su ficha y cambia",
            "la decisión y el motivo:",
            "",
        ]
    )
    if not dudosos:
        lineas.append("No queda ningún registro dudoso. Nada que revisar a mano.")
        return "\n".join(lineas) + "\n"

    for decision in dudosos:
        registro = decision.registro
        lineas.append(
            f"### {decision.identificador} — {_texto(registro.get('titulo'))}"
        )
        lineas.append("")
        lineas.append(f"- **Año**: {_texto(registro.get('anio'))}")
        lineas.append(f"- **Revista**: {_texto(registro.get('revista'))}")
        lineas.append(f"- **DOI**: {_enlace_doi(registro.get('doi'))}")
        lineas.append(
            f"- **Lo decidió**: {_texto(getattr(decision, 'decidido_por', NR))}"
        )
        lineas.append(f"- **Motivo del filtro**: {_texto(decision.motivo_filtro or decision.motivo)}")
        if getattr(decision, "es_manual", False):
            lineas.append(f"- **Motivo registrado**: {_texto(decision.motivo)}")
        bloques = getattr(decision, "bloques_presentes", ())
        lineas.append(
            f"- **Bloques detectados**: {', '.join(bloques) if bloques else NR}"
        )
        lineas.append("")
        lineas.append(f"**Resumen**: {_recortar(registro.get('resumen'), limite)}")
        lineas.append("")
        lineas.append("```bash")
        lineas.append(
            f'python -m tatewari decidir {revision} {decision.identificador} '
            f'--decision incluir --motivo "escribe aquí por qué"'
        )
        lineas.append("```")
        lineas.append("")
    return "\n".join(lineas)


def por_conseguir_markdown(
    sin_abierto: Sequence[Any],
    revision: str = NR,
    fecha: str = "",
) -> str:
    """Los incluidos sin versión abierta, para pedirlos a la biblioteca."""
    fecha = fecha or datetime.now().isoformat(timespec="seconds")
    lineas = _cabecera(
        "Por conseguir: textos completos sin acceso abierto",
        revision,
        fecha,
        len(sin_abierto),
        "Artículos",
    )
    lineas.extend(
        [
            "## Cómo se consiguen estos textos",
            "",
            "**Tatewari no elude muros de pago.** No hay una orden que los abra,",
            "y no la va a haber: nada de Sci-Hub, nada de raspar la web de la",
            "editorial, nada de rodear el acceso (AGENTS.md, regla 5). Cuando no",
            "hay una versión legal en acceso abierto, el programa lo dice y se",
            "detiene ahí.",
            "",
            "Estos artículos se consiguen **a mano, uno por uno**, con la",
            "credencial institucional de tu biblioteca:",
            "",
            "1. Entra al portal de tu biblioteca con tu credencial.",
            "2. Busca el DOI en su buscador de recursos electrónicos.",
            "3. Si la institución no lo tiene suscrito, pídelo por préstamo",
            "   interbibliotecario: es gratuito en la mayoría de universidades y",
            "   suele tardar entre unas horas y unos días.",
            "4. Como último recurso, escribe a los autores y pídeles una copia.",
            "   Es legal, es habitual, y casi siempre contestan.",
            "",
            "Unpaywall ya se consultó para todos ellos: si tuvieran una versión",
            "abierta legal, estarían con su enlace en `incluidos.md` y no aquí.",
            "",
        ]
    )
    if not sin_abierto:
        lineas.append("## Lista")
        lineas.append("")
        lineas.append(
            "Ninguno: todos los registros incluidos tienen una versión en acceso "
            "abierto localizada. No hay nada que pedir a la biblioteca."
        )
        return "\n".join(lineas) + "\n"

    lineas.append("## Lista")
    lineas.append("")
    lineas.append("| Identificador | Año | DOI | Revista | Título |")
    lineas.append("|---|---|---|---|---|")
    for decision in sin_abierto:
        registro = decision.registro
        titulo = _texto(registro.get("titulo")).replace("|", "\\|")
        revista = _texto(registro.get("revista")).replace("|", "\\|")
        lineas.append(
            f"| {decision.identificador} | {_texto(registro.get('anio'))} "
            f"| {_texto(registro.get('doi'))} | {revista} | {titulo} |"
        )
    lineas.append("")
    lineas.append("### Los DOI, uno por línea, para pegarlos en el buscador")
    lineas.append("")
    lineas.append("```")
    for decision in sin_abierto:
        doi = _texto(decision.registro.get("doi"), "")
        lineas.append(doi if doi else f"(sin DOI: {decision.identificador})")
    lineas.append("```")
    lineas.append("")
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Escribir los cuatro archivos
# ---------------------------------------------------------------------------


@dataclass
class ResultadoExportacion:
    """Qué se exportó y a dónde."""

    revision: str
    incluidos: int = 0
    dudosos: int = 0
    sin_abierto: int = 0
    con_abierto: int = 0
    rutas: list[Path] = field(default_factory=list)

    def resumen(self) -> str:
        """Texto para la CLI."""
        lineas = [
            f"Revisión  : {self.revision}",
            f"Incluidos : {self.incluidos} "
            f"({self.con_abierto} con acceso abierto, "
            f"{self.sin_abierto} por conseguir)",
            f"Dudosos   : {self.dudosos} esperando una decisión humana",
            "",
            "Archivos escritos:",
        ]
        lineas.extend(f"  {ruta}" for ruta in self.rutas)
        return "\n".join(lineas)


def _tiene_abierto(decision: Any) -> bool:
    return not _es_nr(decision.registro.get("oa_url"))


def exportar(
    resultado: Any,
    carpeta: Path | str,
    revision: str = "",
    fecha: str = "",
    limite: int = LIMITE_RESUMEN,
) -> ResultadoExportacion:
    """Escribe los cuatro archivos de exportación en `carpeta`.

    `resultado` es un `ResultadoCribado`. Todo va en UTF-8 **sin** BOM y con
    saltos de línea LF: la única excepción del BOM que autoriza AGENTS.md es
    `search_log.csv`.
    """
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    revision = revision or getattr(resultado, "revision", NR)
    fecha = fecha or datetime.now().isoformat(timespec="seconds")

    incluidos = resultado.por_decision("incluir")
    dudosos = resultado.por_decision("dudoso")
    sin_abierto = [d for d in incluidos if not _tiene_abierto(d)]

    salida = ResultadoExportacion(
        revision=revision,
        incluidos=len(incluidos),
        dudosos=len(dudosos),
        sin_abierto=len(sin_abierto),
        con_abierto=len(incluidos) - len(sin_abierto),
    )

    archivos = (
        (NOMBRE_BIB, bibtex_de(incluidos, revision, fecha)),
        (NOMBRE_INCLUIDOS, incluidos_markdown(incluidos, revision, fecha, limite)),
        (
            NOMBRE_REVISION,
            revision_manual_markdown(dudosos, revision, fecha, limite),
        ),
        (NOMBRE_POR_CONSEGUIR, por_conseguir_markdown(sin_abierto, revision, fecha)),
    )

    for nombre, contenido in archivos:
        ruta = carpeta / nombre
        with open(ruta, "w", encoding="utf-8", newline="\n") as manejador:
            manejador.write(contenido)
            if not contenido.endswith("\n"):
                manejador.write("\n")
        salida.rutas.append(ruta)

    return salida
