"""La interfaz local: el servicio, el servidor HTTP y su seguridad, y los trabajos.

Sin red y sin Ollama: el modelo es el Ollama falso de `conftest.py`, y el
servidor escucha en un puerto libre de 127.0.0.1 solo durante cada prueba.
"""

from __future__ import annotations

import http.client
import json
import shutil
import threading
import time

import pytest

from ayudas_conocimiento import EDAFOLOGIA, RESPUESTA_EDAFOLOGIA, como_texto
from conftest import SesionOllamaFalsa, modelo_falso
from tatewari.conocimiento.enrutador import Enrutador
from tatewari.cribado import leer_decisiones
from tatewari.interfaz.servicio import ErrorInterfaz, Servicio, guardar_en_env
from tatewari.interfaz.servidor import CABECERA_CLAVE, Trabajos, crear_servidor


@pytest.fixture
def revision(config_temporal, ruta_fixture_demo, ruta_protocolo_humedales):
    """La revisión «demo» ya cosechada: registros y el protocolo anotado."""
    carpeta = config_temporal.datos / "demo"
    carpeta.mkdir(parents=True)
    shutil.copyfile(ruta_fixture_demo, carpeta / "registros.json")
    (carpeta / "estado.json").write_text(
        json.dumps({"protocolo": str(ruta_protocolo_humedales)}), encoding="utf-8"
    )
    return carpeta


@pytest.fixture
def servicio(config_temporal, revision, vault_ks, ollama):
    """Un servicio con la revisión demo, un Vault vacío y un Ollama falso."""
    vault, _ = vault_ks

    def fabrica(respuestas=None, **extra):
        cliente, sesion = ollama(modelos=[modelo_falso("qwen3:4b", "4.0B")], respuestas=respuestas, **extra)
        enrutador = Enrutador.con_clientes({"extraccion": cliente, "sintesis": cliente})
        return Servicio(config=config_temporal, vault_ruta=vault.raiz, enrutador=enrutador, usuario="Prueba"), sesion

    return fabrica


# ---------------------------------------------------------------------------
# Revisiones
# ---------------------------------------------------------------------------


def test_las_colecciones_traen_la_revision_con_sus_cuentas(servicio):
    s, _ = servicio()

    revisiones, vault = s.colecciones()

    [demo] = revisiones["hijos"]
    assert demo["nombre"] == "demo"
    assert demo["cuenta"] == 13  # 14 registros, un duplicado
    assert sum(h["cuenta"] for h in demo["hijos"]) == 13
    assert [h["id"] for h in demo["hijos"]] == ["rev:demo:incluir", "rev:demo:dudoso", "rev:demo:excluir"]
    assert [h["id"] for h in vault["hijos"]][:2] == ["vault:todas", "vault:estado:DRAFT"]


def test_los_elementos_se_filtran_por_decision(servicio):
    s, _ = servicio()

    excluidos = s.elementos("rev:demo:excluir")

    assert excluidos and {e["marca"] for e in excluidos} == {"excluir"}


def test_la_busqueda_no_distingue_acentos(servicio):
    s, _ = servicio()

    con, sin = s.elementos("rev:demo", "remoción"), s.elementos("rev:demo", "remocion")

    assert con and [e["id"] for e in con] == [e["id"] for e in sin]


def test_la_ficha_de_un_registro_trae_resumen_y_motivo(servicio):
    s, _ = servicio()
    primero = s.elementos("rev:demo:incluir")[0]

    ficha = s.elemento("rev:demo", primero["id"])

    assert ficha["clase"] == "registro"
    assert ficha["resumen"]
    assert ficha["motivo"]
    assert ficha["decidido_por"] == "filtro"


def test_decidir_guarda_en_decisiones_json_y_recriba(servicio, revision):
    s, _ = servicio()
    registro = s.elementos("rev:demo:incluir")[0]["id"]

    ficha = s.decidir("demo", registro, "excluir", "No mide DQO en el efluente", "Ana")

    assert ficha["decision"] == "excluir"
    assert ficha["decidido_por"] == "Ana"
    guardada = leer_decisiones(revision / "decisiones.json")[registro]
    assert (guardada.decision, guardada.motivo, guardada.autor) == ("excluir", "No mide DQO en el efluente", "Ana")
    assert (revision / "cribado.csv").is_file()


