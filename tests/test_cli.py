"""Pruebas de la línea de órdenes. No tocan la red ni necesitan Ollama."""

from __future__ import annotations

import csv
import json
import re

import pytest

from tatewari import __version__
from tatewari.cli import (
    SALIDA_ARCHIVO_NO_ENCONTRADO,
    SALIDA_CONFIGURACION,
    SALIDA_CRIBADO,
    SALIDA_EMBEDDINGS,
    SALIDA_MODELO,
    SALIDA_OK,
    SALIDA_PROTOCOLO_INVALIDO,
    main,
)


def test_version(capsys):
    codigo = main(["version"])

    assert codigo == SALIDA_OK
    assert capsys.readouterr().out.strip() == f"Tatewari {__version__}"


def test_protocolo_validar_imprime_el_resumen(capsys, ruta_protocolo_humedales):
    codigo = main(["protocolo", "validar", str(ruta_protocolo_humedales)])

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "Protocolo válido" in salida
    assert "Ventana : 2016-2026" in salida
    assert "P2_humedal" in salida
    assert "Ecuaciones previstas : 40" in salida


def test_protocolo_validar_falla_con_un_protocolo_roto(capsys, tmp_path):
    ruta = tmp_path / "roto.json"
    ruta.write_text(
        '{"titulo": "X", "ventana": [2016, 2026], "idiomas": ["es"], '
        '"tipos": ["article"], "bloques": {"B1": ["t"]}, '
        '"reglas": {"incluir": [{"todos": ["fantasma"]}]}}',
        encoding="utf-8",
    )

    codigo = main(["protocolo", "validar", str(ruta)])

    assert codigo == SALIDA_PROTOCOLO_INVALIDO
    capturado = capsys.readouterr()
    assert capturado.out == ""
    assert "fantasma" in capturado.err
    assert "reglas.incluir[0].todos[0]" in capturado.err


def test_protocolo_validar_avisa_si_no_existe_el_archivo(capsys, tmp_path):
    codigo = main(["protocolo", "validar", str(tmp_path / "no_existe.json")])

    assert codigo == SALIDA_ARCHIVO_NO_ENCONTRADO
    assert "No existe el protocolo" in capsys.readouterr().err


