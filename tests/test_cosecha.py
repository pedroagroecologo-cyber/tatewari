"""Cosecha reanudable, bitácora y modos sin red."""

from __future__ import annotations

import json

import pytest

from tatewari.cosecha import (
    COLUMNAS_BITACORA,
    INTENTOS_MAXIMOS,
    Cosecha,
    ErrorCosecha,
    cargar_fixture,
)
from tatewari.fuentes import CAMPOS_REGISTRO, NR
from tatewari.http import Cuota, ErrorHttpServidor


@pytest.fixture
def cosecha(protocolo, config_temporal):
    return Cosecha(
        revision="demo", protocolo=protocolo, config=config_temporal, cliente=None
    )


# ---------------------------------------------------------------------------
# Plan y modo seco
# ---------------------------------------------------------------------------


def test_el_plan_tiene_una_ecuacion_por_par(cosecha, protocolo):
    ecuaciones = cosecha.ecuaciones()

    assert len(ecuaciones) == protocolo.numero_de_ecuaciones == 40
    assert ecuaciones[0].numero == 1
    assert ecuaciones[-1].numero == 40
    assert ecuaciones[0].base == "OpenAlex"


def test_el_modo_seco_no_toca_la_red_y_da_las_urls(cosecha):
    resumen = cosecha.plan_seco()

    assert resumen.seco
    assert resumen.total == 40
    assert len(resumen.ecuaciones) == 40
    for ecuacion in resumen.ecuaciones:
        assert ecuacion.url.startswith("https://api.openalex.org/works?")
    # No se ha escrito nada en disco.
    assert not cosecha.carpeta.exists()


def test_el_modo_seco_respeta_el_tope_si_se_pide(cosecha):
    resumen = cosecha.plan_seco(max_consultas=3)

    assert len(resumen.ecuaciones) == 3
    assert resumen.total == 40


def test_un_protocolo_sin_consulta_no_puede_cosecharse(
    protocolo_minimo, config_temporal
):
    from tatewari.protocolo import validar_protocolo

    sin_consulta = Cosecha(
        revision="x", protocolo=validar_protocolo(protocolo_minimo), config=config_temporal
    )

    with pytest.raises(ErrorCosecha) as capturado:
        sin_consulta.ecuaciones()

    assert "consulta" in str(capturado.value)


def test_una_fuente_desconocida_se_rechaza(protocolo, config_temporal):
    with pytest.raises(ErrorCosecha) as capturado:
        Cosecha("x", protocolo, config_temporal, fuente="scihub")

    assert "Fuente desconocida" in str(capturado.value)


# ---------------------------------------------------------------------------
# Modo fixture
# ---------------------------------------------------------------------------


def test_el_fixture_carga_los_catorce_registros(cosecha, ruta_fixture_demo):
    resumen = cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)

    assert resumen.procesadas == 1
    assert resumen.registros_nuevos == 14
    assert len(cosecha.leer_registros()) == 14
    assert resumen.pendientes == 39


def test_los_registros_del_fixture_conservan_el_contrato(cosecha, ruta_fixture_demo):
    cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)

    for registro in cosecha.leer_registros():
        assert set(registro) == set(CAMPOS_REGISTRO)


def test_el_fixture_solo_se_sirve_una_vez_por_lote(cosecha, ruta_fixture_demo):
    resumen = cosecha.ejecutar(max_consultas=3, fixture=ruta_fixture_demo)

    assert resumen.procesadas == 3
    assert resumen.registros_nuevos == 14

    filas = cosecha.leer_bitacora()
    assert filas[0]["resultados"] == "14"
    assert filas[1]["resultados"] == "0"
    assert "ya se sirvió" in filas[1]["observaciones"]


def test_cargar_fixture_admite_una_pagina_cruda_de_openalex(tmp_path, respuesta):
    ruta = tmp_path / "pagina.json"
    ruta.write_text(
        json.dumps(respuesta("openalex_pagina1.json")), encoding="utf-8"
    )

    registros = cargar_fixture(ruta)

    assert len(registros) == 2
    assert registros[0]["doi"] == "10.0000/sintetico.101"


def test_cargar_fixture_rellena_con_nr_lo_que_falte(tmp_path):
    ruta = tmp_path / "parcial.json"
    ruta.write_text(json.dumps([{"titulo": "Solo el título"}]), encoding="utf-8")

    registro = cargar_fixture(ruta)[0]

    assert registro["titulo"] == "Solo el título"
    assert registro["doi"] == NR
    assert registro["autores"] == [NR]