@pytest.mark.parametrize(
    "decision, motivo, identificador, mensaje",
    [
        ("excluir", "   ", "R0001", "motivo"),
        ("borrar", "x", "R0001", "una de"),
        ("excluir", "x", "R9999", "R9999"),
    ],
)
def test_decidir_rechaza_lo_que_no_se_puede_auditar(servicio, revision, decision, motivo, identificador, mensaje):
    s, _ = servicio()

    with pytest.raises(ErrorInterfaz, match=mensaje):
        s.decidir("demo", identificador, decision, motivo, "Ana")
    assert not (revision / "decisiones.json").exists()


def test_una_revision_que_no_existe_se_dice(servicio):
    s, _ = servicio()

    with pytest.raises(ErrorInterfaz, match="No hay ninguna revisión"):
        s.elementos("rev:otra")


# ---------------------------------------------------------------------------
# Vault
# ---------------------------------------------------------------------------


@pytest.fixture
def con_notas(servicio):
    """El servicio con el documento de ejemplo ya procesado."""
    s, sesion = servicio([como_texto(RESPUESTA_EDAFOLOGIA)])
    s.orquestador().procesar_documento(EDAFOLOGIA)
    return s, sesion


def test_las_notas_se_agrupan_por_estado(con_notas):
    s, _ = con_notas

    draft = [e["titulo"] for e in s.elementos("vault:estado:DRAFT")]
    review = [e["titulo"] for e in s.elementos("vault:estado:REVIEW")]

    assert "Suelo" in draft
    assert review == ["Materia orgánica"]
    assert [e["titulo"] for e in s.elementos("vault:fuentes")][0].startswith("Fuente - ")


def test_el_original_de_la_materia_se_ve_como_documento(con_notas):
    s, _ = con_notas

    original = [e for e in s.elementos("vault:todas") if e["titulo"] == EDAFOLOGIA.stem]

    assert original and original[0]["revista"] == "documento original"


def test_la_ficha_de_una_nota_no_trae_el_bloque_de_datos(con_notas):
    s, _ = con_notas
    suelo = next(e for e in s.elementos("vault:todas") if e["titulo"] == "Suelo")

    ficha = s.elemento("vault:todas", suelo["id"])

    assert ficha["clase"] == "nota"
    assert "tatewari-datos" not in ficha["cuerpo"]
    assert ficha["transiciones"] == ["REVIEW", "APPROVED"]
    assert ficha["obsidian"].startswith("obsidian://open?path=")


def test_la_nota_de_fuente_enlaza_su_original(con_notas):
    s, _ = con_notas
    fuente = s.elementos("vault:fuentes")[0]

    ficha = s.elemento("vault:fuentes", fuente["id"])

    assert ficha["original"].endswith(EDAFOLOGIA.name)
    assert s.ruta_de_archivo(ficha["original"]).read_bytes() == EDAFOLOGIA.read_bytes()


def test_aprobar_sin_nombre_no_se_puede(con_notas):
    s, _ = con_notas
    suelo = next(e for e in s.elementos("vault:todas") if e["titulo"] == "Suelo")

    with pytest.raises(ErrorInterfaz, match="persona"):
        s.cambiar_estado(suelo["id"], "APPROVED", "  ")

    assert s.cambiar_estado(suelo["id"], "APPROVED", "Pedro")["estado"] == "APPROVED"


def test_seguir_un_enlace_abre_la_nota(con_notas):
    s, _ = con_notas

    assert s.buscar_nota("Materia orgánica|materia")["nombre"] == "Materia orgánica"
    with pytest.raises(ErrorInterfaz, match="todavía no tiene nota"):
        s.buscar_nota("Material parental")


