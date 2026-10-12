"""Las notas en Markdown: plantillas, frontmatter y el rastro para actualizar.

Una nota de Knowledge Studio tiene tres partes:

1. **Frontmatter YAML** con lo que Obsidian entiende de serie (``aliases`` y
   ``tags``) y lo que Tatewari necesita (``tatewari_id``, ``estado``,
   ``fuentes``…). Se escribe un subconjunto muy simple de YAML: escalares entre
   comillas dobles al estilo JSON y listas en bloque. Así se puede leer de vuelta
   sin depender de PyYAML.
2. **El cuerpo**, a partir de una plantilla de `plantillas/`, con los enlaces
   ``[[...]]`` a otras notas. Todo lo que no sale literalmente de la fuente va
   marcado como interpretación del modelo.
3. **Un bloque de datos** entre ``%%`` (comentario de Obsidian: no se ve al leer)
   con el objeto completo en JSON. Es lo que permite actualizar la nota fundiendo
   lo nuevo con lo que había, en vez de reescribirla a ciegas.

La huella del cuerpo
--------------------

Tatewari guarda en ``tatewari_hash`` la huella del cuerpo que escribió. Si al
volver la huella no coincide, alguien editó la nota a mano, y a partir de ese
momento la nota es de esa persona: Tatewari ya no la reescribe, solo propone
cambios en la bandeja de entrada.
"""

from __future__ import annotations

import hashlib
import json
import re
from importlib import resources
from string import Template
from typing import Any, Iterable, Mapping, Sequence

from .documento import NR
from .objetos import Afirmacion, ObjetoConocimiento, clave_de_nombre
from .rutas import nombre_de_nota

__all__ = [
    "PLANTILLAS",
    "AVISO_BORRADOR",
    "aviso_aprobado",
    "leer_plantilla",
    "plantilla_para_obsidian",
    "escribir_frontmatter",
    "leer_nota",
    "huella_cuerpo",
    "enlace",
    "enlaces_de",
    "render_objeto",
    "render_fuente",
    "MARCA_DATOS",
]

#: Tipo de objeto -> plantilla que se usa para su nota.
PLANTILLAS = {
    "persona": "personaje",
    "lugar": "lugar",
    "proceso": "proceso",
    "metodo": "proceso",
}

MARCA_DATOS = "tatewari-datos"

_BLOQUE_DATOS = re.compile(r"\n?%%\s*" + MARCA_DATOS + r"\s*\n(.*?)\n%%\s*$", re.S)
_ENLACE = re.compile(r"\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|[^\]]*)?\]\]")

_ETIQUETAS_ORIGEN = {
    "fuente": "de la fuente",
    "inferencia": "interpretación del modelo, sin verificar",
}


# ---------------------------------------------------------------------------
# Plantillas
# ---------------------------------------------------------------------------


def leer_plantilla(nombre: str) -> str:
    """El texto de una plantilla de `plantillas/`, sin extensión en el nombre."""
    return (
        resources.files("tatewari.conocimiento")
        .joinpath("plantillas", f"{nombre}.md")
        .read_text(encoding="utf-8")
    )


def plantilla_para_obsidian(texto: str) -> str:
    """Convierte una plantilla de Tatewari en una que la persona pueda usar a mano.

    Las variables ``$titulo`` pasan a ``{{title}}``, que es lo que entiende el
    complemento de plantillas **de serie** de Obsidian; el resto se deja como un
    hueco que rellenar.
    """
    texto = texto.replace("$titulo", "{{title}}").replace("$fecha", "{{date}}")
    return re.sub(r"\$\{?[a-z_]+\}?", "…", texto)


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------


def _escalar(valor: Any) -> str:
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (int, float)):
        return str(valor)
    return json.dumps(str(valor), ensure_ascii=False)


def escribir_frontmatter(campos: Mapping[str, Any]) -> str:
    """YAML mínimo: escalares entre comillas y listas en bloque. Legible por Obsidian."""
    lineas = ["---"]
    for clave, valor in campos.items():
        if isinstance(valor, (list, tuple)):
            if not valor:
                lineas.append(f"{clave}: []")
                continue
            lineas.append(f"{clave}:")
            lineas.extend(f"  - {_escalar(v)}" for v in valor)
        else:
            lineas.append(f"{clave}: {_escalar(valor)}")
    lineas.append("---")
    return "\n".join(lineas) + "\n"


