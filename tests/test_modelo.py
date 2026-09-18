"""Pruebas del cliente de Ollama. Sin red y **sin Ollama instalado**.

Todo sale del doble `SesionOllamaFalsa` de `conftest.py`. Ninguna prueba de este
archivo necesita que haya un modelo descargado, ni un servidor levantado
(AGENTS.md, regla 6).
"""

from __future__ import annotations

import pytest
import requests

from tatewari.modelo import (
    MODELO_SUGERIDO,
    NUM_CTX,
    ClienteOllama,
    ModeloInstalado,
    ModeloNoInstalado,
    OllamaNoResponde,
    SinModelosUtiles,
    elegir_modelo,
    leer_modelos,
    orden_de_preferencia,
)

# ---------------------------------------------------------------------------
# Leer /api/tags
# ---------------------------------------------------------------------------


def test_leer_modelos_saca_el_tamano_y_la_cuantizacion(tags_falsos):
    modelos = leer_modelos({"models": [tags_falsos("llama3.2:3b", "3.2B", "Q4_K_M")]})

    assert len(modelos) == 1
    modelo = modelos[0]
    assert modelo.nombre == "llama3.2:3b"
    assert modelo.tamano == 3.2
    assert modelo.cuantizacion == "Q4_K_M"
    assert modelo.es_cuatro_bits


def test_el_tamano_sale_de_la_etiqueta_si_ollama_no_lo_dice():
    """`llama3.2:3b` son 3B, no 3.2B: el tamaño está en la etiqueta, no en el nombre."""
    modelos = leer_modelos({"models": [{"name": "llama3.2:3b", "details": {}}]})

    assert modelos[0].tamano == 3.0


def test_un_tamano_desconocido_se_queda_desconocido():
    """AGENTS.md, regla 2: lo que no se sabe no se inventa."""
    modelos = leer_modelos({"models": [{"name": "modelo-raro"}]})

    assert modelos[0].tamano is None
    assert modelos[0].cuantizacion == "NR"


def test_leer_modelos_aguanta_una_respuesta_rara():
    assert leer_modelos(None) == ()
    assert leer_modelos({}) == ()
    assert leer_modelos({"models": "no es una lista"}) == ()
    assert leer_modelos({"models": [{"sin": "nombre"}]}) == ()


# ---------------------------------------------------------------------------
# Elegir el modelo con 4 GB de VRAM
# ---------------------------------------------------------------------------


def test_prefiere_un_3b_cuantizado_sobre_un_8b(tags_falsos):
    """La prueba que pide el encargo.

    Un 8B a 4 bits pesa unos 4,7 GB y no entra en 4 GB de VRAM: Ollama lo
    reparte con la RAM y la generación pasa de segundos a minutos.
    """
    modelos = leer_modelos(
        {
            "models": [
                tags_falsos("llama3.1:8b", "8.0B", "Q4_K_M", 4_900_000_000),
                tags_falsos("llama3.2:3b", "3.2B", "Q4_K_M", 2_000_000_000),
            ]
        }
    )

    assert elegir_modelo(modelos).nombre == "llama3.2:3b"


def test_el_orden_del_8b_es_el_ultimo(tags_falsos):
    """Da igual en qué orden los devuelva Ollama: el 8B va al final."""
    modelos = leer_modelos(
        {
            "models": [
                tags_falsos("pequeno:3b", "3.0B", "Q4_K_M"),
                tags_falsos("grande:8b", "8.0B", "Q4_K_M"),
                tags_falsos("enorme:70b", "70.0B", "Q4_K_M"),
            ]
        }
    )

    ordenados = [m.nombre for m in sorted(modelos, key=orden_de_preferencia)]

    assert ordenados[0] == "pequeno:3b"
    assert ordenados[-1] in ("grande:8b", "enorme:70b")
    assert "pequeno:3b" == elegir_modelo(modelos).nombre


