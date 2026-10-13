"""Pruebas de la descarga de PDF abiertos. Sin red: una sesión falsa sirve bytes."""

from __future__ import annotations

from dataclasses import dataclass

import requests

from tatewari.descargas import (
    DESCARGADO,
    FALLO,
    NO_ES_PDF,
    RECHAZADO,
    SIN_ENLACE,
    YA_ESTABA,
    descargar_incluidos,
    enlace_de,
    es_pdf,
    leer_descargas,
    nombre_de_archivo,
)
from tatewari.texto_completo import Resuelto

PDF = b"%PDF-1.7\n" + b"x" * 2000


@dataclass
class Decision:
    identificador: str
    registro: dict


class RespuestaFalsa:
    def __init__(self, estado=200, cuerpo=b"", tipo="application/pdf"):
        self.status_code = estado
        self._cuerpo = cuerpo
        self.headers = {"Content-Type": tipo}
        self.cerrada = False

    def iter_content(self, chunk_size=1024):
        for inicio in range(0, len(self._cuerpo), chunk_size):
            yield self._cuerpo[inicio : inicio + chunk_size]

    def close(self):
        self.cerrada = True


class SesionFalsa:
    """Contesta según la URL; guarda lo que se pidió."""

    def __init__(self, respuestas):
        self.respuestas = respuestas
        self.urls = []

    def get(self, url, **opciones):
        self.urls.append(url)
        respuesta = self.respuestas[url]
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


def registro(oa_url="NR", autores="['S. N. Malkanthi', 'N. Balthazaar']", anio="2019"):
    return {"titulo": "Lime stabilization", "autores": autores, "anio": anio, "oa_url": oa_url}


def test_nombre_de_archivo_lleva_id_apellido_y_anio():
    assert nombre_de_archivo("R0001", registro()) == "R0001_Malkanthi_2019.pdf"
    assert nombre_de_archivo("R0002", registro(autores="NR", anio="NR")) == "R0002.pdf"
    assert nombre_de_archivo("R0003", registro(autores="['José Núñez']")) == "R0003_Nunez_2019.pdf"


def test_enlace_prefiere_unpaywall():
    resuelto = Resuelto("R0001", estado="abierto", oa_url="https://repo/u.pdf")
    assert enlace_de(registro("https://openalex/o"), resuelto) == "https://repo/u.pdf"
    assert enlace_de(registro("https://openalex/o"), None) == "https://openalex/o"
    assert enlace_de(registro(), None) == "NR"


def test_es_pdf_mira_la_firma_y_no_la_cabecera():
    assert es_pdf(b"%PDF-1.4 ...")
    assert not es_pdf(b"<!DOCTYPE html>")


def test_descarga_clasifica_cada_caso(tmp_path):
    sesion = SesionFalsa(
        {
            "https://a/pdf": RespuestaFalsa(cuerpo=PDF),
            "https://b/pagina": RespuestaFalsa(cuerpo=b"<html>hola</html>", tipo="text/html"),
            "https://c/bloqueado": RespuestaFalsa(estado=403),
            "https://d/caido": requests.ConnectionError("sin red"),
        }
    )
    decisiones = [
        Decision("R0001", registro("https://a/pdf")),
        Decision("R0002", registro("https://b/pagina")),
        Decision("R0003", registro("https://c/bloqueado")),
        Decision("R0004", registro("https://d/caido")),
        Decision("R0005", registro()),
    ]
    resultado = descargar_incluidos(decisiones, {}, tmp_path, sesion=sesion)
    estados = {i: d.estado for i, d in resultado.descargas.items()}
    assert estados == {
        "R0001": DESCARGADO,
        "R0002": NO_ES_PDF,
        "R0003": RECHAZADO,
        "R0004": FALLO,
        "R0005": SIN_ENLACE,
    }
    assert (tmp_path / "pdf" / "R0001_Malkanthi_2019.pdf").read_bytes() == PDF
    assert not any(p.name.startswith("R0002") for p in (tmp_path / "pdf").iterdir())
    assert leer_descargas(tmp_path)["R0001"]["estado"] == DESCARGADO
    para_abrir = (tmp_path / "para-abrir.md").read_text(encoding="utf-8")
    assert "R0002" in para_abrir and "R0003" in para_abrir and "R0004" in para_abrir
    assert "R0001" not in para_abrir and "R0005" not in para_abrir


def test_es_reanudable(tmp_path):
    sesion = SesionFalsa({"https://a/pdf": RespuestaFalsa(cuerpo=PDF)})
    decisiones = [Decision("R0001", registro("https://a/pdf"))]
    descargar_incluidos(decisiones, {}, tmp_path, sesion=sesion)
    segunda = descargar_incluidos(decisiones, {}, tmp_path, sesion=sesion)
    assert segunda.descargas["R0001"].estado == YA_ESTABA
    assert sesion.urls == ["https://a/pdf"]


def test_respeta_el_tamano_maximo(tmp_path):
    sesion = SesionFalsa({"https://a/pdf": RespuestaFalsa(cuerpo=PDF)})
    resultado = descargar_incluidos(
        [Decision("R0001", registro("https://a/pdf"))], {}, tmp_path, sesion=sesion, tamano_maximo=100
    )
    assert resultado.descargas["R0001"].estado == FALLO
    assert list((tmp_path / "pdf").iterdir()) == []
