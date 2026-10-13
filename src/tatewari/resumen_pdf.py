"""Resumen extractivo de un PDF: frases clave copiadas tal cual, con su página.

Sin un modelo de lenguaje no se puede escribir un resumen nuevo, y AGENTS.md
(regla 2) prohíbe inventar. Lo que sí se puede hacer, de forma determinista y
sin red, es **escoger** las frases que más importan y copiarlas tal cual, con la
página de donde salen para poder comprobarlas:

- **Conclusiones**: las primeras frases del apartado «Conclusion(s)» o
  «Conclusiones», que es donde los autores dicen qué encontraron.
- **Resultados con números**: frases que traen una cifra con unidad («4.1
  MPa», «7 %», «28 days») **y** algún término del protocolo de la revisión.
  En un artículo de bloques de tierra eso pesca justo «la resistencia llegó a
  4.1 MPa con 7 % de cemento y 3 % de cal».

Lo que no hace: interpretar, traducir ni juntar frases. Si el PDF es un escaneo
sin texto, lo dice y no sale nada.

Necesita PyMuPDF (``pip install -e ".[documentos]"``), la misma dependencia
opcional que usa Knowledge Studio para leer PDF.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .texto import contiene

__all__ = [
    "Frase",
    "ResumenPdf",
    "pdf_legible",
    "partir_frases",
    "resumir_paginas",
    "resumir_pdf",
]

MAX_CONCLUSIONES = 4
MAX_HALLAZGOS = 6
LARGO_MINIMO = 40
LARGO_MAXIMO = 450

#: Abreviaturas tras las que un punto no termina la frase.
_ABREVIATURAS = {
    "al", "fig", "figs", "eq", "eqs", "e.g", "i.e", "vs", "no", "ref", "refs",
    "approx", "ca", "etc", "sec", "tab", "p", "pp", "vol", "dr", "et", "cf",
}
_FIN_DE_FRASE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ(“\"\[])")
_GUION_DE_CORTE = re.compile(r"(\w)-\s*\n\s*(\w)")
_ESPACIOS = re.compile(r"\s+")

#: Cifra con unidad o porcentaje. Basta con que aparezca una.
_CIFRA_CON_UNIDAD = re.compile(
    r"\d+(?:[.,]\d+)?\s?(?:%|‰|MPa|GPa|kPa|N/mm2?|N/mm²|kN|kg/m3|kg/m³|kg|g/cm3|g/cm³|"
    r"mg/L|mg L|µg/L|μg/L|mm|cm|°C|º C|days?|días?|wt|h\b|min\b|nm\b|W/m)",
    re.IGNORECASE,
)
_TITULO_CONCLUSION = re.compile(
    r"(?:^|\n|\s)(?:\d+\.?\s*)?(CONCLUSIONS?|Conclusions?|CONCLUSIONES|Conclusiones|"
    r"CONCLUDING REMARKS|Concluding remarks)\b[\s:.]*"
)
#: Título de referencias: en mayúsculas basta («REFERENCE», «REFERENCES»); en
#: minúsculas tiene que ir solo en su línea, para no cortar en «see references».
_TITULO_REFERENCIAS = re.compile(
    r"\b(?:REFERENCES?|REFERENCIAS|BIBLIOGRAPHY|BIBLIOGRAF[IÍ]A|LITERATURE CITED)\b"
    r"|(?:^|\n)\s*(?:\d+\.?\s*)?(?:References|Referencias|Bibliography|Bibliografía|"
    r"Literature cited)\s*\n"
)
_TITULO_SIGUIENTE = re.compile(
    r"\n\s*(?:\d+\.?\s*)?(Acknowledg|ACKNOWLEDG|Agradecimientos|AGRADECIMIENTOS|"
    r"References|REFERENCES?\b|Referencias|REFERENCIAS|Funding|Declaration|Conflict|"
    r"Author contribution|CRediT|Data availability)"
)
#: Un título en mayúsculas pegado al principio de una frase («CONCLUSION AND
#: RECOMMENDATIONS Conclusion Having…»), que se quita antes de comparar.
_TITULO_PEGADO = re.compile(
    r"^(?:[A-ZÁÉÍÓÚÑ]{2,}[\s&,:]+)+(?:(?:Conclusions?|Conclusiones|Recommendations|"
    r"Aim and Objectives|Abstract|Resumen)\s+)?(?=[A-Z])"
)
#: Una frase completa acaba en puntuación; si no, la cortó una columna o una página.
_TERMINA_BIEN = re.compile(r"[.!?)\]”\"]$")

#: Símbolos fuera del alfabeto latino que sí son normales en un resultado.
_SIMBOLOS_PERMITIDOS = set("±°µμ×–—‐’‘“”…‰²³·≤≥≈∼~α-βγδΔθλρσφωΩ")

#: Palabras que delatan un resultado y no un método. Una frase que dice qué se
#: obtuvo pesa más que una que dice cómo se midió.
_PALABRAS_DE_RESULTADO = re.compile(
    r"\b(obtained|achieved|reached|increased|decreased|improved|reduced|highest|lowest|"
    r"maximum|minimum|optimum|optimal|showed|shows|resulted|exceed\w*|compared to|"
    r"higher than|lower than|obtuvo|obtuvieron|alcanz\w+|aument\w+|disminu\w+|"
    r"mayor|menor|m[aá]xim\w+|m[ií]nim\w+|[oó]ptim\w+)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Frase:
    texto: str
    pagina: int

    def cita(self) -> str:
        return f"{self.texto} (p. {self.pagina})"


@dataclass
class ResumenPdf:
    conclusiones: list[Frase] = field(default_factory=list)
    hallazgos: list[Frase] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def vacio(self) -> bool:
        return not self.conclusiones and not self.hallazgos


def pdf_legible() -> bool:
    """¿Está PyMuPDF instalado?"""
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        try:
            import fitz  # noqa: F401
        except ImportError:
            return False
    return True


def _limpiar(texto: str) -> str:
    """Une las palabras partidas por guion al final de línea y aplana espacios."""
    return _ESPACIOS.sub(" ", _GUION_DE_CORTE.sub(r"\1\2", texto)).strip()


def partir_frases(texto: str) -> list[str]:
    """Parte un texto en frases sin cortar en «et al.», «Fig.» ni decimales."""
    trozos = _FIN_DE_FRASE.split(_limpiar(texto))
    frases: list[str] = []
    for trozo in trozos:
        if frases:
            ultima_palabra = frases[-1].rstrip(".").rsplit(" ", 1)[-1].lower()
            if ultima_palabra in _ABREVIATURAS or len(ultima_palabra) == 1:
                frases[-1] = f"{frases[-1]} {trozo}"
                continue
        frases.append(trozo)
    return [f.strip() for f in frases if f.strip()]


def _parece_prosa(frase: str) -> bool:
    """Descarta restos de tablas, pies de página y frases cortadas por una columna."""
    if not LARGO_MINIMO <= len(frase) <= LARGO_MAXIMO:
        return False
    if not _TERMINA_BIEN.search(frase):
        return False
    raros = sum(1 for c in frase if ord(c) > 0x024F and c not in _SIMBOLOS_PERMITIDOS)
    if raros > 2:
        return False  # ecuaciones o texto mal extraído («𝐶𝑜𝑚𝑝𝑟𝑒𝑠𝑠𝑖𝑣𝑒»)
    letras = sum(c.isalpha() for c in frase)
    return letras / len(frase) > 0.6 and " " in frase


def _sin_titulo(frase: str) -> str:
    """Quita un título en mayúsculas pegado al principio de la frase."""
    limpia = _TITULO_PEGADO.sub("", frase).strip()
    return limpia if len(limpia) >= LARGO_MINIMO else frase


def _sin_referencias(paginas: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Corta el texto donde empiezan las referencias (de la mitad en adelante)."""
    mitad = len(paginas) // 2
    salida = []
    for indice, (numero, texto) in enumerate(paginas):
        if indice >= mitad:
            encontrado = _TITULO_REFERENCIAS.search(texto)
            if encontrado:
                salida.append((numero, texto[: encontrado.start()]))
                break
        salida.append((numero, texto))
    return salida