def test_entre_dos_de_3b_gana_el_cuantizado_a_cuatro_bits(tags_falsos):
    modelos = leer_modelos(
        {
            "models": [
                tags_falsos("sin-cuantizar:3b", "3.2B", "F16", 6_400_000_000),
                tags_falsos("cuantizado:3b", "3.2B", "Q4_K_M", 2_000_000_000),
            ]
        }
    )

    assert elegir_modelo(modelos).nombre == "cuantizado:3b"


def test_un_3b_gana_a_un_1b(tags_falsos):
    """Los dos entran, pero el de 1B razona peor."""
    modelos = leer_modelos(
        {
            "models": [
                tags_falsos("diminuto:1b", "1.0B", "Q4_K_M"),
                tags_falsos("justo:3b", "3.2B", "Q4_K_M"),
            ]
        }
    )

    assert elegir_modelo(modelos).nombre == "justo:3b"


def test_un_modelo_general_gana_a_uno_de_codigo_aunque_sea_mayor(tags_falsos):
    """Aquí hay que leer un resumen en español, no escribir una función.

    Es el caso real de la máquina de referencia: con `qwen2.5-coder:3b` y
    `qwen3:4b` instalados, sin esta regla ganaba el de código por ser más
    pequeño.
    """
    modelos = leer_modelos(
        {
            "models": [
                tags_falsos("qwen2.5-coder:3b", "3.1B", "Q4_K_M"),
                tags_falsos("qwen3:4b", "4.0B", "Q4_K_M"),
            ]
        }
    )

    assert elegir_modelo(modelos).nombre == "qwen3:4b"


def test_un_modelo_de_codigo_se_usa_si_es_el_unico(tags_falsos):
    """Se penaliza, no se descarta: genera texto y puede responder."""
    modelos = leer_modelos({"models": [tags_falsos("qwen2.5-coder:3b", "3.1B")]})

    assert elegir_modelo(modelos).nombre == "qwen2.5-coder:3b"


def test_los_modelos_de_embeddings_no_se_eligen_nunca(tags_falsos):
    """No generan texto: pedirles una decisión devuelve un disparate."""
    modelos = leer_modelos(
        {
            "models": [
                tags_falsos("nomic-embed-text:latest", "137M", "F16"),
                tags_falsos("llama3.2:3b", "3.2B", "Q4_K_M"),
            ]
        }
    )

    assert elegir_modelo(modelos).nombre == "llama3.2:3b"


def test_solo_con_embeddings_se_planta_y_lo_explica(tags_falsos):
    modelos = leer_modelos({"models": [tags_falsos("nomic-embed-text:latest")]})

    with pytest.raises(SinModelosUtiles) as fallo:
        elegir_modelo(modelos)

    assert "embeddings" in str(fallo.value)
    assert "ollama pull" in str(fallo.value)


def test_sin_ningun_modelo_se_planta_y_dice_cual_descargar():
    with pytest.raises(SinModelosUtiles) as fallo:
        elegir_modelo([])

    assert f"ollama pull {MODELO_SUGERIDO}" in str(fallo.value)


def test_la_eleccion_no_depende_del_orden_de_la_respuesta(tags_falsos):
    """Dos máquinas con los mismos modelos tienen que elegir el mismo."""
    unos = [tags_falsos("a:3b", "3.0B"), tags_falsos("b:3b", "3.0B")]
    modelos = leer_modelos({"models": unos})
    alreves = leer_modelos({"models": list(reversed(unos))})

    assert elegir_modelo(modelos).nombre == elegir_modelo(alreves).nombre


def test_el_resumen_de_un_modelo_se_lee(tags_falsos):
    modelo = leer_modelos({"models": [tags_falsos("llama3.2:3b", "3.2B", "Q4_K_M")]})[0]

    assert "llama3.2:3b" in modelo.resumen()
    assert "3.2B" in modelo.resumen()
    assert "2.0 GB" in modelo.resumen()


