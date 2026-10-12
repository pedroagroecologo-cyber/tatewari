"""Knowledge Studio: esquema, citas, estados, rutas, Markdown, enlaces y Vault."""

from __future__ import annotations

import json
import os

import pytest

from ayudas_conocimiento import EDAFOLOGIA, RESPUESTA_EDAFOLOGIA
from tatewari.conocimiento.documento import Documento, Fragmento
from tatewari.conocimiento.extraccion import extraer
from tatewari.conocimiento.ingesta import ingerir
from tatewari.conocimiento.markdown import (
    AVISO_BORRADOR,
    aviso_aprobado,
    enlace,
    enlaces_de,
    escribir_frontmatter,
    huella_cuerpo,
    leer_nota,
    render_objeto,
)
from tatewari.conocimiento.normalizacion import Trozo, normalizar_documento, trocear
from tatewari.conocimiento.objetos import (
    CONFIANZA_SIN_VERIFICAR,
    Afirmacion,
    ErrorEsquema,
    ErrorEstado,
    ObjetoConocimiento,
    Relacion,
    comprobar_transicion,
    fundir,
    id_de_objeto,
    validar_respuesta,
    verificar_cita,
)
from tatewari.conocimiento.rutas import ErrorRuta, Jaula, nombre_de_nota
from tatewari.conocimiento.validacion import validar_vault
from tatewari.conocimiento.vault import ErrorVault, Vault
from tatewari.conocimiento.vinculos import detectar_conflictos, planificar


@pytest.fixture
def trozo():
    documento = normalizar_documento(extraer(ingerir(EDAFOLOGIA)))
    [unico] = trocear(documento)
    return unico


def objeto(titulo="Suelo", **campos):
    base = dict(
        id=id_de_objeto(titulo),
        titulo=titulo,
        tipo="concepto",
        definiciones=[
            Afirmacion(
                texto="Cuerpo natural.",
                cita="El suelo es un cuerpo natural formado por minerales",
                documento="a.md",
                ubicacion="sección «El suelo»",
                verificada=True,
            )
        ],
        documentos=["a.md"],
        ubicaciones=["a.md, sección «El suelo»"],
        confianza=0.9,
        modelo="modelo:qwen3:4b",
    )
    base.update(campos)
    return ObjetoConocimiento(**base)


# ---------------------------------------------------------------------------
# Citas: la regla anti-invención
# ---------------------------------------------------------------------------


def test_una_cita_literal_se_verifica_con_su_ubicacion(trozo):
    verificada, ubicacion = verificar_cita(
        "La meteorización es el proceso de descomposición física y química de las rocas", trozo
    )

    assert verificada
    assert ubicacion == "sección «Meteorización»"


def test_la_cita_tolera_acentos_comillas_y_puntuacion(trozo):
    verificada, _ = verificar_cita(
        "«la METEORIZACION es el proceso de descomposicion fisica y quimica»", trozo
    )

    assert verificada


def test_una_cita_inventada_no_se_verifica(trozo):
    assert verificar_cita("Según Darwin, la materia orgánica es el alma del suelo", trozo)[0] is False


def test_una_cita_de_tres_palabras_no_verifica_nada(trozo):
    """«el suelo es» aparece en cualquier texto sobre suelos."""
    assert verificar_cita("el suelo es", trozo)[0] is False


# ---------------------------------------------------------------------------
# Validación de la respuesta del modelo
# ---------------------------------------------------------------------------


def test_la_respuesta_valida_da_objetos_con_su_fuente(trozo):
    respuesta = validar_respuesta(RESPUESTA_EDAFOLOGIA, trozo, "edafologia.md", "modelo:qwen3:4b")

    nombres = [o.titulo for o in respuesta.objetos]
    assert nombres == ["Suelo", "Horizonte A", "Meteorización", "Materia orgánica"]
    suelo = respuesta.objetos[0]
    assert suelo.verificado
    assert suelo.definiciones[0].ubicacion == "sección «El suelo»"
    assert suelo.ubicaciones == ["edafologia.md, sección «El suelo»"]
    assert suelo.estado == "DRAFT"
    assert suelo.modelo == "modelo:qwen3:4b"


