"""Knowledge Studio de punta a punta: documento → notas en un Vault real en disco.

Es la prueba de integración: un documento de ejemplo pequeño de
`tests/fixtures/conocimiento`, un Vault temporal y un Ollama simulado. Comprueba
lo que le queda a quien usa el programa: archivos `.md` de verdad, con enlaces
`[[...]]` que Obsidian entiende, y nada inventado dentro.
"""

from __future__ import annotations

import requests
import pytest

from ayudas_conocimiento import (
    EDAFOLOGIA,
    OTRA_FUENTE,
    RESPUESTA_EDAFOLOGIA,
    RESPUESTA_INSUFICIENTE,
    RESPUESTA_OTRA_FUENTE,
    como_texto,
)
from fabricar_documentos import crear_docx, crear_pdf, crear_pptx
from tatewari.conocimiento.extraccion import pdf_disponible
from tatewari.conocimiento.markdown import enlaces_de, leer_nota
from tatewari.conocimiento.orquestador import interpretar_peticion
from tatewari.conocimiento.vault import NOMBRE_INDICE


@pytest.fixture
def procesado(orquestador_ks):
    """El documento de ejemplo ya procesado. Devuelve (orquestador, reporte)."""
    orquestador, _ = orquestador_ks([como_texto(RESPUESTA_EDAFOLOGIA)])
    return orquestador, orquestador.procesar_documento(EDAFOLOGIA)


# ---------------------------------------------------------------------------
# El recorrido completo
# ---------------------------------------------------------------------------


def test_procesar_crea_archivos_md_en_el_vault(procesado):
    orquestador, reporte = procesado
    conceptos = orquestador.vault.carpeta("conceptos")

    assert sorted(p.name for p in conceptos.glob("*.md")) == [
        "Horizonte A.md", "Materia orgánica.md", "Meteorización.md", "Suelo.md",
    ]
    assert reporte.nuevas == ["Suelo", "Horizonte A", "Meteorización", "Materia orgánica"]
    assert reporte.errores == []


def test_los_enlaces_son_texto_markdown_de_obsidian(procesado):
    orquestador, _ = procesado
    suelo = (orquestador.vault.carpeta("conceptos") / "Suelo.md").read_text(encoding="utf-8")

    enlaces = enlaces_de(suelo)

    assert "Material parental" in enlaces           # pendiente: Obsidian la ofrece crear
    assert "Materia orgánica" in enlaces            # otra nota de la misma tanda
    assert any(e.startswith("Fuente - ") for e in enlaces)
    assert "[[Materia orgánica]]" in suelo


def test_el_original_queda_en_la_materia_sin_tocar(procesado):
    orquestador, _ = procesado
    copia = orquestador.vault.carpeta("materia") / EDAFOLOGIA.name

    assert copia.read_bytes() == EDAFOLOGIA.read_bytes()


def test_la_nota_de_fuente_enlaza_todo_lo_extraido(procesado):
    orquestador, reporte = procesado
    fuente = orquestador.vault.carpeta("materia") / f"{reporte.nota_fuente}.md"
    campos, cuerpo, _ = leer_nota(fuente.read_text(encoding="utf-8"))

    assert campos["tipo"] == "fuente"
    assert campos["archivo"] == EDAFOLOGIA.name
    for nombre in ("Suelo", "Horizonte A", "Meteorización", "Materia orgánica"):
        assert f"[[{nombre}]]" in cuerpo
    assert f"[[{EDAFOLOGIA.name}]]" in cuerpo


def test_las_referencias_son_solo_las_del_documento(procesado):
    orquestador, reporte = procesado

    assert any("Pérez Ficticio" in r for r in reporte.referencias)
    assert any("Gómez Inventada" in r for r in reporte.referencias)
    assert not any("Smith" in r for r in reporte.referencias)
    # Y el DOI detectado sin modelo, por la vía determinista.
    assert any("10.0000/ficticio.001" in r for r in reporte.referencias)


def test_la_trazabilidad_llega_hasta_la_seccion(procesado):
    orquestador, _ = procesado
    nota = orquestador.vault.buscar("Horizonte A")

    assert nota.frontmatter["fuentes"] == ["edafologia_unidad1.md, sección «Horizontes del suelo»"]
    [definicion] = nota.objeto().definiciones
    assert definicion.ubicacion == "sección «Horizontes del suelo»"
    assert definicion.verificada