def _valor(crudo: str) -> Any:
    crudo = crudo.strip()
    if not crudo:
        return ""
    if crudo in ("[]",):
        return []
    try:
        return json.loads(crudo)
    except ValueError:
        return crudo.strip("'\"")


def _leer_frontmatter(texto: str) -> tuple[dict[str, Any], str]:
    """Separa el frontmatter del cuerpo. Tolera YAML escrito a mano (lo básico)."""
    if not texto.startswith("---"):
        return {}, texto
    lineas = texto.split("\n")
    fin = next((i for i in range(1, len(lineas)) if lineas[i].strip() == "---"), None)
    if fin is None:
        return {}, texto
    campos: dict[str, Any] = {}
    clave_lista: str | None = None
    for linea in lineas[1:fin]:
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        elemento = re.match(r"^\s+-\s*(.*)$", linea)
        if elemento and clave_lista is not None:
            campos.setdefault(clave_lista, [])
            if isinstance(campos[clave_lista], list):
                campos[clave_lista].append(_valor(elemento.group(1)))
            continue
        par = re.match(r"^([\w.-]+)\s*:\s*(.*)$", linea)
        if par:
            clave, valor = par.group(1), par.group(2)
            if valor.strip() == "":
                campos[clave] = []
                clave_lista = clave
            else:
                campos[clave] = _valor(valor)
                clave_lista = None
                # YAML en línea: «tags: [a, b]»
                if isinstance(campos[clave], str) and valor.strip().startswith("["):
                    campos[clave] = [
                        v.strip().strip("'\"") for v in valor.strip()[1:-1].split(",") if v.strip()
                    ]
    return campos, "\n".join(lineas[fin + 1 :])


def huella_cuerpo(cuerpo: str) -> str:
    """Huella del cuerpo visible, sin el bloque de datos y sin espacios del final."""
    visible = _BLOQUE_DATOS.sub("", cuerpo).rstrip()
    return hashlib.sha256(visible.encode("utf-8")).hexdigest()[:16]


def leer_nota(texto: str) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
    """Frontmatter, cuerpo y datos del objeto (o `None` si la nota no los trae)."""
    campos, cuerpo = _leer_frontmatter(texto)
    datos = None
    encontrado = _BLOQUE_DATOS.search(cuerpo)
    if encontrado:
        try:
            cargado = json.loads(encontrado.group(1))
            datos = cargado if isinstance(cargado, dict) else None
        except ValueError:
            datos = None
    return campos, cuerpo, datos


# ---------------------------------------------------------------------------
# Enlaces
# ---------------------------------------------------------------------------


def enlace(destino: str, indice: Mapping[str, str] | None = None) -> str:
    """El enlace ``[[...]]`` a una nota, resolviendo nombres y alias.

    `indice` va de clave de nombre a nombre de archivo de la nota. Si el destino
    es un alias de una nota que se llama distinto, sale ``[[Nota|alias]]``, que es
    como Obsidian muestra un texto y enlaza a otra nota. Si no existe, el enlace
    queda apuntando al nombre limpio: Obsidian lo muestra como nota pendiente, y
    la validación lo cuenta.
    """
    indice = indice or {}
    nombre = indice.get(clave_de_nombre(destino)) or nombre_de_nota(destino)
    if nombre == destino:
        return f"[[{nombre}]]"
    visible = destino.replace("|", " ").replace("]", " ").replace("[", " ").strip()
    return f"[[{nombre}|{visible}]]" if visible and visible != nombre else f"[[{nombre}]]"


def enlaces_de(texto: str) -> list[str]:
    """Los destinos de todos los ``[[...]]`` de un texto, sin alias ni anclas."""
    return [m.group(1).strip() for m in _ENLACE.finditer(texto)]


# ---------------------------------------------------------------------------
# Render de objetos
# ---------------------------------------------------------------------------


def _donde(afirmacion: Afirmacion, notas_fuente: Mapping[str, str]) -> str:
    if afirmacion.documento == NR:
        return ""
    nota = notas_fuente.get(afirmacion.documento)
    documento = f"[[{nota}|{afirmacion.documento}]]" if nota else afirmacion.documento
    ubicacion = f", {afirmacion.ubicacion}" if afirmacion.ubicacion != NR else ""
    return f"{documento}{ubicacion}"