def test_un_fixture_que_no_existe_da_un_error_claro(cosecha, tmp_path):
    with pytest.raises(ErrorCosecha) as capturado:
        cosecha.ejecutar(fixture=tmp_path / "no_existe.json")

    assert "No existe el fixture" in str(capturado.value)


def test_un_fixture_con_forma_rara_se_rechaza(tmp_path):
    ruta = tmp_path / "raro.json"
    ruta.write_text('"esto es una cadena"', encoding="utf-8")

    with pytest.raises(ErrorCosecha):
        cargar_fixture(ruta)


# ---------------------------------------------------------------------------
# Bitácora
# ---------------------------------------------------------------------------


def test_la_bitacora_tiene_las_columnas_pedidas(cosecha, ruta_fixture_demo):
    cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)

    filas = cosecha.leer_bitacora()
    assert list(filas[0]) == list(COLUMNAS_BITACORA)


def test_la_bitacora_guarda_la_url_literal(cosecha, ruta_fixture_demo):
    """AGENTS.md, regla 3: sin la URL literal la búsqueda no es reproducible."""
    cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)

    fila = cosecha.leer_bitacora()[0]

    assert fila["url"].startswith("https://api.openalex.org/works?")
    assert "%22humedal%20artificial%22%20AND%20%22anaerobic%22" in fila["url"]
    assert fila["ecuacion"] == '"humedal artificial" AND "anaerobic"'
    assert fila["idiomas"] == "es|en"
    assert fila["ventana"] == "2016-2026"
    assert fila["base"] == "OpenAlex"
    assert fila["fecha"]


def test_la_bitacora_se_va_ampliando_entre_lotes(cosecha, ruta_fixture_demo):
    cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)
    cosecha.ejecutar(max_consultas=2, fixture=ruta_fixture_demo)

    filas = cosecha.leer_bitacora()

    assert [f["N"] for f in filas] == ["1", "2", "3"]
    # La cabecera se escribe una sola vez.
    texto = cosecha.ruta_bitacora.read_text(encoding="utf-8")
    assert texto.count("observaciones") == 1


def test_la_bitacora_no_deja_lineas_en_blanco_en_windows(cosecha, ruta_fixture_demo):
    """Sin newline="" el módulo csv escribe \\r\\r\\n y sale una línea de más."""
    cosecha.ejecutar(max_consultas=2, fixture=ruta_fixture_demo)

    crudo = cosecha.ruta_bitacora.read_bytes()

    assert b"\r\r\n" not in crudo


# ---------------------------------------------------------------------------
# Reanudación
# ---------------------------------------------------------------------------


def test_la_cosecha_continua_donde_se_quedo(cosecha, ruta_fixture_demo):
    primero = cosecha.ejecutar(max_consultas=2, fixture=ruta_fixture_demo)
    segundo = cosecha.ejecutar(max_consultas=2, fixture=ruta_fixture_demo)

    assert primero.pendientes == 38
    assert segundo.pendientes == 36
    assert [e.numero for e in segundo.ecuaciones] == [3, 4]


def test_el_estado_recuerda_lo_hecho(cosecha, ruta_fixture_demo):
    cosecha.ejecutar(max_consultas=2, fixture=ruta_fixture_demo)

    estado = cosecha.cargar_estado()

    assert estado["total_ecuaciones"] == 40
    assert sorted(estado["hechas"]) == ["1", "2"]
    assert estado["hechas"]["1"]["url"].startswith("https://api.openalex.org/")
    assert estado["fuente"] == "openalex"


def test_una_cosecha_nueva_arranca_de_cero(cosecha):
    estado = cosecha.cargar_estado()

    assert estado["hechas"] == {}
    assert estado["revision"] == "demo"


def test_el_lote_por_defecto_es_de_ocho(cosecha, ruta_fixture_demo):
    resumen = cosecha.ejecutar(fixture=ruta_fixture_demo)

    assert resumen.procesadas == 8
    assert resumen.pendientes == 32


def test_al_acabar_no_quedan_pendientes(cosecha, ruta_fixture_demo):
    resumen = cosecha.ejecutar(max_consultas=100, fixture=ruta_fixture_demo)

    assert resumen.procesadas == 40
    assert resumen.pendientes == 0
    assert "Cosecha completa" in resumen.resumen()


# ---------------------------------------------------------------------------
# Con la red simulada
# ---------------------------------------------------------------------------