def test_un_modelo_sin_tamano_lo_dice_en_su_resumen():
    assert "tamaño NR" in ModeloInstalado(nombre="raro").resumen()


# ---------------------------------------------------------------------------
# Cuando Ollama no está levantado
# ---------------------------------------------------------------------------


def test_si_ollama_no_responde_el_error_dice_exactamente_que_hacer(ollama):
    """El error más probable de todos, así que tiene que ser el más claro."""
    cliente, _ = ollama(
        modelos=[],
        respuestas=[],
    )
    cliente.cliente.sesion.get = _tumbar

    with pytest.raises(OllamaNoResponde) as fallo:
        cliente.instalados()

    mensaje = str(fallo.value)
    assert "ollama serve" in mensaje
    assert f"ollama pull {MODELO_SUGERIDO}" in mensaje
    assert "TATEWARI_OLLAMA" in mensaje
    assert "http://localhost:11434" in mensaje
    # Y deja claro que no hay plan B en la nube (AGENTS.md, regla 1).
    assert "nube" in mensaje


def _tumbar(url, timeout=None):
    raise requests.ConnectionError("[WinError 10061] No se pudo establecer conexión")


def test_si_ollama_se_cae_al_generar_tambien_se_explica(ollama, tags_falsos):
    cliente, sesion = ollama(
        modelos=[tags_falsos("llama3.2:3b")],
        respuestas=[
            requests.ConnectionError("se cayó"),
            requests.ConnectionError("sigue caído"),
        ],
    )

    with pytest.raises(OllamaNoResponde) as fallo:
        cliente.generar("hola")

    assert "ollama serve" in str(fallo.value)


# ---------------------------------------------------------------------------
# Forzar un modelo con --modelo
# ---------------------------------------------------------------------------


def test_forzar_un_modelo_que_no_esta_se_planta_antes_de_empezar(ollama, tags_falsos):
    """Mejor ahora que después de veinte minutos con un nombre mal escrito."""
    cliente, _ = ollama(
        modelos=[tags_falsos("llama3.2:3b")], modelo="llama3.2:3b-mal-escrito"
    )

    with pytest.raises(ModeloNoInstalado) as fallo:
        cliente.elegir()

    assert "ollama pull llama3.2:3b-mal-escrito" in str(fallo.value)
    assert "llama3.2:3b" in str(fallo.value)


def test_forzar_un_modelo_instalado_manda_sobre_la_eleccion(ollama, tags_falsos):
    cliente, _ = ollama(
        modelos=[
            tags_falsos("llama3.2:3b", "3.2B", "Q4_K_M"),
            tags_falsos("grande:8b", "8.0B", "Q4_K_M"),
        ],
        modelo="grande:8b",
    )

    assert cliente.elegir() == "grande:8b"


def test_vale_el_nombre_sin_etiqueta(ollama, tags_falsos):
    """Ollama admite «llama3.2» para «llama3.2:latest»."""
    cliente, _ = ollama(modelos=[tags_falsos("llama3.2:latest")], modelo="llama3.2")

    assert cliente.elegir() == "llama3.2"


# ---------------------------------------------------------------------------
# Generar
# ---------------------------------------------------------------------------


def test_la_generacion_va_con_temperatura_cero_y_num_ctx_explicito(
    ollama, tags_falsos
):
    """Sin `num_ctx` explícito, cada modelo usaría el suyo y el cribado dejaría
    de ser reproducible."""
    cliente, sesion = ollama(
        modelos=[tags_falsos("llama3.2:3b")], respuestas=["una respuesta"]
    )

    cliente.generar("un prompt")

    cuerpo = sesion.cuerpos[0]
    assert cuerpo["options"]["temperature"] == 0
    assert cuerpo["options"]["num_ctx"] == NUM_CTX
    assert cuerpo["stream"] is False
    assert cuerpo["model"] == "llama3.2:3b"
    assert cuerpo["prompt"] == "un prompt"