def _lista_afirmaciones(
    afirmaciones: Sequence[Afirmacion], notas_fuente: Mapping[str, str], vacio: str
) -> str:
    if not afirmaciones:
        return vacio
    lineas = []
    for a in afirmaciones:
        origen = _ETIQUETAS_ORIGEN["fuente" if a.es_de_la_fuente else "inferencia"]
        donde = _donde(a, notas_fuente)
        lineas.append(f"- {a.texto}  \n  *({origen}{' · ' + donde if donde else ''})*")
        if a.es_de_la_fuente and a.cita != NR:
            lineas.append(f"  > «{a.cita}»")
    return "\n".join(lineas)


#: La línea del aviso que dice que la nota es un borrador. `Vault.cambiar_estado`
#: la cambia por la de aprobación, y al revés.
AVISO_BORRADOR = (
    "> Borrador generado por Tatewari. No es conocimiento aprobado: revísalo "
    "contra la fuente antes de pasarlo a APPROVED."
)


def aviso_aprobado(estado: str, autor: str, fecha: str) -> str:
    """La línea que sustituye a AVISO_BORRADOR cuando una persona aprueba o publica."""
    verbo = "Publicado" if estado == "PUBLISHED" else "Aprobado"
    return f"> {verbo} por {autor} el {fecha[:10]}. Tatewari ya no reescribe esta nota."


def _aviso(objeto: ObjetoConocimiento) -> str:
    lineas = [
        f"> [!info] Estado: {objeto.estado} · Confianza: {objeto.confianza:.2f} · "
        f"Generado por: {objeto.modelo}",
    ]
    if objeto.estado in ("DRAFT", "REVIEW"):
        lineas.append(AVISO_BORRADOR)
    if objeto.insuficiente:
        lineas.append(
            "> **El modelo indicó que el documento no da información suficiente** "
            "sobre este tema. Lo que haya aquí es parcial."
        )
    if not objeto.verificado:
        lineas.append(
            "> **Ninguna definición se pudo comprobar contra el texto de la fuente.**"
        )
    return "\n".join(lineas)


def _relaciones(objeto: ObjetoConocimiento, indice: Mapping[str, str]) -> str:
    if not objeto.relaciones:
        return "*Sin relaciones detectadas.*"
    lineas = []
    for r in objeto.relaciones:
        marca = "" if r.origen == "fuente" else " *(interpretación del modelo)*"
        lineas.append(f"- {r.tipo} → {enlace(r.destino, indice)}{marca}")
    return "\n".join(lineas)


def _conflictos(objeto: ObjetoConocimiento) -> str:
    if not objeto.conflictos:
        return "*Sin conflictos detectados.*"
    bloques = []
    for c in objeto.conflictos:
        bloques.append(f"> [!warning] {c.get('descripcion', 'Conflicto entre fuentes')}")
        for version in c.get("versiones", []):
            bloques.append(
                f"> - «{version.get('texto', NR)}» — {version.get('documento', NR)}, "
                f"{version.get('ubicacion', NR)}"
            )
        bloques.append("> Tatewari no elige una versión: lo decide una persona.")
        bloques.append("")
    return "\n".join(bloques).rstrip()


def _fuentes(objeto: ObjetoConocimiento, notas_fuente: Mapping[str, str]) -> str:
    if not objeto.ubicaciones:
        return f"- {NR}"
    lineas = []
    for ubicacion in objeto.ubicaciones:
        documento, _, lugar = ubicacion.partition(", ")
        nota = notas_fuente.get(documento)
        enlazado = f"[[{nota}|{documento}]]" if nota else documento
        lineas.append(f"- {enlazado}{', ' + lugar if lugar else ''}")
    return "\n".join(lineas)


