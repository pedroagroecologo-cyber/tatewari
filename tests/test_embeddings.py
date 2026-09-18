"""Pruebas de la búsqueda por parecido. Sin red y **sin modelo de embeddings**.

Los vectores salen del doble `SesionOllamaFalsa`, con valores fijos que las
pruebas eligen: así el orden por similitud se puede comprobar de verdad, y no
«sale algo y parece razonable».
"""

from __future__ import annotations

import json
from hashlib import sha256

import pytest

from tatewari.cribado import Decision
from tatewari.embeddings import (
    MODELO_EMBED_POR_DEFECTO,
    RUTA_EMBED,
    RUTA_EMBEDDINGS,
    UMBRAL_CASI_DUPLICADO,
    Almacen,
    EmbeddingsNoDisponibles,
    ModeloEmbedNoInstalado,
    Vector,
    casi_duplicados,
    coseno,
    hash_de_texto,
    mas_parecidos,
    ordenar_por_parecido,
    texto_de_registro,
    vectorizar,
)


def registro(identificador="R0001", titulo="Un título", resumen="Un resumen", **extra):
    base = {
        "identificador": identificador,
        "doi": f"10.1234/{identificador.lower()}",
        "titulo": titulo,
        "anio": 2020,
        "idioma": "es",
        "revista": "NR",
        "autores": ["NR"],
        "resumen": resumen,
        "tipo": "article",
        "citas": "NR",
        "oa_url": "NR",
    }
    base.update(extra)
    return base


def decision(identificador="R0001", **campos):
    """Una `Decision` de mentira, con lo que necesitan estas funciones."""
    return Decision(
        identificador=identificador,
        decision=campos.pop("decision", "incluir"),
        motivo="da igual",
        registro=registro(identificador, **campos),
    )


def vector_tematico(texto: str) -> list[float]:
    """Tres ejes: humedal, anaerobio y ciclo de vida, más una base constante.

    La base evita que un registro sin ninguno de los tres temas salga con el
    vector nulo, que no se puede comparar con nada.
    """
    minusculas = texto.lower()
    return [
        1.0 if ("humedal" in minusculas or "wetland" in minusculas) else 0.0,
        1.0
        if ("anaerobi" in minusculas or "uasb" in minusculas or "séptico" in minusculas)
        else 0.0,
        1.0 if ("life cycle" in minusculas or "ciclo de vida" in minusculas) else 0.0,
        0.1,
    ]


def vectores_unicos(pareja: tuple[str, ...] = ()):
    """Da a cada texto su propio eje, salvo a los de `pareja`, que comparten uno.

    Así se puede comprobar la detección de casi duplicados sabiendo exactamente
    qué par tiene que salir y que ningún otro se le acerca.
    """
    asignados: dict[str, int] = {}

    def vector_de(texto: str) -> list[float]:
        base = [0.0] * 24
        if any(marca in texto for marca in pareja):
            base[0] = 1.0
            return base
        if texto not in asignados:
            asignados[texto] = len(asignados) + 1
        base[asignados[texto] % 24] = 1.0
        return base

    return vector_de


# ---------------------------------------------------------------------------
# Qué se vectoriza
# ---------------------------------------------------------------------------


def test_se_vectoriza_titulo_mas_resumen():
    texto, baja = texto_de_registro(registro(titulo="El título", resumen="El resumen"))

    assert "El título" in texto
    assert "El resumen" in texto
    assert baja is False


def test_sin_resumen_solo_el_titulo_y_el_vector_es_de_baja_calidad():
    """Un título son diez palabras y un resumen doscientas: no valen lo mismo."""
    texto, baja = texto_de_registro(registro(titulo="El título", resumen="NR"))

    assert texto == "El título"
    assert baja is True


def test_el_hash_cambia_con_el_texto():
    assert hash_de_texto("uno") != hash_de_texto("otro")
    assert hash_de_texto("uno") == hash_de_texto("uno")


# ---------------------------------------------------------------------------
# El coseno
# ---------------------------------------------------------------------------


