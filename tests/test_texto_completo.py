"""Pruebas de la resolución de textos completos. No tocan la red.

Unpaywall se simula con el `ClienteFalso` de `conftest.py` (AGENTS.md, regla 6).
"""

from __future__ import annotations

import json

import pytest

from tatewari.config import ErrorConfig
from tatewari.cribado import Decision
from tatewari.fuentes.unpaywall import (
    ESTADO_ABIERTO,
    ESTADO_CERRADO,
    ESTADO_DESCONOCIDO,
)
from tatewari.http import ErrorHttpServidor
from tatewari.texto_completo import (
    ESTADO_SIN_DOI,
    NOMBRE_TEXTO_COMPLETO,
    Resuelto,
    aplicar_a_registros,
    guardar_resueltos,
    leer_resueltos,
    resolver_incluidos,
)

CORREO = "prueba@ejemplo.invalid"


def decision(identificador="R0001", doi="10.1234/abierto", **campos):
    registro = {
        "identificador": identificador,
        "doi": doi,
        "titulo": "Un título",
        "anio": 2020,
        "idioma": "es",
        "revista": "NR",
        "autores": ["NR"],
        "resumen": "Un resumen.",
        "tipo": "article",
        "citas": "NR",
        "oa_url": "NR",
    }
    registro.update(campos)
    return Decision(
        identificador=identificador,
        decision="incluir",
        motivo="da igual",
        registro=registro,
    )


def respuesta_abierta(url="https://repositorio.invalid/uno.pdf"):
    return {
        "doi": "10.1234/abierto",
        "best_oa_location": {
            "url_for_pdf": url,
            "version": "publishedVersion",
            "license": "cc-by",
            "host_type": "repository",
        },
    }


def respuesta_cerrada():
    return {"doi": "10.1234/cerrado", "best_oa_location": None}


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def test_un_doi_con_version_abierta_guarda_la_url(cliente_falso):
    cliente = cliente_falso([respuesta_abierta()])

    salida = resolver_incluidos([decision()], cliente, CORREO)

    resuelto = salida.resueltos["R0001"]
    assert resuelto.estado == ESTADO_ABIERTO
    assert resuelto.oa_url == "https://repositorio.invalid/uno.pdf"
    assert resuelto.licencia == "cc-by"
    assert resuelto.esta_abierto
    assert salida.abiertos == 1


def test_un_doi_sin_version_abierta_se_marca_para_la_biblioteca(cliente_falso):
    """Y no se intenta ninguna otra vía (AGENTS.md, regla 5)."""
    cliente = cliente_falso([respuesta_cerrada()])

    salida = resolver_incluidos([decision()], cliente, CORREO)

    resuelto = salida.resueltos["R0001"]
    assert resuelto.estado == ESTADO_CERRADO
    assert resuelto.oa_url == "NR"
    assert not resuelto.esta_abierto
    assert salida.cerrados == 1
    assert "biblioteca" in resuelto.nota


def test_un_registro_sin_doi_no_se_pregunta(cliente_falso):
    cliente = cliente_falso([])

    salida = resolver_incluidos([decision(doi="NR")], cliente, CORREO)

    assert salida.resueltos["R0001"].estado == ESTADO_SIN_DOI
    assert salida.sin_doi == 1
    assert salida.consultados == 0
    assert cliente.urls == []


def test_un_fallo_de_red_en_un_doi_no_tumba_la_tanda(cliente_falso):
    cliente = cliente_falso(
        [
            ErrorHttpServidor("El servidor respondió 503", url="x", estado=503),
            respuesta_abierta(),
        ]
    )

    salida = resolver_incluidos(
        [decision("R0001"), decision("R0002")], cliente, CORREO
    )

    assert salida.resueltos["R0001"].estado == ESTADO_DESCONOCIDO
    assert salida.resueltos["R0002"].esta_abierto
    assert salida.desconocidos == 1
    assert len(salida.incidencias) == 1
    assert "R0001" in salida.incidencias[0]


def test_sin_correo_se_corta_en_seco(cliente_falso):
    """Unpaywall lo exige: seguir preguntando sin correo es gastar por nada."""
    with pytest.raises(ErrorConfig):
        resolver_incluidos([decision()], cliente_falso([]), correo="")


def test_solo_se_pregunta_una_vez_por_doi(cliente_falso):
    """La caché: mil artículos son mil peticiones a un servicio gratuito."""
    cliente = cliente_falso([respuesta_abierta()])
    primera = resolver_incluidos([decision()], cliente, CORREO)

    cliente_nuevo = cliente_falso([])
    segunda = resolver_incluidos(
        [decision()], cliente_nuevo, CORREO, resueltos=primera.resueltos
    )

    assert segunda.reutilizados == 1
    assert segunda.consultados == 0
    assert cliente_nuevo.urls == []
    assert segunda.abiertos == 1


def test_con_rehacer_se_vuelve_a_preguntar(cliente_falso):
    cliente = cliente_falso([respuesta_abierta()])
    primera = resolver_incluidos([decision()], cliente, CORREO)

    cliente_nuevo = cliente_falso([respuesta_abierta("https://otra.invalid/x.pdf")])
    segunda = resolver_incluidos(
        [decision()],
        cliente_nuevo,
        CORREO,
        resueltos=primera.resueltos,
        rehacer=True,
    )

    assert segunda.consultados == 1
    assert segunda.resueltos["R0001"].oa_url == "https://otra.invalid/x.pdf"


