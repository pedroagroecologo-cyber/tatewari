"""Descarga de los PDF en acceso abierto de los registros incluidos.

Hasta aquí Tatewari sabía **dónde** estaba el texto completo legal de cada
artículo (``texto-completo``), pero había que abrir los enlaces uno por uno.
Este módulo los baja a la carpeta ``pdf/`` de la revisión.

Qué enlace se usa
-----------------

Primero el de Unpaywall (``texto_completo.json``), porque suele apuntar al PDF
mismo; si no lo hay, el ``oa_url`` que trajo OpenAlex en la cosecha, que a veces
es la página del artículo y no el archivo.

Lo que no hace, a propósito (AGENTS.md, regla 5)
-------------------------------------------------

- **Solo baja lo que el servidor entrega como PDF.** Si el enlace lleva a una
  página web (la ficha del artículo en la editorial), no se raspa ni se buscan
  botones: se anota como «abrir en el navegador», con su enlace.
- **Se presenta como Tatewari**, con su agente de usuario de siempre. Si una
  editorial rechaza a un programa (403), se respeta: el artículo queda para
  abrirlo a mano. Nunca se disfraza de navegador para saltarse un bloqueo.
- Lo que no tiene versión abierta ni se intenta: va a ``por-conseguir.md``,
  para pedirlo a la biblioteca o al autor.

Es reanudable: un PDF que ya está en la carpeta no se vuelve a bajar, así que
cortar con Ctrl+C no pierde nada.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import requests

from .fuentes import NR
from .http import AGENTE_USUARIO
from .texto_completo import Resuelto

__all__ = [
    "CARPETA_PDF",
    "NOMBRE_DESCARGAS",
    "TAMANO_MAXIMO",
    "Descarga",
    "ResultadoDescargas",
    "nombre_de_archivo",
    "enlace_de",
    "es_pdf",
    "descargar_incluidos",
    "leer_descargas",
    "NOMBRE_PARA_ABRIR",
    "escribir_para_abrir",
]

CARPETA_PDF = "pdf"
NOMBRE_DESCARGAS = "descargas.json"
NOMBRE_PARA_ABRIR = "para-abrir.md"

#: Un artículo rara vez pasa de 30 MB; 60 deja margen para tesis con figuras y
#: corta a tiempo un enlace que en realidad sirve otra cosa.
TAMANO_MAXIMO = 60 * 1024 * 1024
TIEMPO_ESPERA = 60.0
_TROZO = 64 * 1024

DESCARGADO = "descargado"
YA_ESTABA = "ya_estaba"
NO_ES_PDF = "no_es_pdf"
RECHAZADO = "rechazado"
FALLO = "fallo"
SIN_ENLACE = "sin_enlace"

_NO_ALFANUMERICO = re.compile(r"[^A-Za-z0-9]+")


def _ascii(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in plano if not unicodedata.combining(c))


def _primer_apellido(autores: Any) -> str:
    """El apellido del primer autor, como lo escribe la cosecha.

    La cosecha guarda los autores como una lista o como el texto de una lista
    («['S. N. Malkanthi', '…']»). Del primero se toma la última palabra.
    """
    if isinstance(autores, str):
        texto = autores.strip()
        if texto in ("", NR):
            return ""
        if texto.startswith("["):
            try:
                autores = json.loads(texto.replace("'", '"'))
            except ValueError:
                autores = [texto.strip("[]").split(",")[0]]
        else:
            autores = [texto.split(";")[0]]
    if not isinstance(autores, list) or not autores:
        return ""
    primero = str(autores[0]).strip().strip("'\"")
    partes = primero.split()
    return partes[-1] if partes else ""


def nombre_de_archivo(identificador: str, registro: Mapping[str, Any]) -> str:
    """«R0001_Malkanthi_2019.pdf»: se reconoce en el explorador de archivos."""
    piezas = [identificador]
    apellido = _NO_ALFANUMERICO.sub("", _ascii(_primer_apellido(registro.get("autores"))))
    if apellido:
        piezas.append(apellido[:30])
    anio = str(registro.get("anio") or "").strip()
    if anio.isdigit():
        piezas.append(anio)
    return "_".join(piezas) + ".pdf"


def enlace_de(registro: Mapping[str, Any], resuelto: Resuelto | None) -> str:
    """El mejor enlace abierto: el de Unpaywall y, si no, el de OpenAlex."""
    if resuelto is not None and resuelto.esta_abierto:
        return resuelto.oa_url
    enlace = str(registro.get("oa_url") or NR).strip()
    return enlace if enlace.startswith("http") else NR


def es_pdf(inicio: bytes) -> bool:
    """¿Es un PDF? Manda la firma del archivo, no la cabecera Content-Type:
    hay servidores que mandan un PDF como «application/octet-stream» y páginas
    de error como «application/pdf»."""
    return inicio.lstrip()[:5] == b"%PDF-"


@dataclass(frozen=True)
class Descarga:
    """Lo que pasó con el PDF de un registro."""

    identificador: str
    estado: str
    enlace: str = NR
    archivo: str = NR
    bytes: int = 0
    nota: str = NR

    def como_json(self) -> dict[str, Any]:
        return {
            "estado": self.estado,
            "enlace": self.enlace,
            "archivo": self.archivo,
            "bytes": self.bytes,
            "nota": self.nota,
        }

    def linea(self) -> str:
        if self.estado in (DESCARGADO, YA_ESTABA):
            tamano = f"{self.bytes / 1024 / 1024:.1f} MB"
            prefijo = "bajado" if self.estado == DESCARGADO else "ya estaba"
            return f"{self.identificador}  {prefijo}: {self.archivo} ({tamano})"
        if self.estado == NO_ES_PDF:
            return f"{self.identificador}  es una página web: ábrela en el navegador"
        if self.estado == RECHAZADO:
            return f"{self.identificador}  la editorial no deja bajarlo a un programa: ábrelo en el navegador"
        if self.estado == SIN_ENLACE:
            return f"{self.identificador}  sin versión abierta: va a por-conseguir.md"
        return f"{self.identificador}  falló: {self.nota}"


@dataclass
class ResultadoDescargas:
    descargas: dict[str, Descarga] = field(default_factory=dict)

    def contar(self, *estados: str) -> int:
        return sum(1 for d in self.descargas.values() if d.estado in estados)

    def a_mano(self) -> list[Descarga]:
        """Las que tienen enlace pero hay que abrir en el navegador."""
        return [
            d for d in self.descargas.values() if d.estado in (NO_ES_PDF, RECHAZADO, FALLO)
        ]

    def resumen(self) -> str:
        return "\n".join(
            [
                f"PDF en la carpeta     : {self.contar(DESCARGADO, YA_ESTABA)} "
                f"({self.contar(DESCARGADO)} nuevos)",
                f"Abrir en el navegador : {self.contar(NO_ES_PDF, RECHAZADO, FALLO)}",
                f"Sin versión abierta   : {self.contar(SIN_ENLACE)} (van a por-conseguir.md)",
            ]
        )


def _bajar(sesion: Any, enlace: str, destino: Path, tamano_maximo: int) -> tuple[str, int, str]:
    """Baja `enlace` a `destino` si es un PDF. Devuelve (estado, bytes, nota)."""
    try:
        respuesta = sesion.get(enlace, stream=True, timeout=TIEMPO_ESPERA, allow_redirects=True)
    except requests.RequestException as error:
        return FALLO, 0, f"sin conexión ({type(error).__name__})"
    try:
        estado = respuesta.status_code
        if estado in (401, 403):
            return RECHAZADO, 0, f"el servidor respondió {estado}"
        if not 200 <= estado < 300:
            return FALLO, 0, f"el servidor respondió {estado}"
        tipo = str(respuesta.headers.get("Content-Type", ""))
        trozos = respuesta.iter_content(chunk_size=_TROZO)
        primero = next(trozos, b"")
        if not es_pdf(primero):
            return NO_ES_PDF, 0, f"el enlace entrega {tipo or 'algo que no es PDF'}"
        temporal = destino.with_suffix(".pdf.parcial")
        total = 0
        with open(temporal, "wb") as manejador:
            for trozo in _encadenar(primero, trozos):
                total += len(trozo)
                if total > tamano_maximo:
                    manejador.close()
                    temporal.unlink(missing_ok=True)
                    return FALLO, 0, f"pasa de {tamano_maximo // 1024 // 1024} MB"
                manejador.write(trozo)
        temporal.replace(destino)
        return DESCARGADO, total, NR
    finally:
        cerrar = getattr(respuesta, "close", None)
        if callable(cerrar):
            cerrar()


def _encadenar(primero: bytes, resto: Iterable[bytes]) -> Iterable[bytes]:
    if primero:
        yield primero
    for trozo in resto:
        if trozo:
            yield trozo


def nueva_sesion() -> requests.Session:
    sesion = requests.Session()
    sesion.headers.update({"User-Agent": AGENTE_USUARIO})
    return sesion


def descargar_incluidos(
    decisiones: Iterable[Any],
    resueltos: Mapping[str, Resuelto],
    carpeta: Path | str,
    sesion: Any | None = None,
    tamano_maximo: int = TAMANO_MAXIMO,
    avance: Callable[[int, int, Descarga], None] | None = None,
) -> ResultadoDescargas:
    """Baja el PDF abierto de cada decisión y lo deja en ``carpeta/pdf``.

    `decisiones` son las de los incluidos, con su ``identificador`` y su
    ``registro``. Un fallo en uno no detiene a los demás.
    """
    carpeta_pdf = Path(carpeta) / CARPETA_PDF
    carpeta_pdf.mkdir(parents=True, exist_ok=True)
    sesion = sesion or nueva_sesion()
    resultado = ResultadoDescargas()
    lista = list(decisiones)
    for indice, decision in enumerate(lista, start=1):
        identificador = decision.identificador
        registro = decision.registro
        enlace = enlace_de(registro, resueltos.get(identificador))
        nombre = nombre_de_archivo(identificador, registro)
        destino = carpeta_pdf / nombre
        if enlace == NR:
            descarga = Descarga(identificador, SIN_ENLACE)
        elif destino.is_file() and destino.stat().st_size > 0:
            descarga = Descarga(
                identificador, YA_ESTABA, enlace, nombre, destino.stat().st_size
            )
        else:
            estado, tamano, nota = _bajar(sesion, enlace, destino, tamano_maximo)
            descarga = Descarga(
                identificador,
                estado,
                enlace,
                nombre if estado == DESCARGADO else NR,
                tamano,
                nota,
            )
        resultado.descargas[identificador] = descarga
        if avance is not None:
            avance(indice, len(lista), descarga)
    _guardar(Path(carpeta) / NOMBRE_DESCARGAS, resultado)
    escribir_para_abrir(Path(carpeta) / NOMBRE_PARA_ABRIR, resultado, {
        decision.identificador: decision.registro for decision in lista
    })
    return resultado


def escribir_para_abrir(
    ruta: Path, resultado: ResultadoDescargas, registros: Mapping[str, Mapping[str, Any]]
) -> Path:
    """Lista en Markdown los abiertos que no se bajaron solos.

    Son legales y abiertos, pero la editorial no los entrega a un programa o el
    enlace es una página. Desde Obsidian o cualquier visor de Markdown son un
    clic cada uno; el navegador sí los baja, porque así espera la editorial que
    se lean.
    """
    pendientes = resultado.a_mano()
    lineas = [
        "# Para abrir en el navegador",
        "",
        "Artículos en acceso abierto que no se bajaron solos: la editorial no los",
        "entrega a un programa o el enlace lleva a la página del artículo. Ábrelos",
        "y guarda el PDF en la carpeta `pdf/` con el nombre que se indica.",
        "",
    ]
    if not pendientes:
        lineas.append("No queda ninguno: todos los abiertos se bajaron solos.")
    for descarga in pendientes:
        registro = registros.get(descarga.identificador, {})
        titulo = str(registro.get("titulo") or NR).strip()
        nombre = nombre_de_archivo(descarga.identificador, registro)
        lineas.append(f"- [ ] **{descarga.identificador}** — [{titulo}]({descarga.enlace})")
        lineas.append(f"  guárdalo como `{nombre}`")
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return ruta


def _guardar(ruta: Path, resultado: ResultadoDescargas) -> None:
    salida = {
        "actualizado": datetime.now().isoformat(timespec="seconds"),
        "carpeta": CARPETA_PDF,
        "descargas": {
            identificador: resultado.descargas[identificador].como_json()
            for identificador in sorted(resultado.descargas)
        },
    }
    with open(ruta, "w", encoding="utf-8") as manejador:
        json.dump(salida, manejador, ensure_ascii=False, indent=2)
        manejador.write("\n")


def leer_descargas(carpeta: Path | str) -> dict[str, dict[str, Any]]:
    """Lee ``descargas.json``; vacío si todavía no se ha descargado nada."""
    ruta = Path(carpeta) / NOMBRE_DESCARGAS
    if not ruta.is_file():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    descargas = datos.get("descargas") if isinstance(datos, dict) else None
    return descargas if isinstance(descargas, dict) else {}