def test_una_cita_inventada_baja_a_inferencia_y_a_revision(trozo):
    respuesta = validar_respuesta(RESPUESTA_EDAFOLOGIA, trozo, "edafologia.md")

    materia = next(o for o in respuesta.objetos if o.titulo == "Materia orgánica")
    assert not materia.verificado
    assert materia.definiciones[0].origen == "inferencia"
    assert materia.definiciones[0].cita == "NR"  # la cita inventada no se guarda
    assert materia.estado == "REVIEW"
    assert materia.confianza <= CONFIANZA_SIN_VERIFICAR
    assert any("no aparece en el documento" in a for a in respuesta.avisos)


def test_una_inferencia_declarada_queda_marcada(trozo):
    respuesta = validar_respuesta(RESPUESTA_EDAFOLOGIA, trozo, "edafologia.md")

    meteorizacion = next(o for o in respuesta.objetos if o.titulo == "Meteorización")
    origenes = [d.origen for d in meteorizacion.detalles]
    assert origenes == ["fuente", "inferencia"]


def test_una_referencia_inventada_se_descarta(trozo):
    respuesta = validar_respuesta(RESPUESTA_EDAFOLOGIA, trozo, "edafologia.md")

    assert any("Pérez Ficticio" in r for r in respuesta.referencias)
    assert not any("Smith" in r for r in respuesta.referencias)
    assert any("no inventar bibliografía" in a for a in respuesta.avisos)


def test_el_modelo_puede_decir_que_no_hay_informacion_suficiente(trozo):
    respuesta = validar_respuesta(
        {"suficiente": False, "motivo_insuficiente": "Solo hay un índice.", "objetos": []},
        trozo, "a.md",
    )

    assert respuesta.insuficiente
    assert respuesta.motivo_insuficiente == "Solo hay un índice."
    assert respuesta.objetos == []


@pytest.mark.parametrize(
    "datos, mensaje",
    [
        ("no soy json", "no es un objeto"),
        ({"cosas": []}, "falta la lista «objetos»"),
        ({"objetos": "Suelo"}, "debería ser una lista"),
    ],
)
def test_una_respuesta_sin_la_forma_pedida_se_rechaza(trozo, datos, mensaje):
    with pytest.raises(ErrorEsquema, match=mensaje):
        validar_respuesta(datos, trozo, "a.md")


def test_un_objeto_mal_formado_se_descarta_y_los_demas_siguen(trozo):
    respuesta = validar_respuesta(
        {"objetos": ["texto suelto", {"tipo": "concepto"}, RESPUESTA_EDAFOLOGIA["objetos"][0]]},
        trozo, "a.md",
    )

    assert [o.titulo for o in respuesta.objetos] == ["Suelo"]
    assert len([a for a in respuesta.avisos if "se descarta" in a]) == 2


def test_los_tipos_en_ingles_se_traducen_y_los_raros_van_a_otro(trozo):
    respuesta = validar_respuesta(
        {"objetos": [{"titulo": "Darwin", "tipo": "person"}, {"titulo": "X", "tipo": "cosa rara"}]},
        trozo, "a.md",
    )

    assert [o.tipo for o in respuesta.objetos] == ["persona", "otro"]


def test_la_confianza_en_porcentaje_se_normaliza(trozo):
    datos = {"objetos": [dict(RESPUESTA_EDAFOLOGIA["objetos"][0], confianza=85)]}

    assert validar_respuesta(datos, trozo, "a.md").objetos[0].confianza == 0.85


def test_un_titulo_desbocado_se_recorta(trozo):
    datos = {"objetos": [{"titulo": "palabra " * 200, "tipo": "concepto"}]}

    assert len(validar_respuesta(datos, trozo, "a.md").objetos[0].titulo) <= 121


def test_fundir_junta_el_mismo_concepto_de_dos_trozos():
    uno = objeto(documentos=["a.md"], ubicaciones=["a.md, p. 1"])
    otro = objeto(
        titulo="suelo",
        definiciones=[Afirmacion(texto="Otra definición.", documento="a.md", ubicacion="p. 2", verificada=True)],
        documentos=["a.md"],
        ubicaciones=["a.md, p. 2"],
    )

    [fundido] = fundir([uno, otro])

    assert len(fundido.definiciones) == 2
    assert fundido.ubicaciones == ["a.md, p. 1", "a.md, p. 2"]


# ---------------------------------------------------------------------------
# Estados
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "actual, nuevo",
    [("DRAFT", "REVIEW"), ("REVIEW", "APPROVED"), ("APPROVED", "PUBLISHED"), ("APPROVED", "REVIEW")],
)
def test_transiciones_admitidas(actual, nuevo):
    comprobar_transicion(actual, nuevo, autor="Pedro")


