"""ZEA MAYZ: divulgación solo desde conocimiento aprobado, y su validación.

La regla que se prueba: ninguna afirmación científica del borrador narrativo
sale de la nada. Lo que no se apoya en un concepto APPROVED queda marcado.
"""

from __future__ import annotations

import json

import pytest

from ayudas_conocimiento import EDAFOLOGIA, RESPUESTA_EDAFOLOGIA, como_texto
from tatewari.conocimiento.habilidades import habilidades
from tatewari.conocimiento.objetos import ErrorEsquema
from tatewari.conocimiento.markdown import leer_nota
from tatewari.zea_mayz.divulgacion import (
    ErrorDivulgacion,
    construir_prompt,
    generar_borrador,
    seleccionar_base,
    validar_respuesta_narrativa,
)
from tatewari.zea_mayz.interfaces import (
    EspecificacionIlustracion,
    NoDisponible,
    SinGenerador,
    SinMaquetador,
)
from tatewari.zea_mayz.validacion import validar_archivo, validar_borrador


def _narrativa(afirmaciones, narracion="Lía mete la mano en la tierra húmeda.", recuadro=None):
    escena = {
        "titulo": "La tierra por dentro",
        "narracion": narracion,
        "personajes": ["Lía"],
        "dialogos": [{"personaje": "Lía", "texto": "¡Tiene capas!"}],
        "afirmaciones": afirmaciones,
        "vinetas": [{"descripcion": "Lía cava un hoyo", "texto": "¿Qué hay aquí?"}],
        "ilustracion": {"descripcion": "Corte del suelo", "elementos": ["horizonte A"], "conceptos": ["Horizonte A"]},
    }
    if recuadro:
        escena["recuadro"] = recuadro
    return json.dumps({"titulo": "Lía y el suelo", "capitulos": [{"titulo": "Bajo los pies", "escenas": [escena]}]},
                      ensure_ascii=False)


BIEN = _narrativa(
    [{"texto": "El horizonte A mide de 10 a 30 cm.", "conceptos": ["Horizonte A"]}],
    recuadro={"titulo": "¿Qué es el suelo?", "texto": "Minerales, agua y aire.", "conceptos": ["Suelo"]},
)

MAL = _narrativa(
    [
        {"texto": "El horizonte A mide de 10 a 30 cm.", "conceptos": ["Horizonte A"]},
        {"texto": "La materia orgánica es el alma del suelo.", "conceptos": ["Materia orgánica"]},
    ],
    narracion="Hace 45 años el abuelo de Lía araba este campo.",
)


@pytest.fixture
def con_aprobados(orquestador_ks):
    """Un Vault con el documento de ejemplo procesado y tres conceptos aprobados.

    «Materia orgánica» se queda en REVIEW: su cita era inventada.
    """

    def fabrica(*narrativas):
        orquestador, sesion = orquestador_ks([como_texto(RESPUESTA_EDAFOLOGIA), *narrativas])
        orquestador.procesar_documento(EDAFOLOGIA)
        for nombre in ("Suelo", "Horizonte A", "Meteorización"):
            orquestador.vault.cambiar_estado(orquestador.jaula, nombre, "APPROVED", "Pedro")
        return orquestador, sesion

    return fabrica


# ---------------------------------------------------------------------------
# La base: solo lo aprobado
# ---------------------------------------------------------------------------


def test_la_base_son_solo_las_notas_aprobadas(con_aprobados):
    orquestador, _ = con_aprobados()

    base, _ = seleccionar_base(orquestador.vault)

    assert sorted(n.nombre for n in base) == ["Horizonte A", "Meteorización", "Suelo"]


def test_pedir_un_concepto_sin_aprobar_se_descarta_con_aviso(con_aprobados):
    orquestador, _ = con_aprobados()

    base, avisos = seleccionar_base(orquestador.vault, nombres=["Suelo", "Materia orgánica", "Nada"])

    assert [n.nombre for n in base] == ["Suelo"]
    assert any("[[Materia orgánica]] está en REVIEW" in a for a in avisos)
    assert any("«Nada» no existe" in a for a in avisos)


def test_el_prompt_solo_lleva_hechos_comprobados(con_aprobados):
    orquestador, _ = con_aprobados()
    base, _ = seleccionar_base(orquestador.vault)

    prompt = construir_prompt("el suelo", base, "niños")

    assert "Descomposición física y química de las rocas" in prompt
    assert "10 a 30 cm" in prompt
    assert "tropicales" not in prompt           # era una inferencia del modelo
    assert "Darwin" not in prompt               # la nota no aprobada no entra
    assert "NO puedes añadir hechos" in prompt


def test_sin_nada_aprobado_no_se_genera(orquestador_ks):
    orquestador, sesion = orquestador_ks([como_texto(RESPUESTA_EDAFOLOGIA)])
    orquestador.procesar_documento(EDAFOLOGIA)
    peticiones = len(sesion.cuerpos)

    with pytest.raises(ErrorDivulgacion, match="APPROVED"):
        generar_borrador(orquestador.vault, orquestador.jaula, orquestador.enrutador)
    assert len(sesion.cuerpos) == peticiones  # ni se llamó al modelo


# ---------------------------------------------------------------------------
# La respuesta del modelo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("datos", [[], {}, {"capitulos": []}, {"capitulos": [{"escenas": [{"titulo": "sin narración"}]}]}])
def test_una_respuesta_narrativa_sin_forma_se_rechaza(datos):
    with pytest.raises(ErrorEsquema):
        validar_respuesta_narrativa(datos)