def test_cosecha_contra_openalex_simulado(
    protocolo, config_temporal, cliente_falso, respuesta
):
    cliente = cliente_falso(
        [respuesta("openalex_pagina1.json"), respuesta("openalex_pagina2.json")]
    )
    cosecha = Cosecha("demo", protocolo, config_temporal, cliente=cliente)

    resumen = cosecha.ejecutar(max_consultas=1)

    assert resumen.procesadas == 1
    assert resumen.registros_nuevos == 3
    assert cosecha.leer_bitacora()[0]["resultados"] == "3"


def test_un_error_en_una_ecuacion_no_tumba_la_cosecha(
    protocolo, config_temporal, cliente_falso, respuesta
):
    """Se anota y se sigue con la siguiente."""
    cliente = cliente_falso(
        [
            ErrorHttpServidor("El servidor respondió 503", url="https://x", estado=503),
            respuesta("openalex_pagina2.json"),
        ]
    )
    cosecha = Cosecha("demo", protocolo, config_temporal, cliente=cliente)

    resumen = cosecha.ejecutar(max_consultas=2)

    assert resumen.procesadas == 2
    assert resumen.con_error == 1
    assert resumen.registros_nuevos == 1

    filas = cosecha.leer_bitacora()
    assert filas[0]["resultados"] == NR
    assert "503" in filas[0]["observaciones"]
    assert filas[1]["resultados"] == "1"


def test_sin_cliente_y_sin_modo_local_se_avisa(cosecha):
    with pytest.raises(ErrorCosecha) as capturado:
        cosecha.ejecutar(max_consultas=1)

    assert "--seco" in str(capturado.value)


def test_se_puede_cosechar_en_crossref(
    protocolo, config_temporal, cliente_falso, respuesta
):
    cliente = cliente_falso([respuesta("crossref_pagina1.json")])
    cosecha = Cosecha("demo", protocolo, config_temporal, fuente="crossref", cliente=cliente)

    resumen = cosecha.ejecutar(max_consultas=1)

    assert resumen.registros_nuevos == 2
    assert cosecha.leer_bitacora()[0]["base"] == "Crossref"
    assert "api.crossref.org" in cosecha.leer_bitacora()[0]["url"]


def test_los_registros_se_acumulan_con_sus_duplicados(cosecha, ruta_fixture_demo):
    """Deduplicar es otro encargo: aquí se guarda lo que vino."""
    cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)
    cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)

    assert len(cosecha.leer_registros()) == 28


# ---------------------------------------------------------------------------
# Reintentos
# ---------------------------------------------------------------------------


def _cliente_que_falla(cliente_falso, veces):
    return cliente_falso(
        [ErrorHttpServidor("503", url="https://x", estado=503) for _ in range(veces)]
    )


def test_sin_reintentar_una_ecuacion_fallida_no_se_repite(
    protocolo, config_temporal, cliente_falso
):
    cosecha = Cosecha(
        "demo", protocolo, config_temporal, cliente=_cliente_que_falla(cliente_falso, 1)
    )
    cosecha.ejecutar(max_consultas=1)

    cosecha._cliente = _cliente_que_falla(cliente_falso, 1)
    segundo = cosecha.ejecutar(max_consultas=1)

    assert [e.numero for e in segundo.ecuaciones] == [2]


def test_con_reintentar_la_ecuacion_fallida_vuelve_a_la_cola(
    protocolo, config_temporal, cliente_falso, respuesta
):
    cosecha = Cosecha(
        "demo", protocolo, config_temporal, cliente=_cliente_que_falla(cliente_falso, 1)
    )
    cosecha.ejecutar(max_consultas=1)

    cosecha._cliente = cliente_falso([respuesta("openalex_pagina2.json")])
    segundo = cosecha.ejecutar(max_consultas=1, reintentar=True)

    assert [e.numero for e in segundo.ecuaciones] == [1]
    assert segundo.registros_nuevos == 1
    assert cosecha.cargar_estado()["hechas"]["1"]["intentos"] == 2


def test_una_ecuacion_rota_no_atasca_la_cosecha_para_siempre(
    protocolo, config_temporal, cliente_falso
):
    """A los tres intentos se da por perdida y deja de volver a la cola."""
    cosecha = Cosecha("demo", protocolo, config_temporal)

    for _ in range(INTENTOS_MAXIMOS):
        cosecha._cliente = _cliente_que_falla(cliente_falso, 1)
        resumen = cosecha.ejecutar(max_consultas=1, reintentar=True)
        assert [e.numero for e in resumen.ecuaciones] == [1]

    assert resumen.perdidas == 1
    assert cosecha.cargar_estado()["hechas"]["1"]["intentos"] == INTENTOS_MAXIMOS
    assert "se da por perdida" in cosecha.leer_bitacora()[-1]["observaciones"]

    cosecha._cliente = _cliente_que_falla(cliente_falso, 1)
    siguiente = cosecha.ejecutar(max_consultas=1, reintentar=True)
    assert [e.numero for e in siguiente.ecuaciones] == [2]