def test_la_generacion_pide_no_razonar(ollama, tags_falsos):
    """Un modelo de razonamiento con `think` deja `response` vacío.

    Medido con `qwen3:4b`: la respuesta entera se iba al campo `thinking`.
    """
    cliente, sesion = ollama(
        modelos=[tags_falsos("llama3.2:3b")], respuestas=["vale"]
    )

    cliente.generar("un prompt")

    assert sesion.cuerpos[0]["think"] is False


def test_el_formato_json_solo_se_pide_cuando_se_pide(ollama, tags_falsos):
    cliente, sesion = ollama(
        modelos=[tags_falsos("llama3.2:3b")], respuestas=["a", "b"]
    )

    cliente.generar("sin formato")
    cliente.generar("con formato", formato_json=True)

    assert "format" not in sesion.cuerpos[0]
    assert sesion.cuerpos[1]["format"] == "json"


def test_la_generacion_devuelve_el_texto_y_el_tiempo(ollama, tags_falsos):
    cliente, _ = ollama(
        modelos=[tags_falsos("llama3.2:3b")], respuestas=["la respuesta"]
    )

    generacion = cliente.generar("hola")

    assert generacion.texto == "la respuesta"
    assert generacion.modelo == "llama3.2:3b"
    assert generacion.duracion == pytest.approx(1.5)
    assert generacion.tokens == 20


def test_si_response_viene_vacio_se_lee_thinking(ollama, tags_falsos):
    """Red de seguridad para un Ollama que ignore `think: False`."""
    cliente, _ = ollama(
        modelos=[tags_falsos("llama3.2:3b")],
        respuestas=[
            {
                "response": "",
                "thinking": '{"decision": "incluir"}',
                "model": "llama3.2:3b",
            }
        ],
    )

    generacion = cliente.generar("hola")

    assert generacion.texto == '{"decision": "incluir"}'


def test_los_modelos_se_preguntan_una_sola_vez(ollama, tags_falsos):
    """`/api/tags` no cambia a media revisión y preguntarlo por registro sobra."""
    cliente, sesion = ollama(
        modelos=[tags_falsos("llama3.2:3b")], respuestas=["a", "b", "c"]
    )

    cliente.generar("uno")
    cliente.generar("dos")
    cliente.generar("tres")

    assert sesion.veces_tags == 1


def test_todo_el_cribado_lo_decide_el_mismo_modelo(ollama, tags_falsos):
    """Aunque Ollama descargue otro por el camino, la elección ya está tomada."""
    cliente, sesion = ollama(
        modelos=[tags_falsos("llama3.2:3b")], respuestas=["a", "b"]
    )

    primero = cliente.elegir()
    sesion.modelos.append(tags_falsos("otro:3b", "3.0B", "Q4_K_M"))

    assert cliente.elegir() == primero


def test_el_resumen_dice_donde_esta_ollama_y_con_que_va_a_decidir(
    ollama, tags_falsos
):
    cliente, _ = ollama(
        modelos=[
            tags_falsos("llama3.2:3b", "3.2B", "Q4_K_M"),
            tags_falsos("grande:8b", "8.0B", "Q4_K_M"),
        ]
    )

    resumen = cliente.resumen()

    assert "http://localhost:11434" in resumen
    assert "llama3.2:3b" in resumen
    assert "temperatura 0" in resumen
    assert "grande:8b" in resumen  # aparece como «otros»


def test_la_direccion_se_toma_de_la_configuracion(config_temporal):
    from dataclasses import replace

    config = replace(config_temporal, ollama="http://192.168.1.50:11434/")

    cliente = ClienteOllama.desde_config(config)

    assert cliente.direccion == "http://192.168.1.50:11434"
    assert cliente.url_tags == "http://192.168.1.50:11434/api/tags"
    assert cliente.url_generar == "http://192.168.1.50:11434/api/generate"
