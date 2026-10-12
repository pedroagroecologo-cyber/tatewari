"""Divulgación científica: de conceptos aprobados a un borrador narrativo.

Entra conocimiento **aprobado** y sale un borrador con tres partes, cada una en su
carpeta del Vault:

- ``05_GUION``: capítulos y escenas con narración, personajes, diálogos,
  afirmaciones científicas con su base y recuadros científicos.
- ``06_STORYBOARD``: las viñetas de cada escena.
- ``08_ILUSTRACIONES``: la especificación de cada ilustración (qué muestra, con
  qué elementos, apoyada en qué conceptos), sin generar ninguna imagen.

El modelo de síntesis recibe **solo** las definiciones y los detalles
comprobados contra su fuente de cada concepto aprobado, y la instrucción de no
añadir hechos. No basta con pedírselo: el borrador pasa después por
`validacion.validar_borrador`, que comprueba cada afirmación, cada recuadro y
cada cifra contra la base aprobada. Lo que no tenga respaldo queda marcado en el
propio borrador.

El borrador nace siempre en ``DRAFT`` y dice en su cabecera que no es fuente
científica.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..conocimiento.enrutador import Enrutador
from ..conocimiento.habilidades import registrar
from ..conocimiento.markdown import escribir_frontmatter
from ..conocimiento.objetos import ErrorEsquema, ahora, clave_de_nombre
from ..conocimiento.rutas import Jaula, nombre_de_nota, primera_ruta_libre
from ..conocimiento.vault import Nota, Vault
from ..cribado_modelo import extraer_json_si
from .validacion import ValidacionNarrativa, notas_aprobadas, validar_borrador

__all__ = [
    "ErrorDivulgacion",
    "Borrador",
    "ResultadoDivulgacion",
    "seleccionar_base",
    "construir_prompt",
    "validar_respuesta_narrativa",
    "render_guion",
    "render_storyboard",
    "render_ilustraciones",
    "generar_borrador",
    "MAXIMO_CONCEPTOS",
]

#: Conceptos por borrador. Más no caben con holgura en el contexto de un 4B.
MAXIMO_CONCEPTOS = 10

_LARGO_DEFINICION = 500


class ErrorDivulgacion(Exception):
    """No se puede generar el borrador. El mensaje dice qué hacer."""


# ---------------------------------------------------------------------------
# La base: solo lo aprobado
# ---------------------------------------------------------------------------


def seleccionar_base(
    vault: Vault, tema: str = "", nombres: Sequence[str] = ()
) -> tuple[list[Nota], list[str]]:
    """Las notas aprobadas que sostienen el borrador, y avisos de lo descartado.

    Con `nombres`, esas notas (las que no estén aprobadas se descartan con aviso).
    Con `tema`, las aprobadas que más lo mencionan. Sin nada, todas las aprobadas.
    """
    aprobadas = notas_aprobadas(vault)
    avisos: list[str] = []
    if nombres:
        base = []
        for nombre in nombres:
            nota = aprobadas.get(nombre.casefold()) or vault.buscar(nombre)
            if nota is None:
                avisos.append(f"«{nombre}» no existe en el Vault: se descarta.")
            elif nota.nombre.casefold() not in aprobadas:
                avisos.append(
                    f"[[{nota.nombre}]] está en {nota.estado}: solo se usa conocimiento "
                    f"APPROVED o PUBLISHED."
                )
            else:
                base.append(nota)
    elif tema:
        relevantes = [n for n, _ in vault.buscar_texto(tema, limite=50) if n.nombre.casefold() in aprobadas]
        base = relevantes or list(aprobadas.values())
        if not relevantes:
            avisos.append(f"Ninguna nota aprobada menciona «{tema}»: se usa toda la base aprobada.")
    else:
        base = list(aprobadas.values())

    if len(base) > MAXIMO_CONCEPTOS:
        avisos.append(
            f"Hay {len(base)} conceptos aprobados; se usan los {MAXIMO_CONCEPTOS} más "
            f"relevantes para que quepan en el contexto del modelo."
        )
        base = base[:MAXIMO_CONCEPTOS]
    return base, avisos


def _ficha(nota: Nota) -> str:
    """Lo que el modelo puede usar de un concepto: solo lo comprobado en su fuente."""
    objeto = nota.objeto()
    lineas = [f"### {nota.nombre}"]
    if objeto is None:
        texto = " ".join(nota.texto_plano.split())[:_LARGO_DEFINICION]
        lineas.append(f"- {texto}")
        return "\n".join(lineas)
    hechos = [a for a in (*objeto.definiciones, *objeto.detalles) if a.es_de_la_fuente]
    if not hechos:
        lineas.append("- (sin afirmaciones comprobadas contra la fuente: no uses este concepto para datos)")
    for afirmacion in hechos:
        lineas.append(f"- {afirmacion.texto[:_LARGO_DEFINICION]}")
    return "\n".join(lineas)


def construir_prompt(
    tema: str, base: Sequence[Nota], publico: str, capitulos: int = 1
) -> str:
    """El prompt de síntesis narrativa, con la base aprobada y las reglas."""
    nombres = ", ".join(n.nombre for n in base)
    return "\n".join(
        [
            "Escribes divulgación científica para el proyecto ZEA MAYZ. Tu trabajo es",
            "contar de forma sencilla y atractiva lo que dice la BASE CIENTÍFICA, sin",
            "cambiar ningún hecho.",
            "",
            "REGLAS",
            "1. Puedes simplificar, explicar con comparaciones y crear personajes y",
            "   escenas. NO puedes añadir hechos científicos, cifras, fechas ni nombres",
            "   que no estén en la BASE CIENTÍFICA.",
            "2. Cada afirmación científica va en «afirmaciones», con la lista de",
            "   conceptos de la base que la respaldan. Usa los nombres EXACTOS:",
            f"   {nombres}.",
            "3. Los diálogos no introducen hechos nuevos: solo repiten o explican lo",
            "   que ya está en «afirmaciones».",
            "4. Los recuadros científicos resumen un concepto de la base y dicen en",
            "   «conceptos» cuál.",
            "5. Si la base no alcanza para algo, no lo inventes: déjalo fuera.",
            f"6. {capitulos} capítulo(s) de 2 o 3 escenas. Público: {publico}.",
            "",
            "Responde SOLO con este objeto JSON:",
            '{"titulo": "...", "capitulos": [{"titulo": "...", "resumen": "...",'
            ' "escenas": [{"titulo": "...", "narracion": "...", "personajes": ["..."],'
            ' "dialogos": [{"personaje": "...", "texto": "..."}],'
            ' "afirmaciones": [{"texto": "...", "conceptos": ["Nombre exacto"]}],'
            ' "recuadro": {"titulo": "...", "texto": "...", "conceptos": ["..."]},'
            ' "vinetas": [{"descripcion": "...", "texto": "..."}],'
            ' "ilustracion": {"descripcion": "...", "elementos": ["..."], "conceptos": ["..."]}}]}]}',
            "",
            f"TEMA: {tema or 'el conjunto de la base'}",
            "",
            "BASE CIENTÍFICA (lo único que puedes afirmar):",
            *(_ficha(n) for n in base),
        ]
    )


# ---------------------------------------------------------------------------
# La respuesta del modelo
# ---------------------------------------------------------------------------


@dataclass
class Borrador:
    titulo: str
    capitulos: list[dict[str, Any]]


def _texto(valor: Any) -> str:
    return " ".join(str(valor).split()) if isinstance(valor, (str, int, float)) else ""


def _lista(valor: Any) -> list[Any]:
    return valor if isinstance(valor, list) else []


def validar_respuesta_narrativa(datos: Any) -> Borrador:
    """Comprueba la forma de la respuesta. Lanza ErrorEsquema si no sirve.

    Solo la forma: si los conceptos están aprobados lo decide después la
    validación científica, sobre el Markdown.
    """
    if not isinstance(datos, Mapping):
        raise ErrorEsquema(["la respuesta no es un objeto JSON"])
    capitulos = _lista(datos.get("capitulos"))
    if not capitulos:
        raise ErrorEsquema(["falta la lista «capitulos» o está vacía"])
    limpios = []
    for c in capitulos:
        if not isinstance(c, Mapping):
            continue
        escenas = []
        for e in _lista(c.get("escenas")):
            if not isinstance(e, Mapping) or not _texto(e.get("narracion")):
                continue
            recuadro = e.get("recuadro") if isinstance(e.get("recuadro"), Mapping) else None
            ilustracion = e.get("ilustracion") if isinstance(e.get("ilustracion"), Mapping) else None
            escenas.append(
                {
                    "titulo": _texto(e.get("titulo")) or "Escena",
                    "narracion": _texto(e.get("narracion")),
                    "personajes": [_texto(p) for p in _lista(e.get("personajes")) if _texto(p)],
                    "dialogos": [
                        {"personaje": _texto(d.get("personaje")) or "Narrador", "texto": _texto(d.get("texto"))}
                        for d in _lista(e.get("dialogos"))
                        if isinstance(d, Mapping) and _texto(d.get("texto"))
                    ],
                    "afirmaciones": [
                        {"texto": _texto(a.get("texto")), "conceptos": [_texto(x) for x in _lista(a.get("conceptos")) if _texto(x)]}
                        for a in _lista(e.get("afirmaciones"))
                        if isinstance(a, Mapping) and _texto(a.get("texto"))
                    ],
                    "recuadro": {
                        "titulo": _texto(recuadro.get("titulo")) or "Para saber más",
                        "texto": _texto(recuadro.get("texto")),
                        "conceptos": [_texto(x) for x in _lista(recuadro.get("conceptos")) if _texto(x)],
                    } if recuadro and _texto(recuadro.get("texto")) else None,
                    "vinetas": [
                        {"descripcion": _texto(v.get("descripcion")), "texto": _texto(v.get("texto"))}
                        for v in _lista(e.get("vinetas"))
                        if isinstance(v, Mapping) and _texto(v.get("descripcion"))
                    ],
                    "ilustracion": {
                        "descripcion": _texto(ilustracion.get("descripcion")),
                        "elementos": [_texto(x) for x in _lista(ilustracion.get("elementos")) if _texto(x)],
                        "conceptos": [_texto(x) for x in _lista(ilustracion.get("conceptos")) if _texto(x)],
                    } if ilustracion and _texto(ilustracion.get("descripcion")) else None,
                }
            )
        if escenas:
            limpios.append({"titulo": _texto(c.get("titulo")) or "Capítulo", "resumen": _texto(c.get("resumen")), "escenas": escenas})
    if not limpios:
        raise ErrorEsquema(["ningún capítulo trae escenas con narración"])
    return Borrador(titulo=_texto(datos.get("titulo")) or "Borrador sin título", capitulos=limpios)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _base(conceptos: Sequence[str], indice: Mapping[str, str]) -> str:
    """Los conceptos como enlaces. Uno que no está en la base queda sin enlazar."""
    enlaces = []
    for concepto in conceptos:
        nombre = indice.get(clave_de_nombre(concepto))
        enlaces.append(f"[[{nombre}]]" if nombre else f"«{concepto}» (no está en la base aprobada)")
    return ", ".join(enlaces) if enlaces else "(ninguna)"


def _cabecera(tipo: str, borrador: Borrador, tema: str, base: Sequence[Nota], modelo: str, aviso: str) -> str:
    frontmatter = escribir_frontmatter(
        {
            "tipo": tipo,
            "estado": "DRAFT",
            "tema": tema or borrador.titulo,
            "base": [n.nombre for n in base],
            "generado_por": modelo,
            "creado": ahora(),
            "tags": ["zea-mayz", tipo],
        }
    )
    return frontmatter + f"# {borrador.titulo}\n\n{aviso}\n\n"


def render_guion(borrador: Borrador, tema: str, base: Sequence[Nota], modelo: str) -> str:
    indice = {clave_de_nombre(n.nombre): n.nombre for n in base}
    for nota in base:
        for alias in nota.alias:
            indice.setdefault(clave_de_nombre(alias), nota.nombre)
    texto = _cabecera(
        "guion", borrador, tema, base, modelo,
        "> [!warning] Borrador narrativo — no es fuente científica\n"
        "> Simplifica y explica; los hechos están en las notas aprobadas enlazadas en cada\n"
        "> afirmación. Tras editarlo, compruébalo con «tatewari zea-mayz validar».",
    )
    partes = [texto]
    for c, capitulo in enumerate(borrador.capitulos, start=1):
        partes.append(f"## Capítulo {c}: {capitulo['titulo']}\n")
        if capitulo["resumen"]:
            partes.append(f"*{capitulo['resumen']}*\n")
        for e, escena in enumerate(capitulo["escenas"], start=1):
            partes.append(f"### Escena {c}.{e}: {escena['titulo']}\n")
            if escena["personajes"]:
                partes.append("**Personajes:** " + ", ".join(escena["personajes"]) + "\n")
            partes.append(escena["narracion"] + "\n")
            if escena["dialogos"]:
                partes.append("**Diálogos**\n")
                partes.extend(f"- **{d['personaje']}:** «{d['texto']}»" for d in escena["dialogos"])
                partes.append("")
            if escena["afirmaciones"]:
                partes.append("**Afirmaciones científicas**\n")
                partes.extend(
                    f"- **Afirmación:** {a['texto']} · **Base:** {_base(a['conceptos'], indice)}"
                    for a in escena["afirmaciones"]
                )
                partes.append("")
            if escena["recuadro"]:
                r = escena["recuadro"]
                partes.append(f"> [!note] Recuadro científico: {r['titulo']}")
                partes.append(f"> {r['texto']}")
                partes.append(f"> **Base:** {_base(r['conceptos'], indice)}")
                partes.append("")
    return "\n".join(partes).rstrip() + "\n"


def render_storyboard(borrador: Borrador, tema: str, base: Sequence[Nota], modelo: str, guion: str) -> str:
    partes = [
        _cabecera(
            "storyboard", borrador, tema, base, modelo,
            f"> [!info] Storyboard del borrador [[{guion}]]. Borrador: revisar antes de ilustrar.",
        )
    ]
    for c, capitulo in enumerate(borrador.capitulos, start=1):
        for e, escena in enumerate(capitulo["escenas"], start=1):
            partes.append(f"## Escena {c}.{e}: {escena['titulo']}\n")
            vinetas = escena["vinetas"] or [{"descripcion": escena["narracion"][:200], "texto": ""}]
            partes.append("| Viñeta | Qué se ve | Texto |\n|---|---|---|")
            for n, v in enumerate(vinetas, start=1):
                descripcion = v["descripcion"].replace("|", "/")
                texto_v = (v["texto"] or "—").replace("|", "/")
                partes.append(f"| {n} | {descripcion} | {texto_v} |")
            partes.append("")
    return "\n".join(partes).rstrip() + "\n"


def render_ilustraciones(borrador: Borrador, tema: str, base: Sequence[Nota], modelo: str, guion: str) -> str:
    indice = {clave_de_nombre(n.nombre): n.nombre for n in base}
    partes = [
        _cabecera(
            "ilustraciones", borrador, tema, base, modelo,
            f"> [!info] Especificaciones de ilustración del borrador [[{guion}]].\n"
            "> No se genera ninguna imagen: esto es el encargo para un ilustrador o para un\n"
            "> generador local futuro. Lo científico de cada imagen debe respetar su base.",
        )
    ]
    numero = 0
    for c, capitulo in enumerate(borrador.capitulos, start=1):
        for e, escena in enumerate(capitulo["escenas"], start=1):
            ilustracion = escena["ilustracion"]
            if not ilustracion:
                continue
            numero += 1
            partes.append(f"## Ilustración {numero} — Escena {c}.{e}: {escena['titulo']}\n")
            partes.append(f"**Descripción:** {ilustracion['descripcion']}\n")
            if ilustracion["elementos"]:
                partes.append("**Elementos que deben aparecer:**")
                partes.extend(f"- {x}" for x in ilustracion["elementos"])
                partes.append("")
            partes.append(f"**Base científica:** {_base(ilustracion['conceptos'], indice)}\n")
    if numero == 0:
        partes.append("*El borrador no pidió ninguna ilustración.*")
    return "\n".join(partes).rstrip() + "\n"


# ---------------------------------------------------------------------------
# La habilidad completa
# ---------------------------------------------------------------------------


@dataclass
class ResultadoDivulgacion:
    guion: Path | None = None
    storyboard: Path | None = None
    ilustraciones: Path | None = None
    base: list[str] = field(default_factory=list)
    validacion: ValidacionNarrativa | None = None
    modelo: str = ""
    avisos: list[str] = field(default_factory=list)

    def resumen(self) -> str:
        lineas = [
            f"Modelo de síntesis : {self.modelo}",
            f"Base aprobada      : {len(self.base)} conceptos ({', '.join(self.base)})",
            f"Guion              : {self.guion}",
            f"Storyboard         : {self.storyboard}",
            f"Ilustraciones      : {self.ilustraciones}",
        ]
        if self.validacion:
            lineas += ["", "VALIDACIÓN CIENTÍFICA", self.validacion.resumen()]
        if self.avisos:
            lineas += ["", "Avisos:"] + [f"  - {a}" for a in self.avisos]
        return "\n".join(lineas)


def generar_borrador(
    vault: Vault,
    jaula: Jaula,
    enrutador: Enrutador,
    tema: str = "",
    nombres: Sequence[str] = (),
    publico: str = "lectores de 10 a 14 años",
    capitulos: int = 1,
) -> ResultadoDivulgacion:
    """divulgacion_cientifica: escribe guion, storyboard y especificaciones."""
    base, avisos = seleccionar_base(vault, tema, nombres)
    if not base:
        raise ErrorDivulgacion(
            "No hay ningún concepto en APPROVED o PUBLISHED en el Vault. La divulgación "
            "solo parte de conocimiento revisado por una persona. Aprueba conceptos con:\n"
            "  python -m tatewari conocimiento estado \"Nombre de la nota\" APPROVED --autor TU_NOMBRE"
        )

    cliente = enrutador.cliente("sintesis")
    modelo = f"modelo:{cliente.elegir()}"
    prompt = construir_prompt(tema, base, publico, capitulos)
    borrador = None
    for intento in (1, 2):
        texto = prompt if intento == 1 else prompt + (
            "\n\nIMPORTANTE: tu respuesta anterior no tenía la forma pedida. Responde "
            "SOLO con el objeto JSON, con la clave «capitulos»."
        )
        generacion = cliente.generar(texto, formato_json=True)
        try:
            borrador = validar_respuesta_narrativa(
                extraer_json_si(generacion.texto, lambda d: "capitulos" in d)
            )
            break
        except ErrorEsquema as error:
            avisos.append(f"Intento {intento}: respuesta no válida ({error}).")
    if borrador is None:
        raise ErrorDivulgacion(
            "El modelo no devolvió un borrador con la forma pedida ni al segundo intento. "
            "No se ha escrito nada. Prueba con menos conceptos (--concepto) o con un modelo "
            "de síntesis mayor (TATEWARI_MODELO_SINTESIS)."
        )

    marca = datetime.now().strftime("%Y-%m-%d %H%M")
    nombre = nombre_de_nota(f"{borrador.titulo} ({marca})")
    ruta_guion = primera_ruta_libre(vault.carpeta("guion"), f"Guion - {nombre}")
    ruta_story = primera_ruta_libre(vault.carpeta("storyboard"), f"Storyboard - {nombre}")
    ruta_ilus = primera_ruta_libre(vault.carpeta("ilustraciones"), f"Ilustraciones - {nombre}")

    guion = render_guion(borrador, tema, base, modelo)
    validacion = validar_borrador(guion, vault)
    guion = guion + "\n" + validacion.markdown()

    resultado = ResultadoDivulgacion(base=[n.nombre for n in base], validacion=validacion, modelo=modelo, avisos=avisos)
    resultado.guion = jaula.escribir_texto(ruta_guion, guion)
    resultado.storyboard = jaula.escribir_texto(
        ruta_story, render_storyboard(borrador, tema, base, modelo, ruta_guion.stem)
    )
    resultado.ilustraciones = jaula.escribir_texto(
        ruta_ilus, render_ilustraciones(borrador, tema, base, modelo, ruta_guion.stem)
    )
    return resultado


registrar(
    "divulgacion_cientifica",
    "Produce un borrador narrativo (guion, storyboard y especificaciones de "
    "ilustración) solo a partir de conceptos APPROVED, y lo valida.",
    generar_borrador,
    usa_modelo=True,
    escribe=True,
)