def test_lo_no_verificado_entra_en_review_y_lo_verificado_en_draft(procesado):
    orquestador, reporte = procesado

    assert orquestador.vault.buscar("Suelo").estado == "DRAFT"
    assert orquestador.vault.buscar("Materia orgánica").estado == "REVIEW"
    assert reporte.sin_verificar == 2  # la cita de Darwin y la inferencia declarada


def test_nada_nace_aprobado(procesado):
    orquestador, _ = procesado

    assert {n.estado for n in orquestador.conceptos()} <= {"DRAFT", "REVIEW"}


def test_el_indice_da_un_centro_a_la_vista_de_grafo(procesado):
    orquestador, _ = procesado
    indice = (orquestador.vault.raiz / f"{NOMBRE_INDICE}.md").read_text(encoding="utf-8")

    for nombre in ("Suelo", "Horizonte A", "Meteorización", "Materia orgánica"):
        assert f"[[{nombre}]]" in indice


def test_el_reporte_queda_en_el_vault_y_dice_lo_pedido(procesado):
    orquestador, reporte = procesado

    assert reporte.ruta_reporte.is_file()
    assert reporte.ruta_reporte.parent == orquestador.vault.carpeta("reportes")
    texto = reporte.texto()
    for dato in ("Archivo procesado", "Extensión", "Conocimiento", "Notas nuevas",
                 "Notas actualizadas", "Posibles duplicados", "Conflictos", "Referencias", "Errores"):
        assert dato in texto
    assert "6 secciones" in texto


def test_el_reporte_lista_las_herramientas_usadas(procesado):
    _, reporte = procesado

    usadas = " ".join(reporte.herramientas)
    for habilidad in ("document_ingest", "document_extract", "knowledge_extract",
                      "knowledge_link", "obsidian_create_note"):
        assert habilidad in usadas


# ---------------------------------------------------------------------------
# Actualizar, conflictos y lo que no se toca
# ---------------------------------------------------------------------------


def test_una_segunda_fuente_contradictoria_marca_conflicto_y_conserva_ambas(orquestador_ks):
    orquestador, _ = orquestador_ks([como_texto(RESPUESTA_EDAFOLOGIA), como_texto(RESPUESTA_OTRA_FUENTE)])
    orquestador.procesar_documento(EDAFOLOGIA)

    reporte = orquestador.procesar_documento(OTRA_FUENTE)

    assert reporte.actualizadas == ["Horizonte A"]
    assert reporte.conflictos == ["Horizonte A"]
    nota = orquestador.vault.buscar("Horizonte A")
    assert nota.estado == "REVIEW"
    textos = [d.texto for d in nota.objeto().definiciones]
    assert any("10 a 30" in t for t in textos) and any("20 a 50" in t for t in textos)
    assert "no elige una versión" in nota.cuerpo
    assert [n.nombre for n in orquestador.conflictos()] == ["Horizonte A"]


def test_lo_aprobado_nunca_se_sobrescribe_se_propone(orquestador_ks):
    orquestador, _ = orquestador_ks([como_texto(RESPUESTA_EDAFOLOGIA), como_texto(RESPUESTA_OTRA_FUENTE)])
    orquestador.procesar_documento(EDAFOLOGIA)
    orquestador.vault.cambiar_estado(orquestador.jaula, "Horizonte A", "APPROVED", "Pedro")
    ruta = orquestador.vault.buscar("Horizonte A").ruta
    aprobada = ruta.read_text(encoding="utf-8")

    reporte = orquestador.procesar_documento(OTRA_FUENTE)

    assert ruta.read_text(encoding="utf-8") == aprobada
    assert [n for n, _ in reporte.propuestas] == ["Horizonte A"]
    [propuesta] = list(orquestador.vault.carpeta("propuestas").glob("*.md"))
    assert "[[Horizonte A]]" in propuesta.read_text(encoding="utf-8")