def render_objeto(
    objeto: ObjetoConocimiento,
    indice: Mapping[str, str] | None = None,
    notas_fuente: Mapping[str, str] | None = None,
) -> str:
    """La nota completa de un objeto: frontmatter, cuerpo con plantilla y datos."""
    indice = indice or {}
    notas_fuente = notas_fuente or {}
    plantilla = Template(leer_plantilla(PLANTILLAS.get(objeto.tipo, "concepto")))
    referencias = (
        "\n".join(f"- {r}" for r in objeto.referencias)
        if objeto.referencias
        else "*Las referencias bibliográficas del documento están en su nota de fuente.*"
    )
    cuerpo = plantilla.safe_substitute(
        titulo=objeto.titulo,
        aviso=_aviso(objeto),
        definicion=_lista_afirmaciones(
            objeto.definiciones, notas_fuente,
            "*La fuente no da una definición que se haya podido comprobar.*",
        ),
        resumen=objeto.resumen if objeto.resumen != NR else "*Sin resumen.*",
        detalles=_lista_afirmaciones(objeto.detalles, notas_fuente, "*Sin detalles.*"),
        relaciones=_relaciones(objeto, indice),
        conflictos=_conflictos(objeto),
        referencias=referencias,
        fuentes=_fuentes(objeto, notas_fuente),
        tipo=objeto.tipo,
    ).rstrip() + "\n"
    datos = json.dumps(objeto.como_dict(), ensure_ascii=False, indent=1)
    campos = {
        "tatewari_id": objeto.id,
        "tipo": objeto.tipo,
        "estado": objeto.estado,
        "aliases": objeto.alias,
        "tags": sorted({"knowledge-studio", objeto.tipo, *objeto.etiquetas}),
        "confianza": objeto.confianza,
        "fuentes": objeto.ubicaciones,
        "creado": objeto.creado,
        "actualizado": objeto.actualizado,
        "generado_por": objeto.modelo,
        "tatewari_hash": huella_cuerpo(cuerpo),
    }
    return escribir_frontmatter(campos) + cuerpo + f"\n%% {MARCA_DATOS}\n{datos}\n%%\n"


def render_fuente(
    documento: Any,
    nota_original: str,
    objetos: Iterable[tuple[str, ObjetoConocimiento]],
    referencias: Sequence[str],
    avisos: Sequence[str],
) -> str:
    """La nota de un documento fuente: metadatos y todo lo que se sacó de él.

    Cada objeto extraído queda enlazado desde aquí, y cada nota de objeto enlaza
    de vuelta a esta. Ese ir y volver es lo que dibuja la vista de grafo.
    """
    plantilla = Template(leer_plantilla("fuente"))
    lista = list(objetos)
    conceptos = (
        "\n".join(f"- [[{nombre}]] · {obj.tipo} · {obj.estado}" for nombre, obj in lista)
        if lista
        else "*No se extrajo ningún objeto de conocimiento.*"
    )
    metadatos = "\n".join(
        [
            f"- **Archivo original**: [[{nota_original}]]",
            f"- **Tipo**: {documento.tipo.upper()}",
            f"- **Título declarado**: {documento.titulo}",
            f"- **Autoría declarada**: {documento.autores}",
            f"- **Fecha**: {documento.fecha}",
            f"- **Extensión**: {documento.unidades} {documento.unidad}",
            f"- **Huella SHA-256**: `{documento.sha256[:16]}…`",
        ]
    )
    cuerpo = plantilla.safe_substitute(
        titulo=f"Fuente - {documento.titulo_legible}",
        metadatos=metadatos,
        conceptos=conceptos,
        referencias="\n".join(f"- {r}" for r in referencias)
        if referencias
        else "*No se detectaron referencias bibliográficas en el texto.*",
        avisos="\n".join(f"- {a}" for a in avisos) if avisos else "*Sin avisos.*",
    ).rstrip() + "\n"
    campos = {
        "tatewari_id": f"FUENTE-{documento.sha256[:12]}",
        "tipo": "fuente",
        "estado": "REVIEW",
        "aliases": [documento.nombre],
        "tags": ["knowledge-studio", "fuente"],
        "archivo": documento.nombre,
        "sha256": documento.sha256,
        "unidades": documento.unidades,
        "unidad": documento.unidad,
        "actualizado": _ahora(),
        "tatewari_hash": huella_cuerpo(cuerpo),
    }
    return escribir_frontmatter(campos) + cuerpo


def _ahora() -> str:
    from .objetos import ahora

    return ahora()


__all__ += ["clave_de_nombre"]