def test_no_se_publica_sin_aprobar():
    with pytest.raises(ErrorEstado, match="No se puede pasar de DRAFT a PUBLISHED"):
        comprobar_transicion("DRAFT", "PUBLISHED", autor="Pedro")


@pytest.mark.parametrize("autor", ["", "modelo:qwen3:4b"])
def test_el_modelo_no_aprueba_ni_publica(autor):
    with pytest.raises(ErrorEstado, match="solo lo puede poner una persona"):
        comprobar_transicion("REVIEW", "APPROVED", autor=autor)


def test_un_estado_desconocido_se_rechaza():
    with pytest.raises(ErrorEstado, match="Estado desconocido"):
        comprobar_transicion("DRAFT", "FINAL", autor="Pedro")


# ---------------------------------------------------------------------------
# La jaula de rutas
# ---------------------------------------------------------------------------


def test_dentro_del_vault_se_escribe(tmp_path):
    jaula = Jaula.para(tmp_path)

    ruta = jaula.escribir_texto(tmp_path / "a" / "b.md", "hola")

    assert ruta.read_text(encoding="utf-8") == "hola"


@pytest.mark.parametrize("destino", ["../fuera.md", "../../Windows/system.ini", "sub/../../fuera.md"])
def test_fuera_del_vault_no_se_escribe(tmp_path, destino):
    vault = tmp_path / "vault"
    vault.mkdir()
    jaula = Jaula.para(vault)

    with pytest.raises(ErrorRuta, match="fuera de las carpetas autorizadas"):
        jaula.escribir_texto(vault / destino, "x")
    assert not (tmp_path / "fuera.md").exists()


def test_una_ruta_absoluta_ajena_no_se_escribe(tmp_path):
    jaula = Jaula.para(tmp_path / "vault")

    with pytest.raises(ErrorRuta):
        jaula.escribir_texto(tmp_path.parent / "ajeno.md", "x")


@pytest.mark.parametrize("carpeta", [".obsidian", ".git", ".trash"])
def test_las_carpetas_internas_estan_prohibidas(tmp_path, carpeta):
    jaula = Jaula.para(tmp_path)

    with pytest.raises(ErrorRuta, match="carpeta interna"):
        jaula.escribir_texto(tmp_path / carpeta / "workspace.json", "{}")


@pytest.mark.skipif(os.name != "nt" and not hasattr(os, "symlink"), reason="sin enlaces simbólicos")
def test_un_enlace_simbolico_hacia_fuera_no_se_cuela(tmp_path):
    vault = tmp_path / "vault"
    fuera = tmp_path / "fuera"
    vault.mkdir()
    fuera.mkdir()
    try:
        (vault / "atajo").symlink_to(fuera, target_is_directory=True)
    except OSError:
        pytest.skip("este sistema no deja crear enlaces simbólicos")
    jaula = Jaula.para(vault)

    with pytest.raises(ErrorRuta):
        jaula.escribir_texto(vault / "atajo" / "nota.md", "x")


def test_sin_raices_no_hay_jaula():
    with pytest.raises(ErrorRuta, match="TATEWARI_OBSIDIAN_VAULT"):
        Jaula.para(None, "")


@pytest.mark.parametrize(
    "titulo, esperado",
    [
        ("Nitrógeno total", "Nitrógeno total"),
        ("pH: acidez / basicidad", "pH acidez basicidad"),
        ("[[Inyección]]|#^", "Inyección"),
        ("CON", "CON_"),
        ("..\\..\\escape", "escape"),
        ("   ", "Sin título"),
        ("Fin con punto.", "Fin con punto"),
    ],
)
def test_nombre_de_nota_seguro_para_windows_y_obsidian(titulo, esperado):
    assert nombre_de_nota(titulo) == esperado


# ---------------------------------------------------------------------------
# Markdown y enlaces
# ---------------------------------------------------------------------------


def test_el_frontmatter_ida_y_vuelta():
    texto = escribir_frontmatter(
        {"estado": "DRAFT", "aliases": ["suelos", "Suelo: definición"], "confianza": 0.9, "vacia": []}
    ) + "# Cuerpo\n"

    campos, cuerpo, _ = leer_nota(texto)

    assert campos == {
        "estado": "DRAFT",
        "aliases": ["suelos", "Suelo: definición"],
        "confianza": 0.9,
        "vacia": [],
    }
    assert cuerpo == "# Cuerpo\n"


