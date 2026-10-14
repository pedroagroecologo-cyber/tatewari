"""Citas y lista de referencias en el estilo que pida tu programa.

Cada programa, revista o tutor pide un estilo distinto. Este módulo arma la cita
de cada registro en siete estilos de uso común:

==========  ==============================================  ===============
Clave       Estilo                                          Orden de la lista
==========  ==============================================  ===============
apa         APA 7.ª edición                                 alfabético
vancouver   Vancouver (ICMJE / NLM)                         numerado
ieee        IEEE                                            numerado
chicago     Chicago 17.ª, autor-fecha                       alfabético
harvard     Harvard (Cite Them Right)                       alfabético
mla         MLA 9.ª edición                                 alfabético
iso690      ISO 690 / UNE-ISO 690 (en español)              alfabético
==========  ==============================================  ===============

Se elige con ``TATEWARI_ESTILO_CITA`` en el ``.env`` (por defecto ``apa``) o con
``tatewari exportar REVISIÓN --estilo vancouver``.

Lo que no hace, y por qué
-------------------------

- **No inventa datos** (AGENTS.md, regla 2): si falta el volumen, el número o
  las páginas, la cita sale sin ellos; no se rellenan con nada. Los registros
  cosechados antes de que Tatewari guardara esos tres campos no los tienen.
- **No cambia las mayúsculas del título.** APA pide «tipo oración» y otros
  estilos «tipo título»; convertir a ciegas rompe nombres propios y siglas
  («Portland cement», «CSEB»). Se deja como lo publicó la revista.
- **El apellido se adivina**: OpenAlex da el nombre completo («Peter Olugbenga
  Omotainse») y no separa nombre de apellido. Se toma la última palabra, junto
  con partículas como «de», «van» o «da». En artículos en español, un nombre
  de cuatro palabras o más se toma con dos apellidos. Aun así hay casos que
  salen mal y hay que revisar: para la tesis, lo más seguro es importar
  ``incluidos.bib`` en Zotero y comprobar ahí cada autor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .fuentes import NR

__all__ = [
    "ESTILOS",
    "ESTILO_POR_DEFECTO",
    "NUMERADOS",
    "Autor",
    "autores_de",
    "citar",
    "lista_de_referencias",
]

ESTILOS: dict[str, str] = {
    "apa": "APA 7",
    "vancouver": "Vancouver",
    "ieee": "IEEE",
    "chicago": "Chicago autor-fecha",
    "harvard": "Harvard",
    "mla": "MLA 9",
    "iso690": "ISO 690",
}
ESTILO_POR_DEFECTO = "apa"
#: Estilos cuya lista va numerada en orden de aparición, no alfabética.
NUMERADOS = ("vancouver", "ieee")

_PARTICULAS = {"de", "del", "la", "las", "los", "van", "von", "der", "den", "da", "das", "do", "dos", "di", "du", "le", "y"}


@dataclass(frozen=True)
class Autor:
    nombres: tuple[str, ...]
    apellido: str

    def iniciales(self, separador: str = " ", punto: bool = True) -> str:
        """«S. N.» (APA), «SN» (Vancouver), «S.N.» (Harvard)."""
        letras = []
        for nombre in self.nombres:
            for parte in nombre.replace("-", " ").replace(".", " ").split():
                if parte[:1].isalpha():
                    letras.append(parte[0].upper())
        sufijo = "." if punto else ""
        return separador.join(f"{letra}{sufijo}" for letra in letras)

    @property
    def nombre_completo(self) -> str:
        return " ".join((*self.nombres, self.apellido)).strip()


def _lista(autores: Any) -> list[str]:
    if isinstance(autores, (list, tuple)):
        crudos = list(autores)
    elif isinstance(autores, str):
        texto = autores.strip()
        if texto in ("", NR):
            return []
        if texto.startswith("["):
            try:
                crudos = json.loads(texto.replace("'", '"'))
            except ValueError:
                crudos = texto.strip("[]").split(",")
        else:
            crudos = texto.split(";")
    else:
        return []
    limpios = [" ".join(str(a).strip().strip("'\"").split()) for a in crudos]
    return [a for a in limpios if a and a != NR]


def autores_de(registro: Mapping[str, Any]) -> list[Autor]:
    """Separa nombre y apellido de cada autor (ver las limitaciones arriba).

    En un registro en español, un nombre de cuatro palabras o más se toma con
    dos apellidos («José Luis García López» → García López, J. L.). Con tres
    palabras no se puede saber («Juan García López» frente a «José Luis
    García») y se toma uno solo.
    """
    en_espanol = str(registro.get("idioma") or "").lower().startswith("es")
    salida = []
    for nombre in _lista(registro.get("autores")):
        if "," in nombre:  # «Apellido, Nombre», como lo escribe Crossref a veces
            apellido, _, nombres = nombre.partition(",")
            salida.append(Autor(tuple(nombres.split()), apellido.strip()))
            continue
        partes = nombre.split()
        if len(partes) == 1:
            salida.append(Autor((), partes[0]))
            continue
        inicio = len(partes) - 1
        if en_espanol and len(partes) >= 4:
            inicio = len(partes) - 2
        while inicio > 1 and partes[inicio - 1].lower() in _PARTICULAS:
            inicio -= 1
        salida.append(Autor(tuple(partes[:inicio]), " ".join(partes[inicio:])))
    return salida


def _dato(registro: Mapping[str, Any], campo: str) -> str:
    valor = registro.get(campo)
    if valor is None:
        return ""
    texto = " ".join(str(valor).split())
    return "" if texto in ("", NR) else texto


def _titulo(registro: Mapping[str, Any]) -> str:
    return _dato(registro, "titulo").rstrip(". ")


def _doi(registro: Mapping[str, Any]) -> str:
    return _dato(registro, "doi")


def _enlace(registro: Mapping[str, Any]) -> str:
    doi = _doi(registro)
    return f"https://doi.org/{doi}" if doi else ""


def _es_rango(paginas: str) -> bool:
    return "–" in paginas or "-" in paginas


def _unir(nombres: list[str], conector: str, coma_final: bool = True) -> str:
    """«A, B, & C» o «A, B and C», según el estilo."""
    if not nombres:
        return ""
    if len(nombres) == 1:
        return nombres[0]
    if len(nombres) == 2:
        return f"{nombres[0]}{',' if coma_final and conector == '&' else ''} {conector} {nombres[1]}"
    separador = "," if coma_final else ""
    return f"{', '.join(nombres[:-1])}{separador} {conector} {nombres[-1]}"


# ---------------------------------------------------------------------------
# Un estilo por función
# ---------------------------------------------------------------------------


def _apa(r: Mapping[str, Any], autores: list[Autor]) -> str:
    nombres = [f"{a.apellido}, {a.iniciales()}".rstrip(", ") for a in autores]
    if len(nombres) > 20:
        nombres = nombres[:19] + ["…"] + nombres[-1:]
        quien = ", ".join(nombres[:-2]) + ", … " + nombres[-1]
    else:
        quien = _unir(nombres, "&")
    anio = _dato(r, "anio") or "s. f."
    partes = [f"{quien} ({anio}). {_titulo(r)}." if quien else f"{_titulo(r)}. ({anio})."]
    revista = _dato(r, "revista")
    if revista:
        fuente = f"*{revista}*"
        volumen, numero, paginas = _dato(r, "volumen"), _dato(r, "numero"), _dato(r, "paginas")
        if volumen:
            fuente += f", *{volumen}*" + (f"({numero})" if numero else "")
        if paginas:
            fuente += f", {paginas}"
        partes.append(fuente + ".")
    if _enlace(r):
        partes.append(_enlace(r))
    return " ".join(partes)


def _vancouver(r: Mapping[str, Any], autores: list[Autor]) -> str:
    nombres = [f"{a.apellido} {a.iniciales('', False)}".strip() for a in autores]
    quien = ", ".join(nombres[:6]) + (", et al" if len(nombres) > 6 else "")
    partes = [f"{quien}." if quien else "", f"{_titulo(r)}."]
    revista = _dato(r, "revista")
    detalle = _dato(r, "anio")
    volumen, numero, paginas = _dato(r, "volumen"), _dato(r, "numero"), _dato(r, "paginas")
    if volumen:
        detalle += f";{volumen}" + (f"({numero})" if numero else "")
    if paginas:
        detalle += f":{paginas}"
    if revista:
        partes.append(f"{revista}. {detalle}." if detalle else f"{revista}.")
    elif detalle:
        partes.append(f"{detalle}.")
    if _doi(r):
        partes.append(f"doi:{_doi(r)}")
    return " ".join(p for p in partes if p)


def _ieee(r: Mapping[str, Any], autores: list[Autor]) -> str:
    nombres = [f"{a.iniciales()} {a.apellido}".strip() for a in autores]
    if len(nombres) > 6:
        quien = f"{nombres[0]} et al."
    else:
        quien = _unir(nombres, "and")
    trozos = []
    if _dato(r, "revista"):
        trozos.append(f"*{_dato(r, 'revista')}*")
    if _dato(r, "volumen"):
        trozos.append(f"vol. {_dato(r, 'volumen')}")
    if _dato(r, "numero"):
        trozos.append(f"no. {_dato(r, 'numero')}")
    paginas = _dato(r, "paginas")
    if paginas:
        trozos.append(("pp. " if _es_rango(paginas) else "p. ") + paginas)
    if _dato(r, "anio"):
        trozos.append(_dato(r, "anio"))
    if _doi(r):
        trozos.append(f"doi: {_doi(r)}")
    cuerpo = f"“{_titulo(r)},” " + ", ".join(trozos) + "."
    return f"{quien}, {cuerpo}" if quien else cuerpo


def _chicago(r: Mapping[str, Any], autores: list[Autor]) -> str:
    nombres = []
    for indice, autor in enumerate(autores):
        if indice == 0:
            nombres.append(f"{autor.apellido}, {' '.join(autor.nombres)}".rstrip(", "))
        else:
            nombres.append(autor.nombre_completo)
    if len(nombres) > 10:
        quien = ", ".join(nombres[:7]) + ", et al"
    else:
        quien = _unir(nombres, "and")
    anio = _dato(r, "anio") or "s. f."
    partes = [f"{quien}. {anio}." if quien else f"{anio}.", f"“{_titulo(r)}.”"]
    revista = _dato(r, "revista")
    if revista:
        fuente = f"*{revista}*"
        if _dato(r, "volumen"):
            fuente += f" {_dato(r, 'volumen')}"
        if _dato(r, "numero"):
            fuente += f" ({_dato(r, 'numero')})"
        if _dato(r, "paginas"):
            fuente += f": {_dato(r, 'paginas')}"
        partes.append(fuente + ".")
    if _enlace(r):
        partes.append(_enlace(r) + ".")
    return " ".join(partes)


def _harvard(r: Mapping[str, Any], autores: list[Autor]) -> str:
    nombres = [f"{a.apellido}, {a.iniciales('')}".rstrip(", ") for a in autores]
    if len(nombres) >= 4:
        quien = f"{nombres[0]} et al."
    else:
        quien = _unir(nombres, "and", coma_final=False)
    anio = _dato(r, "anio") or "s. f."
    trozos = [f"{quien} ({anio}) ‘{_titulo(r)}’" if quien else f"‘{_titulo(r)}’ ({anio})"]
    if _dato(r, "revista"):
        trozos.append(f"*{_dato(r, 'revista')}*")
    volumen, numero = _dato(r, "volumen"), _dato(r, "numero")
    if volumen:
        trozos.append(volumen + (f"({numero})" if numero else ""))
    paginas = _dato(r, "paginas")
    if paginas:
        trozos.append(("pp. " if _es_rango(paginas) else "p. ") + paginas)
    texto = ", ".join(trozos) + "."
    if _doi(r):
        texto += f" doi: {_doi(r)}."
    return texto


def _mla(r: Mapping[str, Any], autores: list[Autor]) -> str:
    if not autores:
        quien = ""
    elif len(autores) == 1:
        quien = f"{autores[0].apellido}, {' '.join(autores[0].nombres)}".rstrip(", ")
    elif len(autores) == 2:
        primero = f"{autores[0].apellido}, {' '.join(autores[0].nombres)}".rstrip(", ")
        quien = f"{primero}, and {autores[1].nombre_completo}"
    else:
        quien = f"{autores[0].apellido}, {' '.join(autores[0].nombres)}".rstrip(", ") + ", et al"
    trozos = []
    if _dato(r, "revista"):
        trozos.append(f"*{_dato(r, 'revista')}*")
    if _dato(r, "volumen"):
        trozos.append(f"vol. {_dato(r, 'volumen')}")
    if _dato(r, "numero"):
        trozos.append(f"no. {_dato(r, 'numero')}")
    if _dato(r, "anio"):
        trozos.append(_dato(r, "anio"))
    paginas = _dato(r, "paginas")
    if paginas:
        trozos.append(("pp. " if _es_rango(paginas) else "p. ") + paginas)
    if _enlace(r):
        trozos.append(_enlace(r))
    inicio = f"{quien}. " if quien else ""
    return f"{inicio}“{_titulo(r)}.” " + ", ".join(trozos) + "."


def _iso690(r: Mapping[str, Any], autores: list[Autor]) -> str:
    nombres = [f"{a.apellido.upper()}, {a.iniciales()}".rstrip(", ") for a in autores]
    if len(nombres) > 3:
        quien = f"{nombres[0]} et al."
    else:
        quien = _unir(nombres, "y", coma_final=False)
    partes = [f"{quien}." if quien and not quien.endswith(".") else quien, f"{_titulo(r)}."]
    if _dato(r, "revista"):
        partes.append(f"*{_dato(r, 'revista')}*.")
    trozos = []
    if _dato(r, "anio"):
        trozos.append(_dato(r, "anio"))
    if _dato(r, "volumen"):
        trozos.append(f"vol. {_dato(r, 'volumen')}")
    if _dato(r, "numero"):
        trozos.append(f"n.º {_dato(r, 'numero')}")
    paginas = _dato(r, "paginas")
    if paginas:
        trozos.append(f"pp. {paginas}" if _es_rango(paginas) else f"p. {paginas}")
    if trozos:
        partes.append(", ".join(trozos) + ".")
    if _doi(r):
        partes.append(f"DOI {_doi(r)}.")
    return " ".join(p for p in partes if p)


_FORMATEADORES = {
    "apa": _apa,
    "vancouver": _vancouver,
    "ieee": _ieee,
    "chicago": _chicago,
    "harvard": _harvard,
    "mla": _mla,
    "iso690": _iso690,
}


def normalizar_estilo(estilo: str) -> str:
    """Acepta «APA», «iso 690», «ISO-690»…; lanza ValueError si no existe."""
    clave = "".join(c for c in str(estilo).lower() if c.isalnum())
    if clave not in _FORMATEADORES:
        opciones = ", ".join(ESTILOS)
        raise ValueError(f"Estilo de cita desconocido: {estilo!r}. Los disponibles son: {opciones}.")
    return clave


def citar(registro: Mapping[str, Any], estilo: str = ESTILO_POR_DEFECTO) -> str:
    """La referencia de un registro en `estilo`, en Markdown (cursivas con *)."""
    clave = normalizar_estilo(estilo)
    return _FORMATEADORES[clave](registro, autores_de(registro)).strip()


def _clave_alfabetica(registro: Mapping[str, Any]) -> tuple[str, str, str]:
    autores = autores_de(registro)
    primero = autores[0].apellido.lower() if autores else _titulo(registro).lower()
    return (primero, _dato(registro, "anio"), _titulo(registro).lower())


def lista_de_referencias(
    registros: Iterable[Mapping[str, Any]], estilo: str = ESTILO_POR_DEFECTO
) -> list[str]:
    """Las referencias ordenadas como pide el estilo.

    Los numerados (Vancouver, IEEE) van en el orden recibido, con su número; los
    demás, por apellido del primer autor y año.
    """
    clave = normalizar_estilo(estilo)
    lista = list(registros)
    if clave in NUMERADOS:
        return [
            (f"[{n}] " if clave == "ieee" else f"{n}. ") + citar(r, clave)
            for n, r in enumerate(lista, start=1)
        ]
    return [citar(r, clave) for r in sorted(lista, key=_clave_alfabetica)]
