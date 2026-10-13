"""El asistente: toda la revisión paso a paso, sin memorizar órdenes.

Tatewari tiene una orden por paso (``protocolo validar``, ``cosechar``,
``cribar``, ``texto-completo``, ``descargar``, ``exportar``…) y hay que saber
cuál va después de cuál, repetir la cosecha hasta que termine y recordar el
nombre de la revisión en cada una. Para quien empieza, eso es una barrera.

``tatewari asistente`` hace el recorrido completo en una conversación:

1. revisa la configuración (correo y clave de OpenAlex) y explica cómo
   arreglarla si falta;
2. ofrece los protocolos de ``protocolos/`` para escoger uno y lo valida;
3. ofrece **explorar** el tema por significado para ver qué se le escapa al
   protocolo antes de gastar cuota;
4. cosecha y **repite sola** hasta que no queden ecuaciones;
5. criba, busca los textos completos, baja los PDF y exporta las notas;
6. ofrece ligar la revisión a la bóveda de Obsidian.

Cada paso dice qué va a hacer y por qué, y **pregunta antes** de lo que gasta
cuota o escribe fuera de la carpeta de la revisión. Debajo corre exactamente la
misma orden que se escribiría a mano, y la imprime, para que quien quiera
aprenda la orden.

El asistente no decide por la persona: los dudosos se quedan para ella, con la
orden para resolverlos.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

__all__ = ["Asistente", "BOVEDAS_PROBABLES"]

#: Dónde suele estar la bóveda de Obsidian, según la guía de la clase.
BOVEDAS_PROBABLES = (
    Path.home() / "Documentos" / "Tesis",
    Path.home() / "Documents" / "Tesis",
)

#: Vueltas máximas de cosecha: una revisión normal termina mucho antes. Es un
#: tope de seguridad para no quedarse en bucle si algo se atora.
MAX_VUELTAS = 40


@dataclass
class Asistente:
    """La conversación. Todo lo que toca el mundo se inyecta, para probarlo."""

    ejecutar: Callable[[list[str]], int]
    preguntar: Callable[[str], str] = input
    decir: Callable[[str], None] = print
    cargar_config: Callable[[], Any] | None = None
    cargar_protocolo: Callable[[Path], Any] | None = None
    pendientes_de: Callable[[str, Any, Any], int] | None = None
    carpeta_protocolos: Path = Path("protocolos")
    bovedas: tuple[Path, ...] = BOVEDAS_PROBABLES
    si_a_todo: bool = False
    pasos: list[str] = field(default_factory=list)

    # -- Conversación --------------------------------------------------------

    def titulo(self, numero: int, texto: str) -> None:
        self.decir("")
        self.decir(f"── Paso {numero}. {texto} " + "─" * max(0, 60 - len(texto)))

    def confirmar(self, pregunta: str, por_defecto: bool = True) -> bool:
        if self.si_a_todo:
            return por_defecto
        opciones = "[S/n]" if por_defecto else "[s/N]"
        respuesta = self.preguntar(f"{pregunta} {opciones} ").strip().lower()
        if respuesta in ("q", "salir"):
            raise Salir()
        if not respuesta:
            return por_defecto
        return respuesta[0] in ("s", "y")

    def pedir(self, pregunta: str, por_defecto: str = "") -> str:
        if self.si_a_todo:
            return por_defecto
        sugerencia = f" [{por_defecto}]" if por_defecto else ""
        respuesta = self.preguntar(f"{pregunta}{sugerencia}: ").strip()
        if respuesta.lower() in ("q", "salir"):
            raise Salir()
        return respuesta or por_defecto

    def correr(self, argumentos: list[str]) -> int:
        """Corre una orden de Tatewari y la enseña tal como se escribiría."""
        visible = " ".join(f'"{a}"' if " " in a else a for a in argumentos)
        self.decir(f"$ tatewari {visible}")
        self.pasos.append(visible)
        return self.ejecutar(argumentos)

    # -- Recorrido -------------------------------------------------------------

    def recorrer(self) -> int:
        try:
            return self._recorrer()
        except (Salir, EOFError, KeyboardInterrupt):
            self.decir("")
            self.decir("Saliste del asistente. Lo hecho está guardado; vuelve a lanzarlo y sigue donde ibas.")
            self._recapitular()
            return 0

    def _recorrer(self) -> int:
        self.decir("Asistente de Tatewari: tu revisión sistemática, paso a paso.")
        self.decir("Enter acepta la opción en mayúscula; «q» sale en cualquier momento.")

        config = self._paso_configuracion()
        if config is None:
            return 3
        ruta, protocolo = self._paso_protocolo()
        if protocolo is None:
            return 1
        revision = self._paso_revision(ruta)
        self._paso_explorar(ruta)
        if not self._paso_cosechar(revision, ruta, protocolo, config):
            return 4
        self.titulo(6, "Cribar: quitar duplicados y aplicar tus reglas")
        if self.correr(["cribar", revision, "--protocolo", str(ruta)]) != 0:
            return 5
        self._paso_dudosos(revision)
        self._paso_textos(revision, ruta, config)
        self.titulo(10, "Exportar: bibliografía, fichas y notas de Obsidian")
        self.correr(["exportar", revision, "--protocolo", str(ruta)])
        self._paso_obsidian(config)
        self._recapitular()
        return 0

    def _paso_configuracion(self) -> Any:
        self.titulo(1, "Revisar tu configuración (.env)")
        try:
            config = self.cargar_config() if self.cargar_config else None
        except Exception as error:  # ErrorConfig: se explica y se sale
            self.decir(f"No pude leer la configuración: {error}")
            return None
        if config is None:
            return None
        if not getattr(config, "tiene_mailto", False):
            self.decir(
                "Falta tu correo. Abre el archivo .env (por ejemplo: nano .env) y pon "
                "TATEWARI_MAILTO=tu.correo@institucion, sin espacios ni comillas. Sin "
                "correo OpenAlex te atiende peor y Unpaywall no responde."
            )
            return None
        self.decir(f"Correo: {config.mailto}")
        if getattr(config, "openalex_key", ""):
            self.decir("Clave de OpenAlex: puesta (10,000 consultas al día).")
        else:
            self.decir(
                "Clave de OpenAlex: no hay. Funciona igual, con 1,000 consultas al día. "
                "Para tener 10,000, saca una gratis en openalex.org/settings/api y ponla "
                "en .env como TATEWARI_OPENALEX_KEY."
            )
        return config

    def _paso_protocolo(self) -> tuple[Path, Any]:
        self.titulo(2, "Escoger el protocolo de búsqueda")
        disponibles = sorted(self.carpeta_protocolos.glob("*.json"))
        for numero, ruta in enumerate(disponibles, start=1):
            self.decir(f"  {numero}. {ruta}")
        self.decir(
            "Si aún no tienes el tuyo, pídeselo a un chat con el prompt de la clase, "
            "guárdalo en protocolos/ y vuelve a lanzar el asistente."
        )
        while True:
            eleccion = self.pedir(
                "Número o ruta del protocolo", "1" if disponibles else ""
            )
            if eleccion.isdigit() and 1 <= int(eleccion) <= len(disponibles):
                ruta = disponibles[int(eleccion) - 1]
            else:
                ruta = Path(eleccion)
            if not ruta.is_file():
                self.decir(f"No encuentro {ruta}.")
                if self.si_a_todo:
                    return ruta, None
                continue
            break
        if self.correr(["protocolo", "validar", str(ruta)]) != 0:
            self.decir(
                "El protocolo tiene errores. Copia los mensajes de arriba tal cual, "
                "pégaselos al chat y pídele que corrija solo eso."
            )
            return ruta, None
        return ruta, self.cargar_protocolo(ruta) if self.cargar_protocolo else object()

    def _paso_revision(self, ruta: Path) -> str:
        self.titulo(3, "Ponerle nombre a la revisión")
        self.decir("Es el nombre de la carpeta donde queda todo (revisiones/<nombre>).")
        nombre = self.pedir("Nombre, sin espacios", ruta.stem)
        return nombre.replace(" ", "_") or ruta.stem

    def _paso_explorar(self, ruta: Path) -> None:
        self.titulo(4, "Auditar el protocolo por significado (opcional)")
        self.decir(
            "OpenAlex busca los trabajos más parecidos a tu tema y Tatewari te dice "
            "cuáles se le escaparían a tu protocolo. Gasta una consulta."
        )
        if not self.confirmar("¿Exploramos?", por_defecto=not self.si_a_todo):
            return
        tema = self.pedir("Describe tu tema en una línea, en español o inglés")
        if not tema:
            return
        self.correr(["explorar", tema, "--protocolo", str(ruta)])
        self.decir(
            "Si se escapan muchos trabajos pertinentes, conviene corregir el protocolo "
            "antes de cosechar. Puedes salir con «q», corregirlo y volver."
        )
        self.confirmar("¿Seguimos con este protocolo?")

    def _paso_cosechar(self, revision: str, ruta: Path, protocolo: Any, config: Any) -> bool:
        self.titulo(5, "Cosechar en OpenAlex")
        total = getattr(protocolo, "numero_de_ecuaciones", 0)
        total = total() if callable(total) else total
        if total:
            self.decir(
                f"Tu protocolo genera {total} búsquedas. Cada una gasta entre 1 y 3 "
                "consultas de tu cuota del día. Si se corta, no se pierde nada."
            )
        if not self.confirmar("¿Cosechamos?"):
            return False
        anteriores = None
        for _ in range(MAX_VUELTAS):
            if self.correr(["cosechar", revision, "--protocolo", str(ruta)]) != 0:
                self.decir("La cosecha se detuvo con un error; lo de arriba dice por qué.")
                return False
            if self.pendientes_de is None:
                return True
            faltan = self.pendientes_de(revision, protocolo, config)
            if faltan == 0:
                self.decir("Cosecha completa.")
                return True
            if faltan == anteriores:
                self.decir(
                    "La cosecha no avanzó (¿se acabó la cuota del día?). Lo hecho está "
                    "guardado: vuelve a lanzar el asistente mañana."
                )
                return False
            anteriores = faltan
            self.decir(f"Faltan {faltan} búsquedas; sigo.")
        return True

    def _paso_dudosos(self, revision: str) -> None:
        self.titulo(7, "Los dudosos los decides tú")
        self.decir(
            "El filtro no descarta nada en automático que no esté claro: lo dudoso "
            "espera a una persona. Puedes resolverlo después, con calma:"
        )
        self.decir(f"  tatewari pendientes {revision}")
        self.decir(f'  tatewari decidir {revision} R0007 --decision incluir --motivo "…"')
        self.decir("La lista también queda en revision-manual.md, con la orden ya escrita.")

    def _paso_textos(self, revision: str, ruta: Path, config: Any) -> None:
        self.titulo(8, "Buscar los textos completos legales (Unpaywall)")
        self.decir("Tarda alrededor de un segundo por artículo incluido.")
        if self.confirmar("¿Los buscamos?"):
            self.correr(["texto-completo", revision, "--protocolo", str(ruta)])
        self.titulo(9, "Bajar los PDF abiertos")
        self.decir(
            "Baja a pdf/ los que la editorial entrega a un programa; los demás quedan "
            "en para-abrir.md, con su enlace, para abrirlos en tu navegador."
        )
        if self.confirmar("¿Los bajamos?"):
            self.correr(["descargar", revision, "--protocolo", str(ruta)])

    def _paso_obsidian(self, config: Any) -> None:
        self.titulo(11, "Ver las notas en Obsidian")
        datos = Path(getattr(config, "datos", "revisiones")).resolve()
        boveda = next((b for b in self.bovedas if b.is_dir()), None)
        if boveda is None:
            self.decir(
                "No encontré tu bóveda de Obsidian. Las notas están en "
                f"{datos}/<revisión>/notas: puedes abrir esa carpeta como bóveda."
            )
            return
        enlace = boveda / "Tatewari"
        if enlace.exists() or enlace.is_symlink():
            self.decir(f"Tu bóveda ya tiene la carpeta {enlace}: las notas aparecen ahí.")
            return
        self.decir(
            f"Puedo ligar tus revisiones a tu bóveda ({boveda}) con un enlace "
            f"simbólico: la carpeta {enlace} apuntará a {datos}, y cada vez que "
            "exportes las notas aparecerán solas."
        )
        if not self.confirmar("¿Creo el enlace?", por_defecto=False):
            self.decir(f"Cuando quieras, a mano: ln -s {datos} {enlace}")
            return
        try:
            os.symlink(datos, enlace, target_is_directory=True)
        except OSError as error:
            self.decir(
                f"No se pudo crear el enlace ({error}). En Windows hace falta el "
                "modo de desarrollador; en la VM Ubuntu funciona. A mano: "
                f"ln -s {datos} {enlace}"
            )
            return
        self.decir(f"Listo: {enlace} → {datos}. Abre Obsidian y busca la carpeta Tatewari.")

    def _recapitular(self) -> None:
        if not self.pasos:
            return
        self.decir("")
        self.decir("Las órdenes que corrí, por si las quieres usar a mano:")
        for paso in self.pasos:
            self.decir(f"  tatewari {paso}")


class Salir(Exception):
    """La persona escribió «q»."""


def asistente_de_consola(ejecutar: Callable[[list[str]], int], si_a_todo: bool = False) -> Asistente:
    """El asistente conectado a la configuración y la cosecha reales."""
    from .config import cargar_config
    from .cosecha import Cosecha
    from .protocolo import cargar_protocolo

    def pendientes_de(revision: str, protocolo: Any, config: Any) -> int:
        return Cosecha(revision, protocolo, config).pendientes()

    return Asistente(
        ejecutar=ejecutar,
        cargar_config=cargar_config,
        cargar_protocolo=cargar_protocolo,
        pendientes_de=pendientes_de,
        si_a_todo=si_a_todo,
    )