def test_el_frontmatter_escrito_a_mano_tambien_se_lee():
    campos, _, _ = leer_nota("---\ntags: [a, b]\nestado: APPROVED\naliases:\n  - uno\n---\nx")

    assert campos["tags"] == ["a", "b"]
    assert campos["estado"] == "APPROVED"
    assert campos["aliases"] == ["uno"]


def test_la_nota_trae_los_enlaces_como_texto_markdown():
    texto = render_objeto(
        objeto(),
        indice={},
        notas_fuente={"a.md": "Fuente - Apuntes"},
    )

    assert "[[Fuente - Apuntes|a.md]]" in texto
    campos, cuerpo, datos = leer_nota(texto)
    assert campos["estado"] == "DRAFT"
    assert datos["titulo"] == "Suelo"
    assert campos["tatewari_hash"] == huella_cuerpo(cuerpo)


def test_el_enlace_resuelve_alias_hacia_el_nombre_de_la_nota():
    assert enlace("suelos", {"suelos": "Suelo"}) == "[[Suelo|suelos]]"
    assert enlace("Suelo", {"suelo": "Suelo"}) == "[[Suelo]]"
    assert enlace("Material parental") == "[[Material parental]]"


def test_enlaces_de_ignora_alias_y_anclas():
    assert enlaces_de("ver [[Suelo|el suelo]], [[Horizonte A#Espesor]] y [[Nota^bloque]]") == [
        "Suelo", "Horizonte A", "Nota",
    ]


def test_la_nota_marca_lo_que_es_interpretacion_del_modelo():
    texto = render_objeto(
        objeto(
            resumen="Mi interpretación.",
            detalles=[Afirmacion(texto="Algo inferido.", origen="inferencia")],
        )
    )

    assert "## Resumen (interpretación del modelo)" in texto
    assert "Algo inferido.  \n  *(interpretación del modelo, sin verificar" in texto
    assert "*(de la fuente · a.md, sección «El suelo»)*" in texto
    assert "> «El suelo es un cuerpo natural formado por minerales»" in texto


# ---------------------------------------------------------------------------
# El Vault
# ---------------------------------------------------------------------------


def test_crear_estructura_zea_mayz(vault_ks):
    vault, _ = vault_ks

    for carpeta in ("00_INBOX", "01_MATERIA", "02_CONCEPTOS", "03_PERSONAJES", "04_TERRITORIO",
                    "05_GUION", "06_STORYBOARD", "07_REFERENCIAS", "08_ILUSTRACIONES", "09_LIBRO"):
        assert (vault.raiz / carpeta).is_dir(), carpeta
    for plantilla in ("Concepto", "Fuente", "Personaje", "Lugar", "Proceso"):
        assert (vault.raiz / "_plantillas" / f"{plantilla}.md").is_file()
    assert "{{title}}" in (vault.raiz / "_plantillas" / "Concepto.md").read_text(encoding="utf-8")


def test_crear_estructura_no_toca_lo_que_existe(vault_ks):
    vault, jaula = vault_ks
    mia = vault.raiz / "_plantillas" / "Concepto.md"
    mia.write_text("mi plantilla", encoding="utf-8")

    vault.crear_estructura(jaula)

    assert mia.read_text(encoding="utf-8") == "mi plantilla"


def test_la_estructura_es_configurable(tmp_path):
    raiz = tmp_path / "otro"
    (raiz / ".tatewari").mkdir(parents=True)
    (raiz / ".tatewari" / "vault.json").write_text(
        json.dumps({"carpetas": {"conceptos": "Conocimiento"}, "destino_por_tipo": {"persona": "conceptos"}}),
        encoding="utf-8",
    )

    vault = Vault.cargar(raiz)

    assert vault.carpeta_para_tipo("concepto") == raiz / "Conocimiento"
    assert vault.carpeta_para_tipo("persona") == raiz / "Conocimiento"
    assert vault.carpeta("materia") == raiz / "01_MATERIA"


def test_un_vault_inexistente_dice_como_crearlo(tmp_path):
    with pytest.raises(ErrorVault, match="crear-vault"):
        Vault.cargar(tmp_path / "no_existe")