def test_una_nota_editada_a_mano_tampoco_se_sobrescribe(orquestador_ks):
    orquestador, _ = orquestador_ks([como_texto(RESPUESTA_EDAFOLOGIA), como_texto(RESPUESTA_OTRA_FUENTE)])
    orquestador.procesar_documento(EDAFOLOGIA)
    ruta = orquestador.vault.buscar("Horizonte A").ruta
    editada = ruta.read_text(encoding="utf-8").replace("# Horizonte A", "# Horizonte A\n\nMi nota.")
    ruta.write_text(editada, encoding="utf-8")

    reporte = orquestador.procesar_documento(OTRA_FUENTE)

    assert ruta.read_text(encoding="utf-8") == editada
    assert "editó a mano" in reporte.propuestas[0][1]


def test_actualizar_resuelve_enlaces_nuevos_sin_modelo(orquestador_ks):
    orquestador, sesion = orquestador_ks([como_texto(RESPUESTA_EDAFOLOGIA)])
    orquestador.procesar_documento(EDAFOLOGIA)
    # Aparece a mano la nota «Material parental»: el enlace deja de estar pendiente.
    (orquestador.vault.carpeta("conceptos") / "Material parental.md").write_text("# Material parental\n", encoding="utf-8")
    peticiones = len(sesion.peticiones)

    resultado = orquestador.actualizar()

    assert "Material parental" not in resultado.pendientes
    assert len(sesion.peticiones) == peticiones  # sin modelo


# ---------------------------------------------------------------------------
# Errores: Ollama, respuestas inválidas, sin modelo
# ---------------------------------------------------------------------------


def test_una_respuesta_envuelta_en_texto_se_entiende(orquestador_ks):
    orquestador, _ = orquestador_ks([como_texto(RESPUESTA_EDAFOLOGIA, "Claro, aquí tienes:")])

    reporte = orquestador.procesar_documento(EDAFOLOGIA)

    assert len(reporte.nuevas) == 4


def test_una_respuesta_inservible_dos_veces_no_crea_nada(orquestador_ks):
    orquestador, sesion = orquestador_ks(["no tengo ni idea", "{esto: no es json}"])

    reporte = orquestador.procesar_documento(EDAFOLOGIA)

    assert reporte.nuevas == []
    assert reporte.trozos_analizados == 0
    assert any("ni al segundo intento" in a for a in reporte.avisos)
    assert len(sesion.cuerpos) == 2  # un intento y un reintento
    assert "IMPORTANTE" in sesion.cuerpos[1]["prompt"]
    # La fuente y el original sí quedan: el documento se leyó.
    assert (orquestador.vault.carpeta("materia") / EDAFOLOGIA.name).is_file()


def test_el_reintento_rescata_una_primera_respuesta_mala(orquestador_ks):
    orquestador, _ = orquestador_ks(["basura", como_texto(RESPUESTA_EDAFOLOGIA)])

    assert len(orquestador.procesar_documento(EDAFOLOGIA).nuevas) == 4


def test_un_fragmento_sin_informacion_suficiente_se_dice(orquestador_ks):
    orquestador, _ = orquestador_ks([como_texto(RESPUESTA_INSUFICIENTE)])

    reporte = orquestador.procesar_documento(EDAFOLOGIA)

    assert reporte.insuficientes == 1
    assert any("índice" in a for a in reporte.avisos)
    assert reporte.nuevas == []


def test_ollama_caido_se_informa_sin_romper(orquestador_ks):
    orquestador, sesion = orquestador_ks([])

    def caido(url, timeout=None):
        raise requests.ConnectionError("No se pudo establecer conexión")

    sesion.get = caido

    reporte = orquestador.procesar_documento(EDAFOLOGIA)

    assert any("ollama serve" in e for e in reporte.errores)
    assert reporte.nuevas == []


def test_un_modelo_forzado_que_no_existe_se_dice(vault_ks, ollama):
    from tatewari.conocimiento.enrutador import Enrutador
    from tatewari.conocimiento.orquestador import Orquestador

    vault, jaula = vault_ks
    cliente, _ = ollama(modelo="qwen3:inexistente")
    orquestador = Orquestador(vault, jaula, Enrutador.con_clientes({"extraccion": cliente}))

    reporte = orquestador.procesar_documento(EDAFOLOGIA)

    assert any("ollama pull qwen3:inexistente" in e for e in reporte.errores)