def _conclusiones(paginas: list[tuple[int, str]]) -> list[Frase]:
    """Las primeras frases tras el último título «Conclusion(s)»."""
    for indice in range(len(paginas) - 1, -1, -1):
        numero, texto = paginas[indice]
        coincidencias = list(_TITULO_CONCLUSION.finditer(texto))
        if not coincidencias:
            continue
        inicio = coincidencias[-1].end()
        tramo = [(numero, texto[inicio:])]
        if indice + 1 < len(paginas):
            tramo.append(paginas[indice + 1])
        frases: list[Frase] = []
        for numero_tramo, texto_tramo in tramo:
            corte = _TITULO_SIGUIENTE.search(texto_tramo)
            if corte:
                texto_tramo = texto_tramo[: corte.start()]
            for frase in partir_frases(texto_tramo):
                frase = _sin_titulo(frase)
                if _parece_prosa(frase):
                    frases.append(Frase(frase, numero_tramo))
                if len(frases) >= MAX_CONCLUSIONES:
                    return frases
            if corte:
                break
        return frases
    return []


def _hallazgos(
    paginas: list[tuple[int, str]], terminos: list[str], ya: set[str]
) -> list[Frase]:
    candidatas: list[tuple[int, int, Frase]] = []
    orden = 0
    for numero, texto in paginas:
        for frase in partir_frases(texto):
            orden += 1
            frase = _sin_titulo(frase)
            if any(frase in previa or previa in frase for previa in ya):
                continue
            if not _parece_prosa(frase):
                continue
            if not _CIFRA_CON_UNIDAD.search(frase):
                continue
            presentes = sum(1 for termino in terminos if contiene(frase, termino))
            if terminos and presentes == 0:
                continue
            puntos = presentes + (3 if _PALABRAS_DE_RESULTADO.search(frase) else 0)
            candidatas.append((puntos, orden, Frase(frase, numero)))
    mejores = sorted(candidatas, key=lambda c: (-c[0], c[1]))[:MAX_HALLAZGOS]
    return [frase for _, _, frase in sorted(mejores, key=lambda c: c[1])]