def test_sin_vault_configurado_se_dice_donde_ponerlo():
    with pytest.raises(ErrorVault, match="TATEWARI_OBSIDIAN_VAULT"):
        Vault.cargar(None)


def test_crear_nota_no_pisa_un_archivo(vault_ks):
    vault, jaula = vault_ks
    existente = vault.carpeta("conceptos") / "Suelo.md"
    existente.write_text("mía", encoding="utf-8")

    ruta = vault.crear_nota(jaula, objeto(), {}, {})

    assert ruta.name == "Suelo (2).md"
    assert existente.read_text(encoding="utf-8") == "mía"


def test_una_nota_generada_no_nace_aprobada(vault_ks):
    vault, jaula = vault_ks

    with pytest.raises(ErrorVault, match="DRAFT o en REVIEW"):
        vault.crear_nota(jaula, objeto(estado="APPROVED"), {}, {})


def test_buscar_por_alias_y_plural(vault_ks):
    vault, jaula = vault_ks
    vault.crear_nota(jaula, objeto(alias=["tierra"]), {}, {})

    assert vault.buscar("tierra").nombre == "Suelo"
    assert vault.buscar("Suelos").nombre == "Suelo"
    assert vault.buscar("SUELO").nombre == "Suelo"
    assert vault.buscar("Horizonte") is None


@pytest.mark.parametrize(
    "preparar, motivo",
    [
        (lambda v, j: v.cambiar_estado(j, "Suelo", "APPROVED", "Pedro"), "APPROVED"),
        (lambda v, j: (v.carpeta("conceptos") / "Suelo.md").write_text(
            (v.carpeta("conceptos") / "Suelo.md").read_text(encoding="utf-8").replace("# Suelo", "# Suelo\n\nNota mía."),
            encoding="utf-8"), "a mano"),
    ],
)
def test_no_se_actualiza_lo_aprobado_ni_lo_editado(vault_ks, preparar, motivo):
    vault, jaula = vault_ks
    vault.crear_nota(jaula, objeto(), {}, {})
    preparar(vault, jaula)
    vault._notas = None
    nota = vault.buscar("Suelo")
    antes = nota.ruta.read_text(encoding="utf-8")

    with pytest.raises(ErrorVault, match=motivo):
        vault.actualizar_nota(jaula, nota, objeto(), {}, {})
    assert nota.ruta.read_text(encoding="utf-8") == antes


def test_una_nota_escrita_a_mano_nunca_se_reescribe(vault_ks):
    vault, _ = vault_ks
    (vault.carpeta("conceptos") / "Suelo.md").write_text("# Suelo\n\nMis apuntes.", encoding="utf-8")

    nota = vault.buscar("Suelo")

    assert not nota.gestionada
    assert "no la escribió Tatewari" in vault.motivo_para_no_tocar(nota)


def test_cambiar_estado_toca_solo_el_frontmatter_y_anota_quien(vault_ks):
    vault, jaula = vault_ks
    ruta = vault.crear_nota(jaula, objeto(), {}, {})
    cuerpo_antes = leer_nota(ruta.read_text(encoding="utf-8"))[1].split("%%")[0]

    vault.cambiar_estado(jaula, "Suelo", "APPROVED", "Pedro")

    campos, cuerpo, datos = leer_nota(ruta.read_text(encoding="utf-8"))
    assert campos["estado"] == "APPROVED"
    assert campos["approved_por"] == "Pedro"
    assert datos["estado"] == "APPROVED"
    esperado = cuerpo_antes.replace("Estado: DRAFT", "Estado: APPROVED").replace(
        AVISO_BORRADOR, aviso_aprobado("APPROVED", "Pedro", campos["approved_en"])
    )
    assert cuerpo.split("%%")[0] == esperado
    assert vault.buscar("Suelo").intacta


def test_el_aviso_visible_sigue_al_estado(vault_ks):
    """Una nota aprobada no puede seguir diciendo «no es conocimiento aprobado»."""
    vault, jaula = vault_ks
    ruta = vault.crear_nota(jaula, objeto(), {}, {})

    vault.cambiar_estado(jaula, "Suelo", "APPROVED", "Pedro")
    texto = ruta.read_text(encoding="utf-8")
    assert AVISO_BORRADOR not in texto
    assert "> Aprobado por Pedro el " in texto

    vault.cambiar_estado(jaula, "Suelo", "PUBLISHED", "Ana")
    texto = ruta.read_text(encoding="utf-8")
    assert "> Publicado por Ana el " in texto and "Aprobado por" not in texto

    vault.cambiar_estado(jaula, "Suelo", "REVIEW", "Ana")
    texto = ruta.read_text(encoding="utf-8")
    assert AVISO_BORRADOR in texto and "Publicado por" not in texto
    assert vault.buscar("Suelo").intacta