def test_sin_modelo_se_procesa_texto_fuente_y_referencias(orquestador_ks):
    orquestador, sesion = orquestador_ks([], sin_modelo=True)

    reporte = orquestador.procesar_documento(EDAFOLOGIA)

    assert sesion.peticiones == []
    assert reporte.nuevas == []
    assert reporte.nota_fuente.startswith("Fuente - ")
    assert any("10.0000/ficticio.001" in r for r in reporte.referencias)


# ---------------------------------------------------------------------------
# Otros formatos por el mismo camino
# ---------------------------------------------------------------------------


def _respuesta_minima(cita: str) -> str:
    return como_texto({"objetos": [{"titulo": "Acidez", "tipo": "concepto",
                                    "definicion": {"texto": "Medida de acidez.", "cita": cita}}]})


def test_procesar_un_docx(orquestador_ks, tmp_path):
    ruta = crear_docx(tmp_path / "clase.docx", [("Acidez", ["El pH mide la acidez de una disolución acuosa."])])
    orquestador, _ = orquestador_ks([_respuesta_minima("El pH mide la acidez de una disolución acuosa")])

    reporte = orquestador.procesar_documento(ruta)

    assert reporte.nuevas == ["Acidez"]
    assert orquestador.vault.buscar("Acidez").frontmatter["fuentes"] == ["clase.docx, sección «Acidez»"]


def test_procesar_un_pptx(orquestador_ks, tmp_path):
    ruta = crear_pptx(tmp_path / "clase.pptx", ["Portada", "El pH mide la acidez de una disolución acuosa."])
    orquestador, _ = orquestador_ks([_respuesta_minima("El pH mide la acidez de una disolución acuosa")])

    orquestador.procesar_documento(ruta)

    assert orquestador.vault.buscar("Acidez").frontmatter["fuentes"] == ["clase.pptx, diapositiva 2"]


@pytest.mark.skipif(not pdf_disponible(), reason="PyMuPDF no está instalado")
def test_procesar_un_pdf_con_su_pagina(orquestador_ks, tmp_path):
    ruta = crear_pdf(tmp_path / "clase.pdf", ["Portada del curso.", "El pH mide la acidez de una disolución acuosa."])
    orquestador, _ = orquestador_ks([_respuesta_minima("El pH mide la acidez de una disolución acuosa")])

    orquestador.procesar_documento(ruta)

    assert orquestador.vault.buscar("Acidez").frontmatter["fuentes"] == ["clase.pdf, p. 2"]


def test_analizar_materia_se_salta_lo_ya_procesado(orquestador_ks):
    orquestador, _ = orquestador_ks([como_texto(RESPUESTA_EDAFOLOGIA)])
    orquestador.procesar_documento(EDAFOLOGIA)

    resultados = orquestador.analizar_materia()

    assert (EDAFOLOGIA.name, "ya procesado (usa --forzar para repetir)") in resultados


# ---------------------------------------------------------------------------
# «Tatewari, procesa este documento»
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "frase, accion, argumento",
    [
        ("Tatewari, procesa este documento apuntes.pdf", "procesar", "apuntes.pdf"),
        ('procesa "C:/Mis apuntes/Clase 3.docx"', "procesar", "C:/Mis apuntes/Clase 3.docx"),
        ("lee «Unidad 2.pptx»", "procesar", "Unidad 2.pptx"),
        ("analiza la materia", "materia", None),
        ("crea la base de conocimiento", "crear-vault", None),
        ("actualiza el conocimiento existente", "actualizar", None),
        ("muestra los conceptos detectados", "conceptos", None),
        ("muéstrame los conflictos", "conflictos", None),
        ("genera el reporte", "reporte", None),
        ("apuntes.md", "procesar", "apuntes.md"),
    ],
)
def test_interpretar_peticiones_en_espanol(frase, accion, argumento):
    peticion = interpretar_peticion(frase)

    assert peticion is not None
    assert (peticion.accion, peticion.argumento) == (accion, argumento)


def test_una_peticion_sin_sentido_no_se_adivina():
    assert interpretar_peticion("¿qué tiempo hace mañana?") is None