def test_el_avance_se_avisa_por_registro(cliente_falso):
    cliente = cliente_falso([respuesta_abierta(), respuesta_cerrada()])
    avisos = []

    resolver_incluidos(
        [decision("R0001"), decision("R0002")],
        cliente,
        CORREO,
        avance=lambda i, t, r: avisos.append((i, t, r.identificador)),
    )

    assert avisos == [(1, 2, "R0001"), (2, 2, "R0002")]


def test_el_resumen_avisa_de_los_que_hay_que_pedir_a_mano(cliente_falso):
    cliente = cliente_falso([respuesta_cerrada()])

    salida = resolver_incluidos([decision()], cliente, CORREO)

    assert "no elude" in salida.resumen()
    assert "por-conseguir.md" in salida.resumen()


# ---------------------------------------------------------------------------
# El archivo
# ---------------------------------------------------------------------------


def test_lo_resuelto_se_guarda_y_se_vuelve_a_leer(tmp_path, cliente_falso):
    salida = resolver_incluidos(
        [decision()], cliente_falso([respuesta_abierta()]), CORREO
    )
    ruta = tmp_path / NOMBRE_TEXTO_COMPLETO

    guardar_resueltos(ruta, salida.resueltos)
    leidos = leer_resueltos(ruta)

    assert leidos["R0001"].oa_url == salida.resueltos["R0001"].oa_url
    assert leidos["R0001"].licencia == "cc-by"
    assert leidos["R0001"].esta_abierto
    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    assert guardado["fuente"] == "Unpaywall"


def test_leer_lo_que_no_existe_no_es_un_error(tmp_path):
    assert leer_resueltos(tmp_path / "no_existe.json") == {}


def test_una_cache_rota_se_recalcula(tmp_path):
    """Es una caché: lo único que se pierde son unas peticiones."""
    ruta = tmp_path / NOMBRE_TEXTO_COMPLETO
    ruta.write_text("{roto", encoding="utf-8")

    assert leer_resueltos(ruta) == {}


# ---------------------------------------------------------------------------
# Escribir la URL en el registro
# ---------------------------------------------------------------------------


def test_la_url_se_escribe_en_todas_las_copias_del_articulo():
    """`registros.json` viene con duplicados: el enlace es la clave de dedup."""
    registros = [
        {"doi": "10.1234/abierto", "titulo": "Uno", "oa_url": "NR"},
        {"doi": "https://doi.org/10.1234/ABIERTO", "titulo": "Uno bis", "oa_url": "NR"},
        {"doi": "10.9999/otro", "titulo": "Otro", "oa_url": "NR"},
    ]
    resueltos = {
        "R0001": Resuelto(
            identificador="R0001",
            doi="10.1234/abierto",
            estado=ESTADO_ABIERTO,
            oa_url="https://repositorio.invalid/uno.pdf",
        )
    }
    asignaciones = {"doi:10.1234/abierto": "R0001", "doi:10.9999/otro": "R0002"}

    cambiados = aplicar_a_registros(registros, resueltos, asignaciones)

    assert cambiados == 2
    assert registros[0]["oa_url"] == "https://repositorio.invalid/uno.pdf"
    assert registros[1]["oa_url"] == "https://repositorio.invalid/uno.pdf"
    assert registros[2]["oa_url"] == "NR"


def test_un_registro_cerrado_no_pisa_el_oa_url():
    registros = [{"doi": "10.1234/x", "titulo": "Uno", "oa_url": "NR"}]
    resueltos = {
        "R0001": Resuelto(identificador="R0001", doi="10.1234/x", estado=ESTADO_CERRADO)
    }

    cambiados = aplicar_a_registros(registros, resueltos, {"doi:10.1234/x": "R0001"})

    assert cambiados == 0
    assert registros[0]["oa_url"] == "NR"


def test_aplicar_dos_veces_no_cuenta_cambios_de_mas():
    registros = [{"doi": "10.1234/x", "titulo": "Uno", "oa_url": "NR"}]
    resueltos = {
        "R0001": Resuelto(
            identificador="R0001",
            doi="10.1234/x",
            estado=ESTADO_ABIERTO,
            oa_url="https://x.invalid/a.pdf",
        )
    }
    asignaciones = {"doi:10.1234/x": "R0001"}

    assert aplicar_a_registros(registros, resueltos, asignaciones) == 1
    assert aplicar_a_registros(registros, resueltos, asignaciones) == 0


def test_solo_se_toca_el_oa_url():
    """Lo demás de `registros.json` se queda como vino de la cosecha."""
    registros = [
        {"doi": "10.1234/x", "titulo": "Uno", "anio": 2020, "oa_url": "NR", "citas": 7}
    ]
    resueltos = {
        "R0001": Resuelto(
            identificador="R0001",
            doi="10.1234/x",
            estado=ESTADO_ABIERTO,
            oa_url="https://x.invalid/a.pdf",
        )
    }

    aplicar_a_registros(registros, resueltos, {"doi:10.1234/x": "R0001"})

    assert registros[0] == {
        "doi": "10.1234/x",
        "titulo": "Uno",
        "anio": 2020,
        "oa_url": "https://x.invalid/a.pdf",
        "citas": 7,
    }
