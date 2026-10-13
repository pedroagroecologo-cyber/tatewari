"""Normalización de texto y detección de términos del protocolo.

Este módulo existe por un error concreto, y conviene tenerlo escrito antes de
leer el código.

El fallo del acento
-------------------

Los términos de un protocolo se escriben a mano y a veces van sin acento:
``"remocion"``, ``"nitrogeno"``, ``"tanque septico"``. Si el texto del registro
solo se pasa a minúsculas, un resumen en español perfectamente escrito que diga
«remoción» **nunca** coincide con el término «remocion»: son dos cadenas
distintas. El cribado se queda mudo, no falla, no avisa, y el registro acaba
excluido por no cumplir ninguna regla.

La cura es normalizar **los dos lados** —el término y el texto— con la misma
función antes de comparar. Eso es `normalizar`, y es la única puerta por la que
pasa cualquier comparación de este proyecto.

Qué hace `normalizar`
---------------------

1. Pasa a minúsculas con ``casefold``.
2. Descompone en NFD y **descarta los diacríticos combinantes**, así que
   «remoción» y «remocion» acaban siendo la misma cadena. Ojo con la
   consecuencia, que es deliberada: la ``ñ`` se descompone en ``n`` más tilde
   combinante, así que «desempeño» queda «desempeno». Como el término del
   protocolo pasa por la misma función, «desempeño» sigue encontrando
   «desempeño»; y además «desempeno» también lo encuentra, que es justo lo que
   se quiere.
3. Unifica los guiones tipográficos en un guion normal y los espacios raros
   (incluido el no separable) en un espacio, colapsando los repetidos. Un
   título copiado de un PDF viene lleno de ellos.

Por qué no basta con `in`
-------------------------

Buscar el término como subcadena suelta da falsos positivos silenciosos:

- ``"pH"`` aparece dentro de *phosphorus*, *pathogens* y *morphology*.
- ``"LCA"`` aparece dentro de *alcalinidad*.

Así que un término se busca **como palabra completa**: la expresión regular
lleva límites de palabra a los dos lados. Dentro del término, cualquier espacio
admite varios, de modo que «tanque  séptico» coincide con «tanque séptico».

El plural, en los dos sentidos
------------------------------

Cada palabra del término admite una **s** o **es** de más, así que el
término «treatment wetland» encuentra «treatment wetlands» y «remoción»
encuentra «remociones». Hace falta: un protocolo escrito a mano lista unas veces
el singular y otras el plural, y un artículo titulado *Treatment wetlands for…*
no puede quedarse fuera de la revisión por una letra.

Y al revés: un término escrito en plural también encuentra el singular
(«compressed earth blocks» encuentra *Compressed Earth Block as a…*). Al principio
la tolerancia iba en un solo sentido y se confiaba en que el protocolo listara
las dos formas; un protocolo escrito por un chat gratuito puso solo el plural y
dejó fuera doce artículos con el singular en el título. Ahora cada palabra se
reduce a sus singulares probables con reglas cortas (``_singulares``). Va en
cada palabra y no solo en la última porque en español el plural concuerda:
«suelos arcillosos» tiene que encontrar «suelo arcilloso».

- quitar la **s** final («blocks» → «block», «suelos» → «suelo»), salvo en
  ``-ss``, ``-us`` e ``-is`` («process», «humus», «analysis»);
- quitar **es** tras ``s``, ``x``, ``z``, ``ch`` o ``sh`` («processes»,
  «boxes»), o tras ``l``, ``r``, ``n`` o ``d`` si queda una raíz de cinco letras
  o más («remociones» → «remocion», «totales» → «total»). El mínimo de cinco
  evita «tones» → «ton» o «lines» → «lin»;
- ``-ies`` pasa a ``-y`` («studies» → «study»), y un término en ``-y`` encuentra
  su ``-ies``.

Sigue sin ser un lematizador: no conoce plurales irregulares («analyses»,
«media»). Si una forma así importa, se escribe en el protocolo.

El guion
--------

«cement-stabilized» y «cement stabilized» son la misma frase escrita de dos
maneras, y los autores usan las dos. Dentro de un término, el guion y el espacio
se tratan igual: cualquiera de los dos encuentra al otro.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Iterable, Mapping

__all__ = [
    "NR",
    "SEPARADOR_DE_CAMPOS",
    "normalizar",
    "clave_alfanumerica",
    "expresion_de_termino",
    "contiene",
    "terminos_presentes",
    "nombres_presentes",
    "texto_buscable",
]

#: Marcador de dato no reportado (AGENTS.md, regla 2). Se repite aquí para que
#: este módulo no dependa de nada del proyecto y se pueda probar suelto.
NR = "NR"

#: Lo que `texto_buscable` mete entre el título y el resumen. Ni espacio (lo
#: saltaría la expresión del término) ni letra o número (estorbaría a los
#: términos pegados a él). El porqué, en `texto_buscable`.
SEPARADOR_DE_CAMPOS = " ¶ "

_ESPACIOS = re.compile(r"\s+")
_NO_ALFANUMERICO = re.compile(r"[^0-9a-z]+")

#: Guiones tipográficos que hay que unificar antes de comparar.
_GUIONES = {
    "‐": "-",  # guion
    "‑": "-",  # guion no separable
    "‒": "-",  # guion de cifras
    "–": "-",  # guion corto
    "—": "-",  # guion largo
    "―": "-",  # barra horizontal
    "−": "-",  # signo menos
}

#: Espacios que conviene igualar a uno normal.
_ESPACIOS_RAROS = {
    " ": " ",  # espacio no separable
    " ": " ",  # espacio fino no separable
    " ": " ",  # espacio de cifra
}

_TRADUCCION = str.maketrans({**_GUIONES, **_ESPACIOS_RAROS})

#: Expresión que no coincide con nada, para un término que se queda en vacío.
_NUNCA = re.compile(r"(?!)")

#: Plural admitido al final del término: la `s` del inglés y del español
#: («wetlands», «efluentes») y la `es` de las palabras españolas que acaban en
#: consonante («totales», «remociones»).
_PLURAL = r"(?:e?s)?"

#: Separador entre las palabras de un término: espacios o guiones, en cualquier
#: cantidad. Es lo que hace que «cement-stabilized» y «cement stabilized» sean
#: la misma frase.
_SEPARADOR = r"[\s\-]+"
_PARTES = re.compile(_SEPARADOR)

#: Terminaciones tras las que ``es`` es plural en inglés («processes», «boxes»).
_ANTES_DE_ES_INGLES = ("s", "x", "z", "ch", "sh")
#: Consonantes tras las que ``es`` es plural en español («totales», «remociones»).
_ANTES_DE_ES_ESPANOL = ("l", "r", "n", "d")
#: Raíz mínima para quitar ``es`` tras una de esas consonantes.
_RAIZ_MINIMA = 5
_VOCALES = "aeiou"


def _singulares(palabra: str) -> tuple[str, ...]:
    """Formas de `palabra` sin su plural probable, empezando por ella misma.

    Las reglas están explicadas en la cabecera del módulo. La palabra tal cual
    va siempre primero, así que un término en singular se comporta igual que
    antes.
    """
    formas = [palabra]
    if len(palabra) > 4 and palabra.endswith("ies"):
        formas.append(palabra[:-3] + "y")
    if len(palabra) > 3 and palabra.endswith("es"):
        raiz = palabra[:-2]
        if raiz.endswith(_ANTES_DE_ES_INGLES) or (
            raiz.endswith(_ANTES_DE_ES_ESPANOL) and len(raiz) >= _RAIZ_MINIMA
        ):
            formas.append(raiz)
    if (
        len(palabra) > 3
        and palabra.endswith("s")
        and not palabra.endswith(("ss", "us", "is"))
    ):
        formas.append(palabra[:-1])
    for forma in list(formas):
        if len(forma) > 2 and forma.endswith("y") and forma[-2] not in _VOCALES:
            formas.append(forma[:-1] + "ies")
    return tuple(dict.fromkeys(formas))


def normalizar(texto: object) -> str:
    """Devuelve `texto` en minúsculas, sin acentos y con los espacios limpios.

    Es la función que tienen que atravesar **los dos lados** de cualquier
    comparación: el término del protocolo y el texto del registro. El porqué
    está en la cabecera del módulo.

    Acepta cualquier cosa para no obligar a quien llama a comprobar tipos: un
    `None` o un número se convierten a texto primero. Nunca devuelve `None`.
    """
    if texto is None:
        return ""
    if not isinstance(texto, str):
        texto = str(texto)

    plano = texto.translate(_TRADUCCION).casefold()
    descompuesto = unicodedata.normalize("NFD", plano)
    sin_diacriticos = "".join(
        caracter for caracter in descompuesto if not unicodedata.combining(caracter)
    )
    return _ESPACIOS.sub(" ", sin_diacriticos).strip()


def clave_alfanumerica(texto: object) -> str:
    """Reduce `texto` a letras y números, sin acentos ni espacios.

    Sirve para comparar títulos: «Tanque séptico — caracterización» y «Tanque
    septico - caracterizacion» dan la misma clave. Se usa en la deduplicación
    cuando no hay DOI.
    """
    return _NO_ALFANUMERICO.sub("", normalizar(texto))


@lru_cache(maxsize=4096)
def expresion_de_termino(termino: str) -> re.Pattern[str]:
    """Compila un término del protocolo como búsqueda de palabra completa.

    El término se normaliza, se escapa entero (el punto de «E. coli» es un
    punto, no un comodín) y entre sus palabras se admiten espacios o guiones.
    Los límites de palabra son lo que evita que «pH» coincida dentro de
    *phosphorus*, y cada palabra admite el plural en los dos sentidos.

    Los resultados se memorizan: el protocolo tiene cientos de términos y se
    buscan contra miles de registros.
    """
    palabras = [parte for parte in _PARTES.split(normalizar(termino)) if parte]
    if not palabras:
        return _NUNCA
    cuerpo = _SEPARADOR.join(_expresion_de_palabra(palabra) for palabra in palabras)
    return re.compile(r"(?<!\w)" + cuerpo + r"(?!\w)")


def _expresion_de_palabra(palabra: str) -> str:
    """Una palabra del término con su singular y su plural admitidos."""
    formas = sorted(_singulares(palabra), key=len, reverse=True)
    return "(?:" + "|".join(re.escape(forma) for forma in formas) + ")" + _PLURAL


def contiene(texto: object, termino: str) -> bool:
    """¿Aparece `termino` como palabra completa en `texto`?

    Normaliza los dos lados, así que da igual que uno lleve acentos y el otro
    no.
    """
    return expresion_de_termino(termino).search(normalizar(texto)) is not None


def terminos_presentes(texto: object, terminos: Iterable[str]) -> tuple[str, ...]:
    """Devuelve, en el orden del protocolo, los términos que aparecen en `texto`.

    Los términos se devuelven **tal como los escribió el protocolo**, con sus
    acentos y mayúsculas: el motivo de una decisión se lee mejor citando la
    palabra del protocolo que su versión aplastada.
    """
    normalizado = normalizar(texto)
    return tuple(
        termino
        for termino in terminos
        if expresion_de_termino(termino).search(normalizado) is not None
    )


def nombres_presentes(
    mapa: Mapping[str, Iterable[str]], texto: object
) -> dict[str, tuple[str, ...]]:
    """Detecta qué bloques o grupos aparecen en `texto`.

    `mapa` va de nombre a lista de términos, que es la forma de ``bloques`` y de
    ``grupos`` del protocolo. Devuelve solo los nombres con al menos un término
    encontrado, cada uno con los términos concretos que lo dispararon: eso es lo
    que permite auditar una decisión sin volver a leer el resumen.

    Recibe un diccionario y no un `Protocolo` a propósito, para que este módulo
    no dependa de nada del proyecto.
    """
    normalizado = normalizar(texto)
    encontrados: dict[str, tuple[str, ...]] = {}
    for nombre, terminos in mapa.items():
        hallados = tuple(
            termino
            for termino in terminos
            if expresion_de_termino(termino).search(normalizado) is not None
        )
        if hallados:
            encontrados[nombre] = hallados
    return encontrados


def texto_buscable(*partes: object) -> str:
    """Junta los trozos de un registro en el texto contra el que se criba.

    Descarta los ``"NR"``: un campo no reportado no aporta texto, y buscar
    términos dentro de la cadena literal «NR» solo puede dar sorpresas.

    Los trozos se unen con `SEPARADOR_DE_CAMPOS`, que **no es un espacio** a
    propósito. Si se unieran con un espacio o con un salto de línea —que
    `normalizar` convierte en espacio—, un término podría cruzar la frontera
    entre el final del título y el principio del resumen: un título que acaba en
    «…tratamiento de agua» seguido de un resumen que empieza por «residual
    doméstica…» daría por encontrado «agua residual», que no está en ninguno de
    los dos. Como el separador no es un espacio, la expresión del término no
    puede saltarlo; y como tampoco es una letra ni un número, no estorba a los
    términos que empiezan o acaban pegados a él.
    """
    trozos: list[str] = []
    for parte in partes:
        if parte is None:
            continue
        texto = parte if isinstance(parte, str) else str(parte)
        limpio = texto.strip()
        if not limpio or limpio == NR:
            continue
        trozos.append(limpio)
    return SEPARADOR_DE_CAMPOS.join(trozos)