def test_el_coseno_de_dos_vectores_iguales_es_uno():
    assert coseno([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)


def test_el_coseno_no_depende_de_la_escala():
    assert coseno([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)


def test_el_coseno_de_dos_ortogonales_es_cero():
    assert coseno([1, 0], [0, 1]) == pytest.approx(0.0)


def test_un_vector_nulo_no_revienta_el_coseno():
    assert coseno([0, 0], [1, 1]) == 0.0
    assert coseno([], [1, 1]) == 0.0


# ---------------------------------------------------------------------------
# Los endpoints
# ---------------------------------------------------------------------------


def test_usa_el_endpoint_nuevo_con_el_lote_entero(embeddings):
    cliente, sesion = embeddings()

    vectores = cliente.vectores(["uno", "dos", "tres"])

    assert len(vectores) == 3
    assert cliente.ruta_usada == RUTA_EMBED
    # Una sola petición para los tres.
    posts = [u for m, u, _ in sesion.peticiones if m == "POST"]
    assert posts == [f"http://localhost:11434{RUTA_EMBED}"]


def test_si_la_ruta_nueva_no_existe_usa_la_vieja(embeddings):
    """Ollama cambió de sitio los embeddings; hay versiones con solo la vieja."""
    cliente, sesion = embeddings(soporta_embed=False)

    vectores = cliente.vectores(["uno", "dos"])

    assert len(vectores) == 2
    assert cliente.ruta_usada == RUTA_EMBEDDINGS
    assert sesion.textos_vectorizados == ["uno", "dos"]


def test_el_endpoint_se_descubre_una_sola_vez(embeddings):
    cliente, sesion = embeddings(soporta_embed=False)

    cliente.vectores(["uno"])
    cliente.vectores(["dos"])

    # Un único intento contra la ruta nueva, el primero.
    intentos = [u for _, u, _ in sesion.peticiones if u.endswith(RUTA_EMBED)]
    assert len(intentos) == 1


def test_el_texto_no_se_vectoriza_dos_veces_al_descubrir_la_ruta(embeddings):
    """Probar el endpoint aparte gastaría una vectorización en cada corrida."""
    cliente, sesion = embeddings()

    cliente.vectores(["uno"])

    assert sesion.textos_vectorizados == ["uno"]


# ---------------------------------------------------------------------------
# Cuando el modelo no está: la capa es opcional
# ---------------------------------------------------------------------------


def test_si_el_modelo_no_esta_descargado_el_mensaje_dice_que_hacer(embeddings):
    cliente, _ = embeddings(instalado=False)

    with pytest.raises(ModeloEmbedNoInstalado) as fallo:
        cliente.vectores(["uno"])

    mensaje = str(fallo.value)
    assert f"ollama pull {MODELO_EMBED_POR_DEFECTO}" in mensaje
    # Y deja claro que el resto de Tatewari no depende de esto.
    assert "opcional" in mensaje
    assert "llama3.2:3b" in mensaje  # dice qué modelos sí hay


def test_se_comprueba_el_modelo_antes_de_pedir_un_solo_vector(embeddings):
    """Fallar en el primer segundo, no a mitad de la vectorización."""
    cliente, sesion = embeddings(instalado=False)

    with pytest.raises(ModeloEmbedNoInstalado):
        cliente.vectores(["uno"])

    assert sesion.textos_vectorizados == []


def test_un_modelo_generativo_no_sirve_y_se_explica(embeddings):
    """Ollama responde 501 «does not support embeddings». Medido de verdad."""
    cliente, _ = embeddings(sin_soporte=True)

    with pytest.raises(EmbeddingsNoDisponibles) as fallo:
        cliente.vectores(["uno"])

    mensaje = str(fallo.value)
    assert "no sabe generar" in mensaje
    assert f"ollama pull {MODELO_EMBED_POR_DEFECTO}" in mensaje


def test_una_respuesta_sin_vectores_se_dice_claro(embeddings):
    cliente, sesion = embeddings()
    sesion.vector_de = lambda texto: []

    with pytest.raises(EmbeddingsNoDisponibles):
        cliente.vectores(["uno"])


# ---------------------------------------------------------------------------
# La caché
# ---------------------------------------------------------------------------


def test_la_cache_evita_volver_a_pedir_un_texto_que_no_cambio(tmp_path, embeddings):
    """La prueba de la caché: vectorizar es lo caro y no se repite."""
    cliente, sesion = embeddings()
    registros = [registro(f"R000{n}", titulo=f"Título {n}") for n in (1, 2, 3)]
    ruta = tmp_path / "vectores.json"

    primero = Almacen.leer(ruta, cliente.modelo)
    salida = vectorizar(registros, cliente, primero, lote=2)
    primero.guardar()

    assert salida.calculados == 3
    assert salida.reutilizados == 0
    assert len(sesion.textos_vectorizados) == 3

    # Segunda corrida: nada cambió, así que no se pide ni un vector más.
    sesion.textos_vectorizados.clear()
    segundo = Almacen.leer(ruta, cliente.modelo)
    otra = vectorizar(registros, cliente, segundo, lote=2)

    assert otra.calculados == 0
    assert otra.reutilizados == 3
    assert sesion.textos_vectorizados == []


def test_si_cambia_el_texto_se_recalcula_solo_ese(tmp_path, embeddings):
    cliente, sesion = embeddings()
    registros = [registro(f"R000{n}", titulo=f"Título {n}") for n in (1, 2, 3)]
    ruta = tmp_path / "vectores.json"
    almacen = Almacen.leer(ruta, cliente.modelo)
    vectorizar(registros, cliente, almacen, lote=8)
    almacen.guardar()
    sesion.textos_vectorizados.clear()

    # Al segundo registro le llega el resumen que faltaba.
    registros[1] = registro("R0002", titulo="Título 2", resumen="Ahora sí hay resumen")
    otro = Almacen.leer(ruta, cliente.modelo)
    salida = vectorizar(registros, cliente, otro, lote=8)

    assert salida.calculados == 1
    assert salida.reutilizados == 2
    assert len(sesion.textos_vectorizados) == 1
    assert "Ahora sí hay resumen" in sesion.textos_vectorizados[0]


def test_cambiar_de_modelo_descarta_la_cache_entera(tmp_path, embeddings):
    """Los vectores de dos modelos no son comparables: mezclarlos da un orden
    con toda la pinta de estar bien y sin ningún sentido."""
    cliente, _ = embeddings()
    registros = [registro("R0001")]
    ruta = tmp_path / "vectores.json"
    almacen = Almacen.leer(ruta, cliente.modelo)
    vectorizar(registros, cliente, almacen, lote=8)
    almacen.guardar()

    otro = Almacen.leer(ruta, "otro-modelo-de-embeddings")

    assert otro.vectores == {}
    assert "no son comparables" in otro.descartada


def test_la_cache_guarda_el_modelo_y_la_dimension(tmp_path, embeddings):
    cliente, _ = embeddings()
    almacen = Almacen.leer(tmp_path / "vectores.json", cliente.modelo)
    vectorizar([registro("R0001")], cliente, almacen, lote=8)

    ruta = almacen.guardar()
    guardado = json.loads(ruta.read_text(encoding="utf-8"))

    assert guardado["modelo"] == MODELO_EMBED_POR_DEFECTO
    assert guardado["dimension"] == 8
    assert guardado["vectores"]["R0001"]["hash"]
    assert len(guardado["vectores"]["R0001"]["vector"]) == 8


def test_una_cache_ilegible_se_recalcula_sin_quejarse(tmp_path, embeddings):
    """Es lo único del proyecto que se puede tirar sin perder información."""
    ruta = tmp_path / "vectores.json"
    ruta.write_text("{esto no es json", encoding="utf-8")

    almacen = Almacen.leer(ruta, MODELO_EMBED_POR_DEFECTO)

    assert almacen.vectores == {}
    assert almacen.descartada


def test_los_vectores_de_baja_calidad_se_cuentan(tmp_path, embeddings):
    cliente, _ = embeddings()
    registros = [
        registro("R0001", resumen="Con resumen"),
        registro("R0002", resumen="NR"),
    ]
    almacen = Almacen.leer(tmp_path / "vectores.json", cliente.modelo)

    salida = vectorizar(registros, cliente, almacen, lote=8)

    assert salida.baja_calidad == 1
    assert almacen.vectores["R0002"].baja_calidad is True
    assert almacen.vectores["R0001"].baja_calidad is False
    assert "baja calidad" in salida.resumen()


def test_un_registro_sin_titulo_ni_resumen_no_se_inventa_un_vector(
    tmp_path, embeddings
):
    """AGENTS.md, regla 2: se queda fuera del parecido, no con un vector falso."""
    cliente, _ = embeddings()
    almacen = Almacen.leer(tmp_path / "vectores.json", cliente.modelo)

    salida = vectorizar(
        [registro("R0001", titulo="NR", resumen="NR")], cliente, almacen, lote=8
    )

    assert salida.total == 0
    assert almacen.vectores == {}


def test_el_avance_se_avisa_por_lotes(tmp_path, embeddings):
    cliente, _ = embeddings()
    registros = [registro(f"R{n:04d}") for n in range(1, 6)]
    almacen = Almacen.leer(tmp_path / "vectores.json", cliente.modelo)
    avisos: list[tuple[int, int, int]] = []

    vectorizar(registros, cliente, almacen, lote=2, avance=lambda *a: avisos.append(a))

    assert avisos == [(2, 5, 2), (4, 5, 2), (5, 5, 1)]


# ---------------------------------------------------------------------------
# a) Ordenar por la pregunta de investigación
# ---------------------------------------------------------------------------


@pytest.fixture
def tres_registros(tmp_path, embeddings):
    """Tres registros con vectores temáticos conocidos, ya vectorizados."""
    cliente, sesion = embeddings(vector_de=vector_tematico)
    decisiones = [
        decision(
            "R0001",
            titulo="Humedal artificial precedido de reactor anaerobio UASB",
            resumen="Trata agua residual.",
        ),
        decision(
            "R0002",
            titulo="Humedal artificial de flujo vertical",
            resumen="Trata agua residual.",
        ),
        decision(
            "R0003",
            titulo="Life cycle assessment of activated sludge",
            resumen="Nada que ver.",
        ),
    ]
    almacen = Almacen.leer(tmp_path / "vectores.json", cliente.modelo)
    vectorizar([d.registro for d in decisiones], cliente, almacen, lote=8)
    return decisiones, almacen, cliente


def test_ordena_por_cercania_a_la_pregunta(tres_registros):
    """La prueba del orden: el que toca los dos temas de la pregunta va primero."""
    decisiones, almacen, _ = tres_registros
    pregunta = vector_tematico("humedal artificial con reactor anaerobio")

    parecidos = ordenar_por_parecido(decisiones, almacen, pregunta)

    assert [p.identificador for p in parecidos] == ["R0001", "R0002", "R0003"]
    assert parecidos[0].similitud > parecidos[1].similitud > parecidos[2].similitud
    assert parecidos[0].similitud == pytest.approx(1.0)


def test_una_pregunta_de_otro_tema_cambia_el_orden(tres_registros):
    decisiones, almacen, _ = tres_registros
    pregunta = vector_tematico("análisis de ciclo de vida")

    parecidos = ordenar_por_parecido(decisiones, almacen, pregunta)

    assert parecidos[0].identificador == "R0003"


def test_a_igual_similitud_el_orden_es_estable(tres_registros):
    """Dos corridas con los mismos datos dan el mismo orden."""
    decisiones, almacen, _ = tres_registros
    pregunta = vector_tematico("humedal")

    uno = ordenar_por_parecido(decisiones, almacen, pregunta)
    otro = ordenar_por_parecido(list(reversed(decisiones)), almacen, pregunta)

    assert [p.identificador for p in uno] == [p.identificador for p in otro]


def test_un_registro_sin_vector_no_sale_en_el_orden(tres_registros):
    decisiones, almacen, _ = tres_registros
    decisiones.append(decision("R0099"))

    parecidos = ordenar_por_parecido(decisiones, almacen, vector_tematico("humedal"))

    assert "R0099" not in [p.identificador for p in parecidos]


def test_una_pregunta_con_vector_nulo_no_ordena_nada(tres_registros):
    decisiones, almacen, _ = tres_registros

    assert ordenar_por_parecido(decisiones, almacen, [0.0, 0.0, 0.0, 0.0]) == []


# ---------------------------------------------------------------------------
# b) Los parecidos a uno dado
# ---------------------------------------------------------------------------


def test_los_parecidos_a_uno_dado_no_se_incluyen_a_si_mismo(tres_registros):
    decisiones, almacen, _ = tres_registros

    parecidos = mas_parecidos("R0001", decisiones, almacen, cuantos=10)

    assert "R0001" not in [p.identificador for p in parecidos]
    assert parecidos[0].identificador == "R0002"


def test_los_parecidos_respetan_el_cuantos(tres_registros):
    decisiones, almacen, _ = tres_registros

    assert len(mas_parecidos("R0001", decisiones, almacen, cuantos=1)) == 1
    assert len(mas_parecidos("R0001", decisiones, almacen, cuantos=0)) == 0


def test_pedir_los_parecidos_de_un_registro_sin_vector_falla(tres_registros):
    """Es distinto de «no se parece a nada», y quien llama tiene que notarlo."""
    decisiones, almacen, _ = tres_registros

    with pytest.raises(KeyError):
        mas_parecidos("R0099", decisiones, almacen)


# ---------------------------------------------------------------------------
# c) Casi duplicados
# ---------------------------------------------------------------------------


def _almacen_con(vectores: dict[str, list[float]], tmp_path) -> Almacen:
    almacen = Almacen(ruta=tmp_path / "v.json", modelo="prueba")
    for identificador, valores in vectores.items():
        almacen.poner(
            Vector(
                identificador=identificador,
                hash="x",
                valores=tuple(valores),
            )
        )
    return almacen


def test_detecta_el_par_casi_identico(tmp_path):
    """El preprint y la versión publicada: dos DOI, un solo trabajo."""
    decisiones = [
        decision("R0001", titulo="Tratamiento con humedal", doi="10.1234/preprint"),
        decision("R0002", titulo="Tratamiento con humedal", doi="10.5678/publicado"),
        decision("R0003", titulo="Otra cosa", doi="10.9999/otro"),
    ]
    almacen = _almacen_con(
        {
            "R0001": [1.0, 0.0, 0.0],
            "R0002": [0.999, 0.02, 0.0],
            "R0003": [0.0, 0.0, 1.0],
        },
        tmp_path,
    )

    pares = casi_duplicados(decisiones, almacen)

    assert len(pares) == 1
    par = pares[0]
    assert {par.uno, par.otro} == {"R0001", "R0002"}
    assert par.similitud > UMBRAL_CASI_DUPLICADO
    assert "DOI distintos" in par.diagnostico


def test_por_debajo_del_umbral_no_se_reporta_nada(tmp_path):
    decisiones = [decision("R0001"), decision("R0002")]
    almacen = _almacen_con(
        {"R0001": [1.0, 0.0], "R0002": [0.8, 0.6]}, tmp_path
    )

    assert casi_duplicados(decisiones, almacen) == []
    # Con un umbral más flojo sí sale.
    assert len(casi_duplicados(decisiones, almacen, umbral=0.7)) == 1


def test_el_diagnostico_dice_por_que_la_deduplicacion_no_lo_atrapo(tmp_path):
    """Quien revisa el par necesita saber si fue por el DOI o por el título."""
    sin_doi = [
        decision("R0001", titulo="Informe técnico", doi="NR"),
        decision("R0002", titulo="Informe tecnico ampliado", doi="NR"),
    ]
    almacen = _almacen_con({"R0001": [1.0, 0.0], "R0002": [1.0, 0.01]}, tmp_path)

    par = casi_duplicados(sin_doi, almacen)[0]

    assert "ninguno trae DOI" in par.diagnostico


def test_un_par_con_uno_sin_doi_se_diagnostica_aparte(tmp_path):
    mezcla = [
        decision("R0001", doi="10.1234/uno"),
        decision("R0002", doi="NR"),
    ]
    almacen = _almacen_con({"R0001": [1.0, 0.0], "R0002": [1.0, 0.01]}, tmp_path)

    par = casi_duplicados(mezcla, almacen)[0]

    assert "no trae DOI" in par.diagnostico


def test_los_pares_van_del_mas_parecido_al_menos(tmp_path):
    decisiones = [decision(f"R000{n}") for n in (1, 2, 3)]
    almacen = _almacen_con(
        {
            "R0001": [1.0, 0.0, 0.0],
            "R0002": [1.0, 0.0, 0.0],
            "R0003": [0.99, 0.1, 0.0],
        },
        tmp_path,
    )

    pares = casi_duplicados(decisiones, almacen, umbral=0.9)

    assert len(pares) == 3
    assert pares[0].similitud >= pares[1].similitud >= pares[2].similitud


def test_un_par_con_vector_de_baja_calidad_se_marca(tmp_path):
    """Dos títulos parecidos sin resumen se parecen demasiado fácil."""
    decisiones = [decision("R0001"), decision("R0002")]
    almacen = Almacen(ruta=tmp_path / "v.json", modelo="prueba")
    almacen.poner(Vector("R0001", "x", (1.0, 0.0), baja_calidad=True))
    almacen.poner(Vector("R0002", "x", (1.0, 0.01)))

    par = casi_duplicados(decisiones, almacen)[0]

    assert par.baja_calidad is True
    assert "baja calidad" in "\n".join(par.lineas())


def test_casi_duplicados_sobre_el_fixture_completo(
    tmp_path, embeddings, protocolo, ruta_fixture_demo
):
    """De punta a punta: se detecta la pareja preparada y ninguna más."""
    from tatewari.cribado import cribar

    registros = json.loads(ruta_fixture_demo.read_text(encoding="utf-8"))
    resultado = cribar(registros, protocolo)
    cliente, _ = embeddings(
        vector_de=vectores_unicos(
            pareja=("Anaerobic baffled reactor", "Septic tank and constructed wetland")
        )
    )
    almacen = Almacen.leer(tmp_path / "vectores.json", cliente.modelo)
    vectorizar([d.registro for d in resultado.decisiones], cliente, almacen, lote=8)

    pares = casi_duplicados(resultado.decisiones, almacen)

    assert len(pares) == 1
    assert {pares[0].uno, pares[0].otro} == {"R0007", "R0008"}
    assert pares[0].similitud == pytest.approx(1.0)