def test_reintentar_no_toca_las_ecuaciones_que_salieron_bien(
    cosecha, ruta_fixture_demo
):
    cosecha.ejecutar(max_consultas=2, fixture=ruta_fixture_demo)

    segundo = cosecha.ejecutar(max_consultas=2, fixture=ruta_fixture_demo, reintentar=True)

    assert [e.numero for e in segundo.ecuaciones] == [3, 4]


# ---------------------------------------------------------------------------
# Cuota
# ---------------------------------------------------------------------------


class ClienteConCuota:
    """Cliente falso que va gastando cuota como hace OpenAlex."""

    def __init__(self, respuesta, restante, coste=10):
        self._respuesta = respuesta
        self.cuota = Cuota(limite=1000, restante=restante, coste=coste)
        self.urls = []

    def obtener_json(self, url):
        self.urls.append(url)
        self.cuota = Cuota(
            limite=1000,
            restante=max(0, self.cuota.restante - self.cuota.coste),
            coste=self.cuota.coste,
        )
        return self._respuesta


def test_la_cosecha_se_para_antes_de_agotar_la_cuota(
    protocolo, config_temporal, respuesta
):
    """Mejor parar entera que dejar una ecuacion a medias en la bitacora.

    Con 30 creditos y 10 por peticion caben 3 peticiones. Tras la primera
    ecuacion quedan 2, que no alcanzan para otra ecuacion de hasta 3 paginas,
    asi que se corta ahi en vez de empezar algo que no se puede terminar.
    """
    cliente = ClienteConCuota(respuesta("openalex_pagina2.json"), restante=30)
    cosecha = Cosecha("demo", protocolo, config_temporal, cliente=cliente)

    resumen = cosecha.ejecutar(max_consultas=8, max_paginas=3)

    assert resumen.detenido_por_cuota
    assert resumen.procesadas == 1
    assert resumen.pendientes == 39
    assert "poca cuota" in resumen.resumen()


def test_con_cuota_de_sobra_el_lote_entero_se_procesa(
    protocolo, config_temporal, respuesta
):
    cliente = ClienteConCuota(respuesta("openalex_pagina2.json"), restante=1000)
    cosecha = Cosecha("demo", protocolo, config_temporal, cliente=cliente)

    resumen = cosecha.ejecutar(max_consultas=3, max_paginas=1)

    assert not resumen.detenido_por_cuota
    assert resumen.procesadas == 3
    assert "Cuota: quedan" in resumen.resumen()


def test_una_fuente_sin_cuota_no_detiene_nada(
    protocolo, config_temporal, cliente_falso, respuesta
):
    cliente = cliente_falso([respuesta("openalex_pagina2.json")] * 3)
    cosecha = Cosecha("demo", protocolo, config_temporal, cliente=cliente)

    resumen = cosecha.ejecutar(max_consultas=3, max_paginas=1)

    assert not resumen.detenido_por_cuota
    assert resumen.procesadas == 3


# ---------------------------------------------------------------------------
# Resumenes ausentes y codificacion de la bitacora
# ---------------------------------------------------------------------------


def test_se_cuentan_los_registros_sin_resumen(cosecha, ruta_fixture_demo):
    """Dato operativo: en OpenAlex la mayoria de obras no traen resumen."""
    resumen = cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)

    assert resumen.registros_nuevos == 14
    assert resumen.sin_resumen == 1
    assert "sin resumen" in resumen.resumen()


def test_la_bitacora_lleva_bom_para_que_excel_la_abra_bien(cosecha, ruta_fixture_demo):
    """Unica excepcion documentada a la regla 8 de AGENTS.md."""
    cosecha.ejecutar(max_consultas=1, fixture=ruta_fixture_demo)

    crudo = cosecha.ruta_bitacora.read_bytes()

    assert crudo.startswith(b"\xef\xbb\xbf")
    # Y se relee sin que el BOM se cuele en el nombre de la primera columna.
    assert list(cosecha.leer_bitacora()[0])[0] == "N"


def test_los_acentos_de_la_bitacora_sobreviven(cosecha, ruta_fixture_demo):
    cosecha.ejecutar(max_consultas=2, fixture=ruta_fixture_demo)

    texto = cosecha.ruta_bitacora.read_text(encoding="utf-8-sig")

    assert "sirvió" in texto
