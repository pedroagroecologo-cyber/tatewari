"""Capa HTTP: reintentos y fallo limpio. Sin red y sin esperas reales."""

from __future__ import annotations

import pytest
import requests

from tatewari.http import (
    ClienteHttp,
    ErrorHttp,
    ErrorHttpCliente,
    ErrorHttpServidor,
    ErrorRed,
)

URL = "https://api.openalex.org/works?filter=x"


class RespuestaFalsa:
    def __init__(self, estado: int, datos=None, cabeceras=None, texto_roto=False):
        self.status_code = estado
        self._datos = datos if datos is not None else {"ok": True}
        self.headers = cabeceras or {}
        self._texto_roto = texto_roto

    def json(self):
        if self._texto_roto:
            raise ValueError("Expecting value: line 1 column 1")
        return self._datos


class SesionFalsa:
    """Doble de `requests.Session` que devuelve respuestas de una cola."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.urls = []
        self.headers = {}

    def get(self, url, timeout=None):
        self.urls.append(url)
        siguiente = self.respuestas.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente


def cliente_con(respuestas, **extra):
    """Cliente que no duerme de verdad: apunta las esperas y sigue."""
    esperado = []
    cliente = ClienteHttp(
        sesion=SesionFalsa(respuestas),
        dormir=esperado.append,
        espera_base=1.0,
        **extra,
    )
    return cliente


def test_una_respuesta_correcta_devuelve_el_json():
    cliente = cliente_con([RespuestaFalsa(200, {"meta": {"count": 1}})])

    assert cliente.obtener_json(URL) == {"meta": {"count": 1}}


def test_reintenta_ante_un_429_y_acaba_bien():
    cliente = cliente_con([RespuestaFalsa(429), RespuestaFalsa(200, {"ok": 1})])

    assert cliente.obtener_json(URL) == {"ok": 1}
    assert len(cliente.sesion.urls) == 2
    assert cliente.esperas == [1.0]


def test_reintenta_ante_un_500_con_espera_creciente():
    cliente = cliente_con(
        [RespuestaFalsa(500), RespuestaFalsa(503), RespuestaFalsa(200, {"ok": 1})]
    )

    assert cliente.obtener_json(URL) == {"ok": 1}
    # 1 s, luego 2 s: la espera crece.
    assert cliente.esperas == [1.0, 2.0]


def test_respeta_la_cabecera_retry_after():
    cliente = cliente_con(
        [RespuestaFalsa(429, cabeceras={"Retry-After": "7"}), RespuestaFalsa(200)]
    )

    cliente.obtener_json(URL)

    assert cliente.esperas == [7.0]


def test_un_retry_after_con_fecha_no_rompe_nada():
    cliente = cliente_con(
        [
            RespuestaFalsa(429, cabeceras={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
            RespuestaFalsa(200),
        ]
    )

    cliente.obtener_json(URL)

    assert cliente.esperas == [1.0]


def test_un_4xx_no_se_reintenta():
    """Repetir una petición mal construida solo gasta la cuota del servicio."""
    cliente = cliente_con([RespuestaFalsa(400)])

    with pytest.raises(ErrorHttpCliente) as capturado:
        cliente.obtener_json(URL)

    assert capturado.value.estado == 400
    assert len(cliente.sesion.urls) == 1
    assert cliente.esperas == []


def test_agotar_los_reintentos_acaba_en_error_de_servidor():
    cliente = cliente_con([RespuestaFalsa(503)] * 4, intentos=4)

    with pytest.raises(ErrorHttpServidor) as capturado:
        cliente.obtener_json(URL)

    assert capturado.value.estado == 503
    assert len(cliente.sesion.urls) == 4
    assert len(cliente.esperas) == 3


def test_un_fallo_de_red_se_reintenta_y_acaba_en_error_de_red():
    cliente = cliente_con([requests.ConnectionError("sin ruta al host")] * 4, intentos=4)

    with pytest.raises(ErrorRed) as capturado:
        cliente.obtener_json(URL)

    assert "No se pudo conectar" in str(capturado.value)
    assert capturado.value.url == URL


def test_una_espera_agotada_tambien_se_reintenta():
    cliente = cliente_con([requests.Timeout("agotado"), RespuestaFalsa(200, {"ok": 1})])

    assert cliente.obtener_json(URL) == {"ok": 1}


def test_una_respuesta_que_no_es_json_falla_sin_reintentar():
    cliente = cliente_con([RespuestaFalsa(200, texto_roto=True)])

    with pytest.raises(ErrorHttp) as capturado:
        cliente.obtener_json(URL)

    assert "no es JSON válido" in str(capturado.value)


def test_todos_los_fallos_previsibles_son_un_error_http():
    """Quien llama solo tiene que atrapar ErrorHttp para no tumbar la cosecha."""
    for excepciones in (ErrorHttpCliente, ErrorHttpServidor, ErrorRed):
        assert issubclass(excepciones, ErrorHttp)


def test_se_manda_un_user_agent_identificable():
    cliente = cliente_con([RespuestaFalsa(200)])

    assert "Tatewari/" in cliente.sesion.headers["User-Agent"]