@pytest.mark.parametrize("ruta", ["../fuera.txt", ".obsidian/app.json", "no-existe.pdf"])
def test_no_se_sirve_nada_fuera_del_vault(con_notas, ruta, tmp_path):
    s, _ = con_notas
    (tmp_path / "fuera.txt").write_text("secreto", encoding="utf-8")
    obsidian = s.vault().raiz / ".obsidian"
    obsidian.mkdir(exist_ok=True)
    (obsidian / "app.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ErrorInterfaz):
        s.ruta_de_archivo(ruta)


def test_elegir_vault_crea_la_estructura_y_la_recuerda(servicio, tmp_path, config_temporal):
    from dataclasses import replace

    s, _ = servicio()
    env = tmp_path / ".env"
    s.config = replace(config_temporal, origen_env=env)
    nuevo = tmp_path / "Otro Vault"

    resultado = s.elegir_vault(str(nuevo), recordar=True)

    assert (nuevo / "02_CONCEPTOS").is_dir()
    assert f"TATEWARI_OBSIDIAN_VAULT={nuevo}" in env.read_text(encoding="utf-8")
    assert resultado["vault"] == str(nuevo)


def test_elegir_vault_pide_una_ruta_completa(servicio):
    s, _ = servicio()

    with pytest.raises(ErrorInterfaz, match="ruta completa"):
        s.elegir_vault("mi vault")


def test_guardar_en_env_sustituye_sin_tocar_lo_demas(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TATEWARI_MAILTO=yo@x.invalid\nTATEWARI_OBSIDIAN_VAULT=C:/viejo\n", encoding="utf-8")

    guardar_en_env(env, "TATEWARI_OBSIDIAN_VAULT", "C:/nuevo")

    assert env.read_text(encoding="utf-8") == "TATEWARI_MAILTO=yo@x.invalid\nTATEWARI_OBSIDIAN_VAULT=C:/nuevo\n"


def test_guardar_en_env_parte_del_ejemplo(tmp_path):
    (tmp_path / ".env.example").write_text("# comentario\nTATEWARI_DATOS=./revisiones\n", encoding="utf-8")

    guardar_en_env(tmp_path / ".env", "TATEWARI_OBSIDIAN_VAULT", "C:/v")

    texto = (tmp_path / ".env").read_text(encoding="utf-8")
    assert texto.startswith("# comentario\n") and texto.endswith("TATEWARI_OBSIDIAN_VAULT=C:/v\n")


# ---------------------------------------------------------------------------
# Subidas
# ---------------------------------------------------------------------------


def test_una_subida_se_guarda_en_datos_con_un_nombre_limpio(servicio, config_temporal):
    s, _ = servicio()

    ruta = s.guardar_subida("..\\..\\apuntes.md", b"# Hola")

    assert ruta.name == "apuntes.md"
    assert (config_temporal.datos / "_interfaz" / "subidas") in ruta.parents


@pytest.mark.parametrize("nombre, contenido, mensaje", [("virus.exe", b"MZ", "no se admite"), ("vacio.pdf", b"", "vacío")])
def test_una_subida_rara_se_rechaza(servicio, nombre, contenido, mensaje):
    s, _ = servicio()

    with pytest.raises(ErrorInterfaz, match=mensaje):
        s.guardar_subida(nombre, contenido)


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


def test_modelos_dice_que_hace_cada_tarea(servicio):
    s, _ = servicio()

    modelos = s.modelos()

    assert modelos["ok"]
    assert modelos["tareas"] == {"extraccion": "qwen3:4b", "sintesis": "qwen3:4b"}
    assert modelos["en_memoria"] == []  # el Ollama falso no tiene /api/ps


def test_modelos_con_ollama_apagado_no_rompe(servicio):
    s, sesion = servicio()

    def caido(url, timeout=None):
        import requests

        raise requests.ConnectionError("rechazada")

    sesion.get = caido

    modelos = s.modelos()

    assert not modelos["ok"] and "ollama serve" in modelos["error"]


def test_precargar_pide_un_prompt_vacio_con_el_mismo_contexto(servicio):
    s, sesion = servicio([""])

    assert s.precargar() == "qwen3:4b"

    [cuerpo] = sesion.cuerpos
    assert cuerpo["prompt"] == ""
    assert cuerpo["keep_alive"] == "30m"
    assert cuerpo["options"]["num_ctx"] == 4096  # el de la extracción: si no, Ollama recarga


def test_en_memoria_lee_api_ps(ollama):
    sesion = SesionOllamaFalsa(modelos=[modelo_falso("qwen3:4b")])
    original = sesion.get

    def get(url, timeout=None):
        if url.endswith("/api/ps"):
            from conftest import RespuestaFalsa

            return RespuestaFalsa(200, {"models": [{"name": "qwen3:4b"}]})
        return original(url, timeout)

    sesion.get = get
    cliente, _ = ollama(sesion=sesion)

    assert cliente.en_memoria() == ("qwen3:4b",)


# ---------------------------------------------------------------------------
# Trabajos
# ---------------------------------------------------------------------------


def test_un_trabajo_que_falla_no_para_la_cola():
    trabajos = Trabajos()

    def rompe(trabajo):
        raise ValueError("algo")

    trabajos.encolar("roto", rompe)
    trabajos.encolar("bien", lambda t: "hecho")
    trabajos.esperar(5)

    estados = {t["titulo"]: (t["estado"], t["resultado"]) for t in trabajos.lista()}
    assert estados["roto"][0] == "fallo" and "ValueError" in estados["roto"][1]
    assert estados["bien"] == ("hecho", "hecho")


def test_la_precarga_no_bloquea_la_cola():
    trabajos = Trabajos()
    soltar = threading.Event()
    trabajos.aparte("Cargar el modelo", lambda t: (soltar.wait(5), "cargado")[1])

    trabajos.encolar("documento", lambda t: "procesado")
    limite = time.monotonic() + 5
    while time.monotonic() < limite and trabajos.lista()[0]["estado"] != "hecho":
        time.sleep(0.02)

    assert trabajos.lista()[0] == {**trabajos.lista()[0], "titulo": "documento", "estado": "hecho"}
    soltar.set()


# ---------------------------------------------------------------------------
# HTTP y seguridad
# ---------------------------------------------------------------------------


@pytest.fixture
def servidor(servicio):
    """Un servidor de verdad en un puerto libre. Devuelve (pedir, clave, servicio, trabajos)."""
    s, _ = servicio([como_texto(RESPUESTA_EDAFOLOGIA)])
    trabajos = Trabajos()
    httpd, clave = crear_servidor(s, trabajos, puerto=0)
    hilo = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    hilo.start()
    puerto = httpd.server_address[1]

    def pedir(metodo, ruta, cuerpo=None, cabeceras=None, con_clave=True, host=None):
        conexion = http.client.HTTPConnection("127.0.0.1", puerto, timeout=10)
        todas = {"Host": host or f"127.0.0.1:{puerto}"}
        if con_clave:
            todas[CABECERA_CLAVE] = clave
        if isinstance(cuerpo, dict):
            cuerpo = json.dumps(cuerpo).encode("utf-8")
            todas["Content-Type"] = "application/json"
        todas.update(cabeceras or {})
        conexion.request(metodo, ruta, body=cuerpo, headers=todas)
        respuesta = conexion.getresponse()
        datos = respuesta.read()
        conexion.close()
        return respuesta, datos

    yield pedir, clave, s, trabajos
    httpd.shutdown()
    httpd.server_close()


def test_la_pagina_se_sirve_con_su_politica_de_seguridad(servidor):
    pedir, *_ = servidor

    respuesta, cuerpo = pedir("GET", "/", con_clave=False)

    assert respuesta.status == 200
    assert b"Tatewari" in cuerpo
    assert "script-src 'self'" in respuesta.getheader("Content-Security-Policy")
    assert respuesta.getheader("X-Frame-Options") == "DENY"


def test_sin_clave_no_se_lee_nada(servidor):
    pedir, *_ = servidor

    respuesta, _ = pedir("GET", "/api/estado", con_clave=False)

    assert respuesta.status == 401


def test_con_la_clave_se_lee(servidor):
    pedir, *_ = servidor

    respuesta, cuerpo = pedir("GET", "/api/estado")

    assert respuesta.status == 200
    assert json.loads(cuerpo)["usuario"] == "Prueba"


def test_otro_host_se_rechaza_contra_el_dns_rebinding(servidor):
    pedir, *_ = servidor

    respuesta, _ = pedir("GET", "/api/estado", host="ataque.ejemplo:80")

    assert respuesta.status == 403


def test_una_escritura_desde_otra_web_se_rechaza(servidor):
    pedir, *_ = servidor

    respuesta, _ = pedir("POST", "/api/validar", {}, cabeceras={"Origin": "https://ataque.ejemplo"})

    assert respuesta.status == 403


def test_una_escritura_con_solo_la_galleta_no_basta(servidor):
    pedir, clave, *_ = servidor

    respuesta, _ = pedir("POST", "/api/validar", {}, con_clave=False, cabeceras={"Cookie": f"tatewari_clave={clave}"})

    assert respuesta.status == 401


def test_decidir_por_http(servidor, revision):
    pedir, *_ = servidor

    respuesta, cuerpo = pedir("POST", "/api/decidir", {"revision": "demo", "id": "R0001", "decision": "dudoso", "motivo": "Revisar el método", "autor": "Ana"})

    assert respuesta.status == 200, cuerpo
    assert json.loads(cuerpo)["decision"] == "dudoso"
    assert leer_decisiones(revision / "decisiones.json")["R0001"].autor == "Ana"


def test_un_error_llega_como_mensaje_en_espanol(servidor):
    pedir, *_ = servidor

    respuesta, cuerpo = pedir("POST", "/api/decidir", {"revision": "demo", "id": "R0001", "decision": "excluir", "motivo": ""})

    assert respuesta.status == 400
    assert "motivo" in json.loads(cuerpo)["error"]


def test_subir_un_documento_lo_procesa_y_borra_la_copia(servidor, config_temporal):
    pedir, _, s, trabajos = servidor

    respuesta, cuerpo = pedir("POST", "/api/subir?nombre=edafologia_unidad1.md", EDAFOLOGIA.read_bytes())
    assert respuesta.status == 200, cuerpo
    trabajos.esperar(20)

    [trabajo] = trabajos.lista()
    assert trabajo["estado"] == "hecho", trabajo["resultado"]
    assert "Notas nuevas        : 4" in trabajo["resultado"]
    assert any("analizando" in l for l in trabajo["lineas"])
    assert (s.vault().carpeta("materia") / EDAFOLOGIA.name).is_file()
    assert not any((config_temporal.datos / "_interfaz" / "subidas").iterdir())


def test_abrir_un_archivo_pide_la_sesion_y_no_sale_del_vault(servidor):
    pedir, clave, s, _ = servidor
    s.orquestador().procesar_documento(EDAFOLOGIA)
    original = f"{s.vault().carpeta('materia').name}/{EDAFOLOGIA.name}"

    sin, _ = pedir("GET", f"/archivo?ruta={original}", con_clave=False)
    respuesta, _ = pedir("POST", "/api/sesion", {})
    galleta = respuesta.getheader("Set-Cookie")
    con, cuerpo = pedir("GET", f"/archivo?ruta={original}", con_clave=False, cabeceras={"Cookie": galleta.split(";")[0]})
    fuera, _ = pedir("GET", "/archivo?ruta=../../x", con_clave=False, cabeceras={"Cookie": galleta.split(";")[0]})

    assert sin.status == 401
    assert "HttpOnly" in galleta and "SameSite=Strict" in galleta
    assert con.status == 200 and cuerpo == EDAFOLOGIA.read_bytes()
    assert fuera.status == 400


def test_la_orden_interfaz_existe():
    from tatewari.cli import construir_parser

    args = construir_parser().parse_args(["interfaz", "--no-abrir", "--sin-precarga", "--puerto", "9100"])

    assert (args.puerto, args.no_abrir, args.sin_precarga) == (9100, True, True)
