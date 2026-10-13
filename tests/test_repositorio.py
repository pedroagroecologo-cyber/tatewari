"""Pruebas del repositorio en sí: lo que AGENTS.md exige del código y los datos.

No prueban una función: prueban que el repositorio cumple sus propias reglas.
Son las que avisan cuando alguien añade un `open()` sin encoding o deja un
mensaje en inglés, que son fallos que no rompen ninguna prueba funcional y
aparecen meses después en la máquina de otra persona.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FUENTES = sorted((Path(__file__).resolve().parents[1] / "src" / "tatewari").rglob("*.py"))
PRUEBAS = sorted((Path(__file__).resolve().parent).glob("*.py"))


def _leer(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8")


def test_hay_modulos_que_probar():
    """Si el glob se queda vacío, las pruebas de abajo pasarían sin mirar nada."""
    assert len(FUENTES) >= 10


# ---------------------------------------------------------------------------
# Regla 8: Windows primero
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ruta", FUENTES, ids=lambda r: r.name)
def test_todo_open_lleva_encoding_explicito(ruta):
    """AGENTS.md, regla 8: sin `encoding`, Windows usa la página de códigos local.

    Se mira el `open(` y lo que sigue hasta su paréntesis de cierre, porque la
    llamada suele ir partida en varias líneas.
    """
    texto = _leer(ruta)
    # `(?<!\.)`: el `open` de Python, no el método de otra librería
    # (`pymupdf.open`, `zipfile.ZipFile.open`), que no abre texto.
    for encontrado in re.finditer(r"(?<![.\w])open\(", texto):
        inicio = encontrado.end()
        profundidad = 1
        indice = inicio
        while indice < len(texto) and profundidad:
            if texto[indice] == "(":
                profundidad += 1
            elif texto[indice] == ")":
                profundidad -= 1
            indice += 1
        llamada = texto[inicio : indice - 1]
        # En modo binario Python no admite `encoding` (lanza ValueError): la
        # regla 8 va de archivos de texto.
        if re.search(r"""["'][rwax+]*b[rwax+]*["']""", llamada):
            continue
        assert "encoding=" in llamada, (
            f"{ruta.name}: un open() sin encoding=\"utf-8\" "
            f"(AGENTS.md, regla 8): open({llamada[:80]}…"
        )


@pytest.mark.parametrize("ruta", FUENTES, ids=lambda r: r.name)
def test_ningun_archivo_de_codigo_tiene_crlf(ruta):
    """El código va en LF; el `.gitattributes` solo excepciona .bat, .cmd y .ps1."""
    assert b"\r\n" not in ruta.read_bytes()


@pytest.mark.parametrize("ruta", FUENTES, ids=lambda r: r.name)
def test_no_se_concatenan_rutas_con_barras(ruta):
    """Las rutas se construyen con `pathlib`, no pegando cadenas con «/»."""
    texto = _leer(ruta)
    sospechosas = re.findall(r'\w+\s*\+\s*"/[a-z_]+\.(?:json|csv|txt|bib|md)"', texto)

    assert not sospechosas, f"{ruta.name}: rutas concatenadas: {sospechosas}"


# ---------------------------------------------------------------------------
# Regla 1: nada de modelos en la nube
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ruta", FUENTES, ids=lambda r: r.name)
def test_no_se_llama_a_ningun_modelo_en_la_nube(ruta):
    """AGENTS.md, regla 1. Ni el SDK, ni la clave, ni un «por si acaso»."""
    texto = _leer(ruta)
    # Se buscan los import y las URL, no la palabra suelta: los docstrings del
    # proyecto nombran a estos servicios justamente para decir que no se usan.
    prohibidos = re.findall(
        r"^\s*(?:import|from)\s+(openai|anthropic|cohere|mistralai|google\.generativeai"
        r"|langchain\w*|transformers|sentence_transformers)\b",
        texto,
        re.M,
    )
    assert not prohibidos, f"{ruta.name}: importa {prohibidos}"

    urls = re.findall(r"https?://(?!localhost|127\.0\.0\.1)([a-zA-Z0-9.-]+)", texto)
    permitidos = {
        # Las fuentes que autoriza AGENTS.md, regla 5.
        "api.openalex.org",
        "api.crossref.org",
        "api.unpaywall.org",
        "unpaywall.org",
        "doi.org",
        "dx.doi.org",
        "arxiv.org",
        "www.ncbi.nlm.nih.gov",
        # Tesauros para sugerir términos del protocolo (AGENTS.md, regla 5).
        "agrovoc.fao.org",
        "www.wikidata.org",
        # Y las que solo se citan en la documentación de los módulos.
        "docs.openalex.org",
        "api.crossref.org",
        "github.com",
        "ollama.com",
        "www.python.org",
        # Espacios de nombres XML de DOCX y PPTX: son identificadores escritos
        # dentro del formato, no direcciones que se consulten.
        "schemas.openxmlformats.org",
        "purl.org",
    }
    ajenas = sorted(set(urls) - permitidos)
    assert not ajenas, f"{ruta.name}: URL de un servicio no autorizado: {ajenas}"


def test_no_se_leen_claves_de_api_de_ningun_proveedor():
    for ruta in FUENTES:
        texto = _leer(ruta)
        encontrados = re.findall(
            r"(OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY|HF_TOKEN"
            r"|COHERE_API_KEY|MISTRAL_API_KEY)",
            texto,
        )
        assert not encontrados, f"{ruta.name}: lee {encontrados}"


def test_los_datos_que_el_paquete_lee_en_ejecucion_estan_declarados():
    """`biblioteca.py` lee `esquema.sql` al abrirse.

    Sin declararlo como `package-data`, una instalación no editable no lo copia y
    la biblioteca falla en la máquina de otra persona. Con `pip install -e .` no
    se nota, porque lee del árbol de fuentes: es de los fallos que solo aparecen
    al instalar de verdad.
    """
    paquete = FUENTES[0].parent
    # Fuera lo que Python genera solo: los .pyc de __pycache__ no se empaquetan.
    datos = {
        ruta.suffix
        for ruta in paquete.rglob("*")
        if ruta.is_file()
        and ruta.suffix not in ("", ".py", ".pyc", ".pyo")
        and "__pycache__" not in ruta.parts
    }
    pyproject = _leer(RAIZ / "pyproject.toml")

    for sufijo in datos:
        # Vale «"*.sql"» y también «"plantillas/*.md"»: lo que importa es que el
        # patrón que cubre esa extensión esté declarado.
        assert f'*{sufijo}"' in pyproject, (
            f"el paquete trae archivos {sufijo} que pyproject.toml no declara "
            f"en [tool.setuptools.package-data]"
        )


def test_las_dependencias_no_traen_ningun_sdk_de_la_nube():
    pyproject = _leer(Path(__file__).resolve().parents[1] / "pyproject.toml")

    for prohibido in (
        "openai",
        "anthropic",
        "cohere",
        "mistralai",
        "google-generativeai",
        "langchain",
        "transformers",
        "sentence-transformers",
    ):
        assert prohibido not in pyproject, f"pyproject.toml declara {prohibido}"


# ---------------------------------------------------------------------------
# Regla 7: todo el texto de cara al usuario, en español
# ---------------------------------------------------------------------------

#: Palabras que delatan un mensaje en inglés dentro de un `print` o un `raise`.
#:
#: Ojo con lo que **no** está: «error» es palabra española además de inglesa
#: («Ecuaciones con error», «Sin cribar: {error}»), así que buscarla da falsos
#: positivos y esconde los de verdad detrás del ruido. Igual con «total» o
#: «version». Aquí solo van palabras que en español no existen.
_INGLES = re.compile(
    r'"[^"]*\b(?:failed|failure|invalid|must|should|cannot|can\'t|unable'
    r"|missing|required|unexpected|not found|unknown|warning|please"
    r"|the|there|this|with|without|found)\b[^\"]*\"",
    re.IGNORECASE,
)


@pytest.mark.parametrize("ruta", FUENTES, ids=lambda r: r.name)
def test_los_mensajes_al_usuario_van_en_espanol(ruta):
    """AGENTS.md, regla 7. Se mira solo lo que se imprime o se lanza."""
    texto = _leer(ruta)
    sospechosos: list[str] = []

    for linea in re.findall(r"^\s*(?:print|raise|.*Error)\(.*$", texto, re.M):
        for cadena in _INGLES.findall(linea):
            sospechosos.append(linea.strip()[:90])

    assert not sospechosos, f"{ruta.name}: posible inglés: {sospechosos}"


# ---------------------------------------------------------------------------
# Regla 2: nada de datos inventados en los archivos de ejemplo
# ---------------------------------------------------------------------------


def test_el_env_de_ejemplo_no_trae_el_correo_de_nadie():
    """Un correo real en la plantilla acaba mandado a tres APIs por error."""
    ejemplo = _leer(Path(__file__).resolve().parents[1] / ".env.example")

    correos = re.findall(r"TATEWARI_MAILTO=(\S+)", ejemplo)
    assert correos, "la plantilla tiene que traer la variable"
    for correo in correos:
        dominio = correo.split("@")[-1].lower()
        assert dominio in ("institucion.edu", "ejemplo.com", "ejemplo.invalid"), (
            f".env.example trae un correo que parece real: {correo}"
        )
    assert "PON AQUI TU PROPIO CORREO" in ejemplo


def test_el_env_de_ejemplo_declara_las_tres_variables():
    ejemplo = _leer(Path(__file__).resolve().parents[1] / ".env.example")

    for variable in ("TATEWARI_MAILTO", "TATEWARI_OLLAMA", "TATEWARI_DATOS"):
        assert variable in ejemplo


# ---------------------------------------------------------------------------
# El lanzador de Windows
# ---------------------------------------------------------------------------

RAIZ = Path(__file__).resolve().parents[1]
SCRIPTS = RAIZ / "scripts" / "windows"


def test_estan_los_dos_scripts_de_windows():
    assert (SCRIPTS / "tatewari.bat").is_file()
    assert (SCRIPTS / "crear-acceso-directo.ps1").is_file()


@pytest.mark.parametrize(
    "nombre", ["tatewari.bat", "tatewari-interfaz.bat", "crear-acceso-directo.ps1"]
)
def test_los_scripts_de_windows_van_en_crlf(nombre):
    """cmd.exe se rompe con un bloque `if` en finales de línea de Unix.

    Y se comprueba en el archivo de trabajo, no solo en el `.gitattributes`: es
    el archivo que la persona va a ejecutar.
    """
    crudo = (SCRIPTS / nombre).read_bytes()

    assert b"\r\n" in crudo
    # Ni un solo \n suelto.
    assert crudo.replace(b"\r\n", b"").count(b"\n") == 0


def test_el_gitattributes_fuerza_crlf_en_los_scripts():
    atributos = _leer(RAIZ / ".gitattributes")

    for patron in ("*.bat", "*.cmd", "*.ps1"):
        assert f"{patron} text eol=crlf" in atributos
    # Y el resto del repositorio en LF.
    assert "eol=lf" in atributos


def test_el_lanzador_comprueba_python_crea_el_entorno_e_instala():
    bat = _leer(SCRIPTS / "tatewari.bat")

    assert "py -3.12" in bat
    assert "-m venv" in bat
    assert "pip install -e" in bat
    # Y deja una consola abierta, que es el punto de un lanzador.
    assert "cmd /k" in bat


@pytest.mark.parametrize("nombre", ["tatewari.bat", "tatewari-interfaz.bat"])
def test_el_lanzador_no_lleva_acentos(nombre):
    """La consola de Windows arranca con la página de códigos local."""
    bat = (SCRIPTS / nombre).read_bytes()

    assert bat.decode("ascii")


def test_el_lanzador_de_la_interfaz_abre_la_interfaz_y_espera_a_ollama():
    bat = _leer(SCRIPTS / "tatewari-interfaz.bat")

    assert "-m tatewari interfaz --esperar-ollama" in bat
    # Sin entorno no intenta nada: manda a abrir antes el lanzador de siempre.
    assert "tatewari.bat" in bat


def test_el_creador_de_accesos_directos_crea_tambien_el_de_la_interfaz():
    ps1 = _leer(SCRIPTS / "crear-acceso-directo.ps1")

    assert "tatewari-interfaz.bat" in ps1


def test_el_acceso_directo_usa_la_raiz_como_carpeta_de_trabajo():
    """Sin esto, «protocolos\\humedales.json» no lo encuentra."""
    ps1 = _leer(SCRIPTS / "crear-acceso-directo.ps1")

    assert "WorkingDirectory" in ps1
    assert "TargetPath" in ps1
    # El Escritorio se pregunta al sistema: con OneDrive no está en USERPROFILE.
    assert "GetFolderPath('Desktop')" in ps1


# ---------------------------------------------------------------------------
# El README tiene que poder seguirse al pie de la letra
# ---------------------------------------------------------------------------


def _ordenes_del_readme() -> list[list[str]]:
    """Cada `python -m tatewari …` que aparece en el README, ya troceado."""
    import shlex

    texto = _leer(RAIZ / "README.md")
    ordenes = []
    for linea in re.findall(r"^python -m tatewari (.+)$", texto, re.M):
        try:
            ordenes.append(shlex.split(linea))
        except ValueError:
            # Una línea con comillas sin cerrar es un error del README en sí.
            pytest.fail(f"orden del README mal escrita: {linea}")
    return ordenes


def test_el_readme_trae_el_recorrido_completo():
    ordenes = _ordenes_del_readme()

    usadas = {partes[0] for partes in ordenes}
    for esperada in (
        "protocolo",
        "cosechar",
        "cribar",
        "pendientes",
        "decidir",
        "texto-completo",
        "exportar",
        "estado",
    ):
        assert esperada in usadas, f"el README no muestra «{esperada}»"


@pytest.mark.parametrize("partes", _ordenes_del_readme(), ids=lambda p: " ".join(p))
def test_cada_orden_del_readme_existe_de_verdad(partes):
    """Si el README documenta una opción que no existe, esto lo dice.

    Es lo que mantiene honesta la promesa de que alguien puede seguir el README
    al pie de la letra: se comprueba que el analizador de argumentos acepta cada
    orden tal como está escrita, sin ejecutarla.
    """
    from tatewari.cli import construir_parser

    parser = construir_parser()
    try:
        parser.parse_args(partes)
    except SystemExit as salida:
        # `--help` termina con 0, y eso es que funcionó. Lo que delata un README
        # desfasado es un código distinto: argparse sale con 2 al no reconocer
        # una orden o una opción.
        if salida.code not in (0, None):
            pytest.fail(
                f"el README documenta una orden que la CLI rechaza "
                f"(código {salida.code}): python -m tatewari {' '.join(partes)}"
            )


def test_el_readme_lista_todos_los_subcomandos():
    """La tabla de subcomandos no puede quedarse corta cuando se añade uno."""
    from tatewari.cli import construir_parser

    parser = construir_parser()
    acciones = [
        a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"
    ]
    nombres = sorted(acciones[0].choices)
    readme = _leer(RAIZ / "README.md")

    faltan = [nombre for nombre in nombres if f"`{nombre}" not in readme]
    assert not faltan, f"el README no documenta: {faltan}"


def test_el_readme_dice_que_modelos_descargar_para_cuatro_gigas():
    readme = _leer(RAIZ / "README.md")

    assert "ollama pull llama3.2:3b" in readme
    assert "ollama pull nomic-embed-text" in readme
    assert "4 GB de VRAM" in readme
    # Y avisa de lo que NO hay que descargar, que es la mitad del consejo.
    assert "No descargues un 8B" in readme


def test_el_readme_dice_que_no_se_eluden_muros_de_pago():
    """AGENTS.md, regla 5, donde lo va a leer quien tenga el problema."""
    readme = _leer(RAIZ / "README.md")

    assert "no elude muros de pago" in readme
    assert "Sci-Hub" in readme


def test_el_readme_deja_escrito_que_la_similitud_no_decide():
    """Lo pidió el encargo de embeddings, y es fácil que se caiga al reescribir."""
    readme = _leer(RAIZ / "README.md")

    assert "ayuda de lectura, no un criterio de inclusión" in readme


def test_el_readme_documenta_el_lanzador_de_windows():
    readme = _leer(RAIZ / "README.md")

    assert "tatewari.bat" in readme
    assert "crear-acceso-directo.ps1" in readme


# ---------------------------------------------------------------------------
# Que no quede código muerto que la CLI no alcanza
# ---------------------------------------------------------------------------


def test_cada_modulo_se_alcanza_desde_la_linea_de_ordenes():
    """Un módulo que nadie importa es código que nadie ejecuta.

    Esta prueba pilló que `fuentes/unpaywall.py` estaba entero sin usar antes de
    que existiera la orden `texto-completo`.
    """
    import tatewari.cli  # noqa: F401 - se importa para recorrer sus módulos
    import sys

    cargados = {
        nombre
        for nombre in sys.modules
        if nombre.startswith("tatewari.") and not nombre.endswith("__main__")
    }
    esperados = {
        f"tatewari.{ruta.relative_to(FUENTES[0].parent).with_suffix('').as_posix().replace('/', '.')}"
        for ruta in FUENTES
        if ruta.name not in ("__init__.py", "__main__.py")
    }
    faltan = sorted(esperados - cargados)

    assert not faltan, (
        f"estos módulos no los alcanza la CLI: {faltan}. "
        f"O se usan, o no deberían estar."
    )