def test_una_respuesta_inservible_dos_veces_no_escribe_nada(con_aprobados):
    orquestador, _ = con_aprobados("nada", "{}")

    with pytest.raises(ErrorDivulgacion, match="No se ha escrito nada"):
        generar_borrador(orquestador.vault, orquestador.jaula, orquestador.enrutador)
    assert list(orquestador.vault.carpeta("guion").glob("*.md")) == []


# ---------------------------------------------------------------------------
# El borrador y su validación
# ---------------------------------------------------------------------------


def test_un_borrador_con_base_aprobada_es_valido(con_aprobados):
    orquestador, _ = con_aprobados(BIEN)

    resultado = generar_borrador(orquestador.vault, orquestador.jaula, orquestador.enrutador, tema="suelo")

    assert resultado.validacion.valida, resultado.validacion.resumen()
    assert resultado.validacion.afirmaciones == 1
    assert resultado.validacion.recuadros == 1


def test_el_borrador_se_reparte_en_sus_carpetas_y_nace_en_draft(con_aprobados):
    orquestador, _ = con_aprobados(BIEN)
    vault = orquestador.vault

    resultado = generar_borrador(vault, orquestador.jaula, orquestador.enrutador)

    assert resultado.guion.parent == vault.carpeta("guion")
    assert resultado.storyboard.parent == vault.carpeta("storyboard")
    assert resultado.ilustraciones.parent == vault.carpeta("ilustraciones")
    for ruta in (resultado.guion, resultado.storyboard, resultado.ilustraciones):
        campos, _, _ = leer_nota(ruta.read_text(encoding="utf-8"))
        assert campos["estado"] == "DRAFT"
    guion = resultado.guion.read_text(encoding="utf-8")
    assert "no es fuente científica" in guion
    assert "**Base:** [[Horizonte A]]" in guion
    assert f"[[{resultado.guion.stem}]]" in resultado.storyboard.read_text(encoding="utf-8")


def test_lo_no_aprobado_y_las_cifras_inventadas_se_marcan(con_aprobados):
    orquestador, _ = con_aprobados(MAL)

    resultado = generar_borrador(orquestador.vault, orquestador.jaula, orquestador.enrutador)
    validacion = resultado.validacion

    assert not validacion.valida
    assert validacion.respaldadas == 1
    [(texto, motivo)] = validacion.sin_respaldo
    assert "alma del suelo" in texto and "Materia orgánica" in motivo
    assert validacion.cifras_sin_respaldo == ["45"]   # 10 y 30 sí están en la base
    assert "[!danger]" in resultado.guion.read_text(encoding="utf-8")


def test_un_recuadro_sin_base_se_marca(con_aprobados):
    orquestador, _ = con_aprobados()
    texto = "# X\n\n> [!note] Recuadro científico: Raíces\n> Las raíces respiran.\n\nFin.\n"

    validacion = validar_borrador(texto, orquestador.vault)

    assert validacion.recuadros_sin_respaldo == [("Raíces", "no tiene línea de base")]


def test_una_base_que_no_existe_se_dice(con_aprobados):
    orquestador, _ = con_aprobados()
    texto = "- **Afirmación:** Las lombrices airean. · **Base:** [[Lombriz]]\n"

    validacion = validar_borrador(texto, orquestador.vault)

    assert validacion.sin_respaldo == [("Las lombrices airean.", "[[Lombriz]] no existe en el Vault")]


def test_tras_corregir_a_mano_la_validacion_se_rehace(con_aprobados):
    orquestador, _ = con_aprobados(MAL)
    resultado = generar_borrador(orquestador.vault, orquestador.jaula, orquestador.enrutador)
    ruta = resultado.guion
    texto = ruta.read_text(encoding="utf-8")
    texto = "\n".join(l for l in texto.split("\n") if "alma del suelo" not in l)
    texto = texto.replace("Hace 45 años el abuelo", "Hace tiempo el abuelo")
    ruta.write_text(texto, encoding="utf-8")

    validacion = validar_archivo(ruta, orquestador.vault)

    assert validacion.valida, validacion.resumen()


def test_aprobar_el_concepto_que_faltaba_tambien_lo_arregla(con_aprobados):
    orquestador, _ = con_aprobados()
    texto = "- **Afirmación:** Hay materia orgánica. · **Base:** [[Materia orgánica]]\n"
    assert not validar_borrador(texto, orquestador.vault).valida

    orquestador.vault.cambiar_estado(orquestador.jaula, "Materia orgánica", "APPROVED", "Pedro")

    assert validar_borrador(texto, orquestador.vault).valida


# ---------------------------------------------------------------------------
# Lo que todavía no existe dice que no existe
# ---------------------------------------------------------------------------


def test_generar_imagenes_y_maquetar_no_estan_y_lo_dicen(tmp_path):
    especificacion = EspecificacionIlustracion(identificador="1.1", descripcion="Corte del suelo", elementos=["horizonte A"], conceptos=["Horizonte A"])

    with pytest.raises(NoDisponible):
        SinGenerador().generar(especificacion, tmp_path / "a.png")
    with pytest.raises(NoDisponible):
        SinMaquetador().maquetar([tmp_path / "a.md"], tmp_path / "libro.pdf")
    assert not (tmp_path / "a.png").exists()


def test_las_habilidades_de_zea_mayz_estan_registradas():
    import tatewari.zea_mayz  # noqa: F401  (registra al importarse)

    nombres = {h.nombre for h in habilidades()}

    assert {"divulgacion_cientifica", "divulgacion_validar"} <= nombres