# ---------------------------------------------------------------------------
# Vínculos: duplicados y conflictos
# ---------------------------------------------------------------------------


def test_un_mismo_concepto_con_otro_nombre_es_posible_duplicado(vault_ks):
    vault, jaula = vault_ks
    vault.crear_nota(
        jaula,
        objeto(definiciones=[Afirmacion(texto="Capa superficial del terreno rica en humus y raíces", verificada=True)]),
        {}, {},
    )
    vault._notas = None
    nuevo = objeto(
        titulo="Capa arable",
        definiciones=[Afirmacion(texto="Capa superficial del terreno rica en humus y raíces", verificada=True)],
    )

    [accion] = planificar([nuevo], vault)

    assert accion.tipo == "crear"
    assert accion.posibles_duplicados == ["Suelo"]
    assert accion.objeto.estado == "REVIEW"


def test_mismo_nombre_y_nota_intacta_se_actualiza(vault_ks):
    vault, jaula = vault_ks
    vault.crear_nota(jaula, objeto(), {}, {})
    vault._notas = None

    [accion] = planificar([objeto(documentos=["b.md"], ubicaciones=["b.md, p. 3"])], vault)

    assert accion.tipo == "actualizar"
    assert "b.md, p. 3" in accion.objeto.ubicaciones
    assert "a.md, sección «El suelo»" in accion.objeto.ubicaciones


def test_cifras_distintas_de_dos_fuentes_son_conflicto():
    uno = Afirmacion(texto="Espesor de 10 a 30 cm.", documento="a.md", verificada=True)
    otro = Afirmacion(texto="Espesor de 20 a 50 cm.", documento="b.md", verificada=True)

    [conflicto] = detectar_conflictos([uno], [otro])

    assert conflicto["descripcion"] == "Las fuentes dan cifras distintas"
    assert [v["documento"] for v in conflicto["versiones"]] == ["a.md", "b.md"]


def test_las_inferencias_no_generan_conflictos():
    uno = Afirmacion(texto="Espesor de 10 cm.", documento="a.md", verificada=True)
    inferida = Afirmacion(texto="Espesor de 99 cm.", documento="b.md", origen="inferencia")

    assert detectar_conflictos([uno], [inferida]) == []


def test_el_mismo_documento_no_se_contradice_consigo_mismo():
    uno = Afirmacion(texto="10 cm.", documento="a.md", verificada=True)
    otro = Afirmacion(texto="30 cm.", documento="a.md", verificada=True)

    assert detectar_conflictos([uno], [otro]) == []


# ---------------------------------------------------------------------------
# Validación del Vault
# ---------------------------------------------------------------------------


def test_la_validacion_cuenta_estados_y_enlaces_pendientes(vault_ks):
    vault, jaula = vault_ks
    vault.crear_nota(
        jaula,
        objeto(relaciones=[Relacion(tipo="contiene", destino="Materia orgánica")]),
        {}, {},
    )

    resultado = validar_vault(vault)

    assert resultado.gestionadas == 1
    assert resultado.por_estado["DRAFT"] == 1
    assert "Materia orgánica" in resultado.pendientes
    assert resultado.valida


def test_la_validacion_avisa_de_lo_aprobado_sin_verificar(vault_ks):
    vault, jaula = vault_ks
    vault.crear_nota(
        jaula,
        objeto(definiciones=[Afirmacion(texto="Inferido.", origen="inferencia")], estado="REVIEW"),
        {}, {},
    )
    vault.cambiar_estado(jaula, "Suelo", "APPROVED", "Pedro")

    resultado = validar_vault(vault)

    assert any("ninguna definición se comprobó" in a for a in resultado.avisos)


def test_la_validacion_marca_una_nota_sin_fuente_como_error(vault_ks):
    vault, jaula = vault_ks
    vault.crear_nota(jaula, objeto(ubicaciones=[]), {}, {})

    resultado = validar_vault(vault)

    assert not resultado.valida
    assert any("no tiene ninguna fuente" in e for e in resultado.errores)