def resumir_paginas(
    paginas: Iterable[tuple[int, str]], terminos: Iterable[str] = ()
) -> ResumenPdf:
    """Resume páginas ya extraídas: (número de página, texto)."""
    lista = [(numero, texto or "") for numero, texto in paginas]
    resumen = ResumenPdf()
    if not any(texto.strip() for _, texto in lista):
        resumen.avisos.append("El PDF no trae texto (¿es un escaneo?): no hay frases que copiar.")
        return resumen
    cuerpo = _sin_referencias(lista)
    resumen.conclusiones = _conclusiones(cuerpo)
    ya = {frase.texto for frase in resumen.conclusiones}
    resumen.hallazgos = _hallazgos(cuerpo, list(dict.fromkeys(terminos)), ya)
    return resumen


def resumir_pdf(ruta: Path | str, terminos: Iterable[str] = ()) -> ResumenPdf:
    """Lee el PDF con PyMuPDF y lo resume. Nunca lanza por un PDF roto."""
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
        except ImportError:
            return ResumenPdf(
                avisos=['Falta PyMuPDF para leer PDF: pip install -e ".[documentos]"']
            )
    try:
        with pymupdf.open(str(ruta)) as documento:
            paginas = [(i + 1, pagina.get_text()) for i, pagina in enumerate(documento)]
    except Exception as error:  # un PDF dañado no puede tumbar la exportación
        return ResumenPdf(avisos=[f"No se pudo leer el PDF: {type(error).__name__}"])
    return resumir_paginas(paginas, terminos)