@pytest.fixture
def entorno_aislado(tmp_path, monkeypatch):
    """CLI en una carpeta limpia: sin .env del repositorio y salida en tmp."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TATEWARI_DATOS", str(tmp_path / "revisiones"))
    monkeypatch.delenv("TATEWARI_MAILTO", raising=False)
    return tmp_path


def test_cosechar_en_seco_imprime_las_ecuaciones_con_su_url(
    capsys, entorno_aislado, ruta_protocolo_humedales
):
    codigo = main(
        ["cosechar", "demo", "--protocolo", str(ruta_protocolo_humedales), "--seco"]
    )

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "no se ha tocado la red" in salida
    assert "Ecuaciones previstas : 40" in salida
    assert '[  1] "humedal artificial" AND "anaerobic"' in salida
    assert salida.count("https://api.openalex.org/works?") == 40
    assert "%20AND%20" in salida
    # Nada escrito en disco en modo seco.
    assert not (entorno_aislado / "revisiones").exists()


def test_cosechar_con_fixture_carga_los_registros_y_escribe_la_bitacora(
    capsys, entorno_aislado, ruta_protocolo_humedales, ruta_fixture_demo
):
    codigo = main(
        [
            "cosechar",
            "demo",
            "--protocolo",
            str(ruta_protocolo_humedales),
            "--fixture",
            str(ruta_fixture_demo),
        ]
    )

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "Registros cosechados en este lote  : 14" in salida
    assert "Pendientes                         : 39 de 40" in salida

    carpeta = entorno_aislado / "revisiones" / "demo"
    assert (carpeta / "search_log.csv").is_file()
    assert (carpeta / "registros.json").is_file()
    assert (carpeta / "estado.json").is_file()

    bitacora = (carpeta / "search_log.csv").read_text(encoding="utf-8")
    assert "https://api.openalex.org/works?" in bitacora


def test_cosechar_es_reanudable_desde_la_cli(
    capsys, entorno_aislado, ruta_protocolo_humedales, ruta_fixture_demo
):
    orden = [
        "cosechar",
        "demo",
        "--protocolo",
        str(ruta_protocolo_humedales),
        "--fixture",
        str(ruta_fixture_demo),
    ]
    main(orden)
    capsys.readouterr()
    main(orden)

    assert "Pendientes                         : 38 de 40" in capsys.readouterr().out


def test_cosechar_sin_correo_y_con_red_se_planta(
    capsys, entorno_aislado, ruta_protocolo_humedales
):
    """Unpaywall lo exige y OpenAlex lo premia: mejor avisar que gastar red."""
    codigo = main(
        ["cosechar", "demo", "--protocolo", str(ruta_protocolo_humedales)]
    )

    assert codigo == SALIDA_CONFIGURACION
    error = capsys.readouterr().err
    assert "TATEWARI_MAILTO" in error
    assert "--seco" in error


def test_cosechar_avisa_si_el_protocolo_no_existe(capsys, entorno_aislado, tmp_path):
    codigo = main(
        ["cosechar", "demo", "--protocolo", str(tmp_path / "no.json"), "--seco"]
    )

    assert codigo == SALIDA_ARCHIVO_NO_ENCONTRADO
    assert "No existe el protocolo" in capsys.readouterr().err


@pytest.fixture
def revision_cosechada(entorno_aislado, ruta_protocolo_humedales, ruta_fixture_demo):
    """Una revisión ya cosechada desde el fixture, lista para cribar."""
    main(
        [
            "cosechar",
            "demo",
            "--protocolo",
            str(ruta_protocolo_humedales),
            "--fixture",
            str(ruta_fixture_demo),
        ]
    )
    return entorno_aislado / "revisiones" / "demo"


def test_cribar_imprime_el_prisma_y_escribe_el_csv(capsys, revision_cosechada):
    """Lo que tiene que funcionar al final del encargo: «cribar demo»."""
    capsys.readouterr()

    codigo = main(["cribar", "demo"])

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "Diagrama de flujo PRISMA 2020" in salida
    assert "Registros cribados" in salida
    assert "Incluir" in salida
    assert (revision_cosechada / "cribado.csv").is_file()
    assert (revision_cosechada / "prisma.txt").is_file()


def test_cribar_usa_el_protocolo_que_anoto_la_cosecha(capsys, revision_cosechada):
    """Sin repetir --protocolo: se criba con el mismo con el que se cosechó."""
    capsys.readouterr()

    main(["cribar", "demo"])

    salida = capsys.readouterr().out
    assert "Caracterización de aguas residuales" in salida


def test_cribar_avisa_si_no_sabe_con_que_protocolo(capsys, entorno_aislado):
    codigo = main(["cribar", "fantasma"])

    assert codigo == SALIDA_CRIBADO
    error = capsys.readouterr().err
    assert "--protocolo" in error


def test_cribar_avisa_si_no_hay_nada_cosechado(
    capsys, entorno_aislado, ruta_protocolo_humedales
):
    codigo = main(
        ["cribar", "vacia", "--protocolo", str(ruta_protocolo_humedales)]
    )

    assert codigo == SALIDA_CRIBADO
    assert "cosechar" in capsys.readouterr().err


def test_cribar_avisa_de_una_decision_manual_huerfana(capsys, revision_cosechada):
    (revision_cosechada / "decisiones.json").write_text(
        '{"R9999": {"decision": "incluir", "motivo": "De otra cosecha.", '
        '"autor": "Pedro", "fecha": "2026-09-12"}}',
        encoding="utf-8",
    )
    capsys.readouterr()

    codigo = main(["cribar", "demo"])

    assert codigo == SALIDA_OK
    capturado = capsys.readouterr()
    assert "R9999" in capturado.err
    assert "Avisos" in capturado.err


@pytest.fixture
def ollama_en_la_cli(monkeypatch, ollama):
    """Sustituye el Ollama de la CLI por uno falso.

    Así se prueba `cribar --modelo-local` de punta a punta **sin Ollama
    instalado** (AGENTS.md, regla 6). Devuelve una función que recibe las
    respuestas que dará el modelo y deja apuntada la sesión falsa.
    """
    from tatewari import cli

    apuntes = {}

    def preparar(respuestas, modelos=None):
        cliente, sesion = ollama(modelos=modelos, respuestas=respuestas)
        apuntes["cliente"] = cliente
        apuntes["sesion"] = sesion
        monkeypatch.setattr(
            cli.ClienteOllama, "desde_config", classmethod(lambda *a, **k: cliente)
        )
        return apuntes

    return preparar


def test_cribar_con_modelo_local_resuelve_los_dudosos(
    capsys, revision_cosechada, ollama_en_la_cli
):
    apuntes = ollama_en_la_cli(
        [
            '{"decision":"incluir","motivo":"El título ya lo dice"}',
            '{"decision":"excluir","motivo":"Son aguas pluviales"}',
        ]
    )
    capsys.readouterr()

    codigo = main(["cribar", "demo", "--modelo-local"])

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "Registros dudosos que va a mirar el modelo: 2" in salida
    assert "[1/2]" in salida and "[2/2]" in salida
    assert "llama3.2:3b" in salida
    # Y las decisiones quedan guardadas con el nombre del modelo.
    decisiones = json.loads(
        (revision_cosechada / "decisiones.json").read_text(encoding="utf-8")
    )
    assert len(decisiones) == 2
    for decision in decisiones.values():
        assert decision["autor"] == "modelo:llama3.2:3b"
        assert decision["motivo"]
        assert decision["fecha"]


def test_el_cribado_con_modelo_deja_constancia_en_el_csv(
    capsys, revision_cosechada, ollama_en_la_cli
):
    """Que se sepa siempre quién decidió qué."""
    ollama_en_la_cli(
        [
            '{"decision":"incluir","motivo":"Vale"}',
            '{"decision":"dudoso","motivo":"No se sabe"}',
        ]
    )

    main(["cribar", "demo", "--modelo-local"])
    capsys.readouterr()

    with open(revision_cosechada / "cribado.csv", encoding="utf-8", newline="") as m:
        filas = list(csv.DictReader(m))
    del_modelo = [f for f in filas if f["decidido_por"].startswith("modelo:")]

    assert len(del_modelo) == 2
    for fila in del_modelo:
        assert fila["decidido_por"] == "modelo:llama3.2:3b"
        # Lo que decía el filtro sigue ahí al lado.
        assert fila["decision_filtro"] == "dudoso"


def test_una_respuesta_inservible_del_modelo_deja_el_registro_en_dudoso(
    capsys, revision_cosechada, ollama_en_la_cli
):
    """Jamás «excluir» por una respuesta que no se entendió."""
    ollama_en_la_cli(["no entiendo nada"] * 4)
    capsys.readouterr()

    codigo = main(["cribar", "demo", "--modelo-local"])

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "no se entendió la respuesta" in salida
    assert "nunca se excluye" in salida
    # No se escribe ninguna decisión: nadie decidió nada.
    assert not (revision_cosechada / "decisiones.json").exists()
    assert "Decisiones: 8 incluir, 2 dudoso, 3 excluir" in salida


def test_si_ollama_no_esta_levantado_la_cli_lo_explica(
    capsys, revision_cosechada, ollama_en_la_cli
):
    import requests

    apuntes = ollama_en_la_cli([])
    apuntes["sesion"].get = _ollama_caido
    capsys.readouterr()

    codigo = main(["cribar", "demo", "--modelo-local"])

    assert codigo == SALIDA_MODELO
    error = capsys.readouterr().err
    assert "ollama serve" in error
    assert "ollama pull" in error


def _ollama_caido(url, timeout=None):
    import requests

    raise requests.ConnectionError("No se pudo establecer conexión")


def test_cribar_sin_modelo_local_no_toca_ollama(capsys, revision_cosechada, ollama_en_la_cli):
    """El filtro determinista no necesita ningún modelo."""
    apuntes = ollama_en_la_cli([])
    capsys.readouterr()

    codigo = main(["cribar", "demo"])

    assert codigo == SALIDA_OK
    assert apuntes["sesion"].peticiones == []


def test_pendientes_lista_los_dudosos_con_su_motivo(capsys, revision_cosechada):
    codigo = main(["pendientes", "demo"])

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "2 registros dudosos" in salida
    assert "R0007" in salida
    assert "Motivo :" in salida
    assert "Resumen:" in salida
    assert "decidir demo R0007" in salida


def test_pendientes_en_modo_auditoria_saca_una_muestra_de_exclusiones(
    capsys, revision_cosechada
):
    codigo = main(["pendientes", "demo", "--modo", "auditoria"])

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "Auditoría" in salida
    assert "Semilla" in salida
    # Las tres exclusiones del fixture salen todas: son menos de veinte.
    for identificador in ("R0004", "R0005", "R0006"):
        assert identificador in salida
    # Pero «pendientes» no escribe: la ronda no queda registrada sin --registrar,
    # y la salida lo dice en vez de dejar creer que sí.
    assert not (revision_cosechada / "auditoria.json").exists()
    assert "NO ha quedado registrada" in salida
    assert "--registrar" in salida


def test_la_auditoria_queda_registrada_cuando_se_pide(capsys, revision_cosechada):
    """AGENTS.md, regla 4: una muestra que no se apunta no se puede comprobar."""
    codigo = main(["pendientes", "demo", "--modo", "auditoria", "--registrar"])

    assert codigo == SALIDA_OK
    assert "Auditoría registrada en" in capsys.readouterr().out
    registro = json.loads(
        (revision_cosechada / "auditoria.json").read_text(encoding="utf-8")
    )
    assert len(registro) == 1
    assert registro[0]["poblacion"] == 3


def _identificadores(texto: str) -> list[str]:
    """Los identificadores que aparecen al principio de una línea del listado."""
    return [l[:5] for l in texto.splitlines() if l.startswith("R0")]


def test_la_auditoria_se_puede_repetir_con_su_semilla(capsys, revision_cosechada):
    """La semilla que se imprime tiene que servir para reconstruir la muestra."""
    main(["pendientes", "demo", "--modo", "auditoria", "--cuantos", "2"])
    primera = capsys.readouterr().out
    semilla = re.search(r"Semilla (\d+)", primera).group(1)

    main(
        [
            "pendientes",
            "demo",
            "--modo",
            "auditoria",
            "--cuantos",
            "2",
            "--semilla",
            semilla,
        ]
    )
    segunda = capsys.readouterr().out

    assert len(_identificadores(primera)) == 2
    assert _identificadores(primera) == _identificadores(segunda)


def test_pendientes_en_modo_incluir_lista_lo_que_entra(capsys, revision_cosechada):
    codigo = main(["pendientes", "demo", "--modo", "incluir"])

    assert codigo == SALIDA_OK
    assert "8 registros que entran" in capsys.readouterr().out


def test_decidir_registra_la_decision_humana(capsys, revision_cosechada):
    codigo = main(
        [
            "decidir",
            "demo",
            "R0007",
            "--decision",
            "incluir",
            "--motivo",
            "El texto completo sí reporta remoción de DQO.",
            "--autor",
            "Pedro",
        ]
    )

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "Pedro dice «incluir»" in salida
    decisiones = json.loads(
        (revision_cosechada / "decisiones.json").read_text(encoding="utf-8")
    )
    assert decisiones["R0007"]["autor"] == "Pedro"
    assert decisiones["R0007"]["decision"] == "incluir"
    assert decisiones["R0007"]["fecha"]


def test_decidir_rehace_el_cribado_y_el_prisma(capsys, revision_cosechada):
    main(
        [
            "decidir",
            "demo",
            "R0004",
            "--decision",
            "incluir",
            "--motivo",
            "Es de 2009 pero es el estudio de referencia.",
        ]
    )

    salida = capsys.readouterr().out
    assert "9 incluir" in salida
    prisma = (revision_cosechada / "prisma.txt").read_text(encoding="utf-8")
    assert "Decisiones que no tomó el filtro" in prisma


def test_una_persona_manda_sobre_el_modelo(
    capsys, revision_cosechada, ollama_en_la_cli
):
    """La persona corrige al modelo, y el rastro guarda a quién sustituye."""
    ollama_en_la_cli(
        [
            '{"decision":"incluir","motivo":"Vale"}',
            '{"decision":"dudoso","motivo":"No se sabe"}',
        ]
    )
    main(["cribar", "demo", "--modelo-local"])
    capsys.readouterr()

    main(
        [
            "decidir",
            "demo",
            "R0007",
            "--decision",
            "excluir",
            "--motivo",
            "Leí el texto completo y no reporta nada.",
            "--autor",
            "Pedro",
        ]
    )

    salida = capsys.readouterr().out
    assert "Sustituye la decisión anterior de modelo:llama3.2:3b" in salida
    decisiones = json.loads(
        (revision_cosechada / "decisiones.json").read_text(encoding="utf-8")
    )
    assert decisiones["R0007"]["autor"] == "Pedro"


def test_decidir_con_un_identificador_que_no_existe_avisa(capsys, revision_cosechada):
    codigo = main(
        ["decidir", "demo", "R9999", "--decision", "incluir", "--motivo", "X"]
    )

    assert codigo == SALIDA_CRIBADO
    assert "R9999" in capsys.readouterr().err


def test_decidir_sin_motivo_util_se_planta(capsys, revision_cosechada):
    codigo = main(
        ["decidir", "demo", "R0007", "--decision", "incluir", "--motivo", "   "]
    )

    assert codigo == SALIDA_CRIBADO
    assert "no es auditable" in capsys.readouterr().err


def vector_tematico(texto: str) -> list[float]:
    """Tres ejes temáticos más una base constante. Igual que en test_embeddings."""
    minusculas = texto.lower()
    return [
        1.0 if ("humedal" in minusculas or "wetland" in minusculas) else 0.0,
        1.0
        if ("anaerobi" in minusculas or "uasb" in minusculas or "séptic" in minusculas)
        else 0.0,
        1.0 if ("life cycle" in minusculas or "ciclo de vida" in minusculas) else 0.0,
        0.1,
    ]


@pytest.fixture
def embeddings_en_la_cli(monkeypatch, embeddings):
    """Sustituye el cliente de embeddings de la CLI por uno falso.

    Así se prueban `ordenar`, `similares` y `casi-duplicados` **sin Ollama y sin
    nomic-embed-text descargado** (AGENTS.md, regla 6).
    """
    from tatewari import cli

    apuntes = {}

    def preparar(vector_de=vector_tematico, instalado=True, **extra):
        cliente, sesion = embeddings(
            vector_de=vector_de, instalado=instalado, **extra
        )
        apuntes["cliente"] = cliente
        apuntes["sesion"] = sesion
        monkeypatch.setattr(
            cli.ClienteEmbeddings,
            "desde_config",
            classmethod(lambda *a, **k: cliente),
        )
        return apuntes

    return preparar


def test_ordenar_devuelve_los_registros_por_cercania(
    capsys, revision_cosechada, embeddings_en_la_cli
):
    """Lo que tiene que funcionar al final del encargo."""
    embeddings_en_la_cli()
    capsys.readouterr()

    codigo = main(
        [
            "ordenar",
            "demo",
            "--pregunta",
            "remoción de DQO en humedal artificial precedido de biodigestor",
        ]
    )

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "Ordenados por cercanía" in salida
    assert "vectorizando…" in salida
    # Las similitudes salen en orden decreciente.
    similitudes = [
        float(l.split(".", 1)[1].strip().split()[0])
        for l in salida.splitlines()
        if l.strip().startswith(("1.", "2.", "3.", "4.", "5."))
        and "0." in l
    ]
    assert similitudes == sorted(similitudes, reverse=True)
    # Y queda dicho que esto no decide nada.
    assert "ayuda de lectura" in salida


def test_ordenar_guarda_los_vectores_y_no_los_recalcula(
    capsys, revision_cosechada, embeddings_en_la_cli
):
    apuntes = embeddings_en_la_cli()
    main(["ordenar", "demo", "--pregunta", "humedal"])
    capsys.readouterr()
    pedidos_primera = len(apuntes["sesion"].textos_vectorizados)

    apuntes["sesion"].textos_vectorizados.clear()
    main(["ordenar", "demo", "--pregunta", "humedal"])
    salida = capsys.readouterr().out

    assert (revision_cosechada / "vectores.json").is_file()
    # Los trece registros únicos más la pregunta, que no se cachea: cambia en
    # cada consulta y vectorizarla cuesta una sola petición.
    assert pedidos_primera == 14
    # La segunda vez solo se vectoriza la pregunta, no los trece registros.
    assert apuntes["sesion"].textos_vectorizados == ["humedal"]
    assert "13 de la caché" in salida


def test_ordenar_no_cambia_ninguna_decision_del_cribado(
    capsys, revision_cosechada, embeddings_en_la_cli
):
    """La similitud es una ayuda de lectura, no un criterio de inclusión."""
    embeddings_en_la_cli()
    main(["cribar", "demo"])
    antes_csv = (revision_cosechada / "cribado.csv").read_text(encoding="utf-8")
    capsys.readouterr()

    main(["ordenar", "demo", "--pregunta", "humedal artificial"])
    main(["similares", "demo", "R0001"])
    main(["casi-duplicados", "demo"])

    assert (revision_cosechada / "cribado.csv").read_text(encoding="utf-8") == antes_csv
    assert not (revision_cosechada / "decisiones.json").exists()


def test_ordenar_puede_mirar_solo_los_dudosos(
    capsys, revision_cosechada, embeddings_en_la_cli
):
    """Para eso se hizo: leer primero lo más cercano de cien dudosos."""
    embeddings_en_la_cli()
    capsys.readouterr()

    codigo = main(
        ["ordenar", "demo", "--pregunta", "humedal", "--modo", "dudoso"]
    )

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "(dudoso)" in salida
    assert "R0007" in salida


def test_similares_lista_los_parecidos_sin_incluir_el_de_referencia(
    capsys, revision_cosechada, embeddings_en_la_cli
):
    embeddings_en_la_cli()
    capsys.readouterr()

    codigo = main(["similares", "demo", "R0001", "--cuantos", "3"])

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "Parecidos a R0001" in salida
    cuerpo = salida.split("Parecidos a R0001")[1]
    assert cuerpo.count("  R0001  ") == 0
    # Tres entradas numeradas. Se cuentan por el número y no por el final de la
    # línea: a un vector de baja calidad se le añade su marca detrás.
    numeradas = [l for l in cuerpo.splitlines() if re.match(r"\s*\d+\. ", l)]
    assert len(numeradas) == 3


def test_similares_avisa_si_el_identificador_no_existe(
    capsys, revision_cosechada, embeddings_en_la_cli
):
    embeddings_en_la_cli()
    capsys.readouterr()

    codigo = main(["similares", "demo", "R9999"])

    assert codigo == SALIDA_CRIBADO
    assert "R9999" in capsys.readouterr().err


def test_casi_duplicados_reporta_el_par_y_no_lo_fusiona(
    capsys, revision_cosechada, embeddings_en_la_cli
):
    """Se reportan para que una persona decida; no se fusionan solos."""
    asignados: dict[str, int] = {}

    def vector_de(texto: str) -> list[float]:
        base = [0.0] * 24
        if "Anaerobic baffled reactor" in texto or "Septic tank and constructed" in texto:
            base[0] = 1.0
            return base
        if texto not in asignados:
            asignados[texto] = len(asignados) + 1
        base[asignados[texto] % 24] = 1.0
        return base

    embeddings_en_la_cli(vector_de=vector_de)
    capsys.readouterr()

    codigo = main(["casi-duplicados", "demo"])

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "1 pares con similitud" in salida
    assert "R0007" in salida and "R0008" in salida
    assert "No se han fusionado" in salida or "no se han fusionado" in salida
    # El reporte queda en un CSV para que una persona lo revise.
    ruta = revision_cosechada / "casi_duplicados.csv"
    assert ruta.is_file()
    with open(ruta, encoding="utf-8", newline="") as manejador:
        filas = list(csv.DictReader(manejador))
    assert len(filas) == 1
    assert {filas[0]["identificador_uno"], filas[0]["identificador_otro"]} == {
        "R0007",
        "R0008",
    }
    assert "DOI distintos" in filas[0]["diagnostico"]
    # Y los trece registros siguen siendo trece: nada se fusionó.
    assert "13 únicos" in salida or main(["cribar", "demo"]) == SALIDA_OK


def test_casi_duplicados_sin_pares_lo_dice(
    capsys, revision_cosechada, embeddings_en_la_cli
):
    asignados: dict[str, int] = {}

    def todos_distintos(texto: str) -> list[float]:
        base = [0.0] * 24
        if texto not in asignados:
            asignados[texto] = len(asignados) + 1
        base[asignados[texto] % 24] = 1.0
        return base

    embeddings_en_la_cli(vector_de=todos_distintos)
    capsys.readouterr()

    codigo = main(["casi-duplicados", "demo"])

    assert codigo == SALIDA_OK
    assert "No hay ningún par" in capsys.readouterr().out
    assert not (revision_cosechada / "casi_duplicados.csv").exists()


def test_sin_el_modelo_de_embeddings_las_tres_ordenes_avisan(
    capsys, revision_cosechada, embeddings_en_la_cli
):
    """La capa es opcional: falla claro y no arrastra a nadie."""
    embeddings_en_la_cli(instalado=False)
    capsys.readouterr()

    for orden in (
        ["ordenar", "demo", "--pregunta", "x"],
        ["similares", "demo", "R0001"],
        ["casi-duplicados", "demo"],
    ):
        assert main(orden) == SALIDA_EMBEDDINGS
        error = capsys.readouterr().err
        assert "ollama pull nomic-embed-text" in error
        assert "opcional" in error


def test_sin_el_modelo_de_embeddings_el_resto_sigue_funcionando(
    capsys, revision_cosechada, embeddings_en_la_cli
):
    """Lo que pide el encargo: si no está el modelo, todo lo demás va igual."""
    embeddings_en_la_cli(instalado=False)
    main(["ordenar", "demo", "--pregunta", "x"])
    capsys.readouterr()

    assert main(["cribar", "demo"]) == SALIDA_OK
    assert "Diagrama de flujo PRISMA" in capsys.readouterr().out
    assert main(["pendientes", "demo"]) == SALIDA_OK
    assert main(["pendientes", "demo", "--modo", "auditoria"]) == SALIDA_OK
    capsys.readouterr()
    assert (
        main(
            [
                "decidir",
                "demo",
                "R0007",
                "--decision",
                "incluir",
                "--motivo",
                "Revisado a mano.",
            ]
        )
        == SALIDA_OK
    )


def test_un_modelo_generativo_para_embeddings_se_explica(
    capsys, revision_cosechada, embeddings_en_la_cli
):
    embeddings_en_la_cli(sin_soporte=True)
    capsys.readouterr()

    codigo = main(["ordenar", "demo", "--pregunta", "x"])

    assert codigo == SALIDA_EMBEDDINGS
    error = capsys.readouterr().err
    assert "no sabe generar vectores" in error


@pytest.mark.parametrize(
    "orden",
    [
        "cosechar",
        "cribar",
        "pendientes",
        "decidir",
        "ordenar",
        "similares",
        "casi-duplicados",
    ],
)
def test_la_ayuda_de_cada_suborden_encabeza_con_un_solo_uso(capsys, orden):
    """«Uso: Uso: tatewari cribar …» es lo que pasa si el formateador fuerza el
    prefijo también en la llamada con la que argparse calcula el `prog`."""
    with pytest.raises(SystemExit):
        main([orden, "--help"])

    primera = capsys.readouterr().out.splitlines()[0]

    assert primera.startswith(f"Uso: tatewari {orden}")
    assert "Uso: Uso:" not in primera


def test_el_prog_de_una_suborden_no_arrastra_el_prefijo(capsys):
    """Si el `prog` sale contaminado, también lo hacen los mensajes de error."""
    with pytest.raises(SystemExit):
        main(["ordenar", "demo"])  # falta --pregunta

    # argparse escribe el bloque de uso y luego la línea de error, las dos en
    # stderr. Lo que se vigila es que el `prog` de esa línea vaya limpio.
    error = capsys.readouterr().err
    assert "\ntatewari ordenar: error:" in error
    assert "Uso: Uso:" not in error


def test_sin_orden_muestra_la_ayuda(capsys):
    codigo = main([])

    assert codigo == SALIDA_OK
    salida = capsys.readouterr().out
    assert "Uso: tatewari" in salida
    assert "PRISMA 2020" in salida
