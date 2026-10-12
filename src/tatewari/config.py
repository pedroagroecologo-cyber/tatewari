"""Configuracion de Tatewari: valores por defecto mas un archivo `.env` simple.

No usa dependencias externas: el lector de `.env` esta aqui mismo, son treinta
lineas y evita arrastrar `python-dotenv`.

Precedencia, de menor a mayor:

1. Los valores por defecto de `PREDETERMINADOS`.
2. Lo que diga el archivo `.env`.
3. Las variables de entorno reales del proceso.

Asi, `set TATEWARI_OLLAMA=...` en la consola manda sobre el `.env`, que es lo
que espera quien depura a mano.

Variables reconocidas:

- `TATEWARI_MAILTO`: correo de contacto para las APIs academicas. Unpaywall lo
  **exige**; OpenAlex y Crossref lo usan para meter las peticiones en su cola
  educada (mas rapida y con menos cortes).
- `TATEWARI_OPENALEX_KEY`: clave gratuita de OpenAlex (openalex.org/settings/api).
  Multiplica por diez el presupuesto diario de consultas. Opcional. Viaja en la
  cabecera `Authorization` y nunca en la URL, para que no quede escrita en la
  bitacora de busquedas.
- `TATEWARI_OLLAMA`: direccion del Ollama local. Por defecto
  `http://localhost:11434`.
- `TATEWARI_DATOS`: carpeta de salida de las revisiones. Por defecto
  `./revisiones`.
- `TATEWARI_OBSIDIAN_VAULT`: el Vault de Obsidian donde Knowledge Studio escribe
  las notas. Sin el, las ordenes de `conocimiento` piden `--vault`.
- `TATEWARI_MODELO_EXTRACCION` y `TATEWARI_MODELO_SINTESIS`: modelos de Ollama
  por tarea. Vacios, Tatewari elige el que entra en la tarjeta.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "PREDETERMINADOS",
    "NOMBRE_ARCHIVO_ENV",
    "Config",
    "ErrorConfig",
    "cargar_config",
    "leer_env",
    "buscar_archivo_env",
]

NOMBRE_ARCHIVO_ENV = ".env"
HOST_OPENALEX = "api.openalex.org"

PREDETERMINADOS: dict[str, str] = {
    "TATEWARI_MAILTO": "",
    "TATEWARI_OPENALEX_KEY": "",
    "TATEWARI_OLLAMA": "http://localhost:11434",
    "TATEWARI_DATOS": "./revisiones",
    "TATEWARI_OBSIDIAN_VAULT": "",
    "TATEWARI_MODELO_EXTRACCION": "",
    "TATEWARI_MODELO_SINTESIS": "",
}


class ErrorConfig(Exception):
    """Falta un valor de configuracion imprescindible, o es invalido."""


def leer_env(ruta: Path) -> dict[str, str]:
    """Lee un archivo `.env` y devuelve sus pares clave/valor.

    Formato admitido, a proposito minimo:

    - Lineas vacias y lineas que empiezan por `#` se ignoran.
    - `CLAVE=valor`, con espacios opcionales alrededor del `=`.
    - Se acepta el prefijo `export ` al principio de la linea.
    - Si el valor va entre comillas simples o dobles, se le quitan.

    No se interpretan comentarios al final de la linea: un `#` dentro del valor
    es parte del valor. Si el archivo no existe, devuelve un diccionario vacio.
    """
    if not ruta.is_file():
        return {}

    valores: dict[str, str] = {}
    with open(ruta, encoding="utf-8") as manejador:
        for numero, linea_cruda in enumerate(manejador, start=1):
            linea = linea_cruda.strip()
            if not linea or linea.startswith("#"):
                continue
            if linea.startswith("export "):
                linea = linea[len("export ") :].lstrip()
            if "=" not in linea:
                raise ErrorConfig(
                    f'{ruta}: linea {numero}: se esperaba "CLAVE=valor" y se '
                    f"leyo {linea_cruda.strip()!r}."
                )
            clave, _, valor = linea.partition("=")
            clave = clave.strip()
            if not clave:
                raise ErrorConfig(
                    f"{ruta}: linea {numero}: el nombre de la variable esta vacio."
                )
            valor = valor.strip()
            if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
                valor = valor[1:-1]
            valores[clave] = valor
    return valores


def buscar_archivo_env(inicio: Path | None = None) -> Path | None:
    """Busca un `.env` en `inicio` y en sus carpetas superiores.

    Devuelve la primera coincidencia o `None`. Por defecto arranca en la
    carpeta de trabajo actual.
    """
    actual = (inicio or Path.cwd()).resolve()
    for carpeta in (actual, *actual.parents):
        candidato = carpeta / NOMBRE_ARCHIVO_ENV
        if candidato.is_file():
            return candidato
    return None


@dataclass(frozen=True)
class Config:
    """Configuracion efectiva de una ejecucion de Tatewari."""

    mailto: str
    ollama: str
    datos: Path
    origen_env: Path | None = None
    #: Vault de Obsidian de Knowledge Studio. `None` si no esta configurado.
    vault: Path | None = None
    #: Modelos forzados por tarea. Vacio = eleccion automatica para 4 GB de VRAM.
    modelo_extraccion: str = ""
    modelo_sintesis: str = ""
    #: Clave de OpenAlex. Vacia = cola sin clave, con el presupuesto minimo.
    openalex_key: str = field(default="", repr=False)

    def credenciales_http(self) -> dict[str, str]:
        """Token por servidor, para `ClienteHttp(credenciales=...)`.

        La clave solo se entrega a OpenAlex: Crossref, Unpaywall y Ollama no
        la reciben nunca.
        """
        if not self.openalex_key:
            return {}
        return {HOST_OPENALEX: self.openalex_key}

    @property
    def tiene_mailto(self) -> bool:
        """Hay un correo de contacto configurado (comprobacion de forma, no de existencia)."""
        return bool(self.mailto) and "@" in self.mailto

    def exigir_mailto(self) -> str:
        """Devuelve el correo de contacto o falla con un mensaje accionable.

        Unpaywall rechaza las peticiones sin correo, asi que la cosecha debe
        llamar a este metodo antes de salir a la red.
        """
        if not self.tiene_mailto:
            raise ErrorConfig(
                "Falta un correo de contacto valido en TATEWARI_MAILTO. "
                "Unpaywall lo exige y OpenAlex lo usa para dar respuestas mas "
                "rapidas. Copia .env.example a .env y pon ahi tu correo."
            )
        return self.mailto

    def asegurar_datos(self) -> Path:
        """Crea la carpeta de salida si no existe y devuelve su ruta."""
        self.datos.mkdir(parents=True, exist_ok=True)
        return self.datos

    def resumen(self) -> str:
        """Resumen legible de la configuracion, para la CLI."""
        origen = str(self.origen_env) if self.origen_env else "(sin archivo .env)"
        correo = self.mailto if self.tiene_mailto else "(sin configurar)"
        clave = "con clave" if self.openalex_key else "sin clave"
        return (
            f"Archivo .env : {origen}\n"
            f"Correo       : {correo}\n"
            f"OpenAlex     : {clave}\n"
            f"Ollama       : {self.ollama}\n"
            f"Datos        : {self.datos}\n"
            f"Vault        : {self.vault or '(sin configurar)'}"
        )


def cargar_config(
    ruta_env: Path | None = None,
    entorno: dict[str, str] | None = None,
    base: Path | None = None,
) -> Config:
    """Construye la configuracion efectiva.

    - `ruta_env`: archivo `.env` concreto. Si se omite, se busca hacia arriba
      desde `base` (o desde la carpeta de trabajo).
    - `entorno`: diccionario de variables de entorno. Si se omite, `os.environ`.
      Existe para que las pruebas no toquen el entorno real.
    - `base`: carpeta contra la que se resuelve una `TATEWARI_DATOS` relativa.
      Si se omite, la carpeta de trabajo actual.
    """
    entorno = os.environ if entorno is None else entorno
    base = (base or Path.cwd()).resolve()

    archivo = ruta_env if ruta_env is not None else buscar_archivo_env(base)
    if ruta_env is not None and not ruta_env.is_file():
        raise ErrorConfig(f"No existe el archivo .env indicado: {ruta_env}")

    valores = dict(PREDETERMINADOS)
    if archivo is not None:
        valores.update(leer_env(archivo))
    for clave in PREDETERMINADOS:
        if entorno.get(clave):
            valores[clave] = entorno[clave]

    datos = Path(valores["TATEWARI_DATOS"]).expanduser()
    if not datos.is_absolute():
        datos = base / datos

    vault = None
    if valores["TATEWARI_OBSIDIAN_VAULT"].strip():
        vault = Path(valores["TATEWARI_OBSIDIAN_VAULT"].strip()).expanduser()
        if not vault.is_absolute():
            vault = base / vault
        vault = Path(os.path.normpath(vault))

    return Config(
        mailto=valores["TATEWARI_MAILTO"].strip(),
        openalex_key=valores["TATEWARI_OPENALEX_KEY"].strip(),
        ollama=valores["TATEWARI_OLLAMA"].strip().rstrip("/"),
        datos=Path(os.path.normpath(datos)),
        origen_env=archivo,
        vault=vault,
        modelo_extraccion=valores["TATEWARI_MODELO_EXTRACCION"].strip(),
        modelo_sintesis=valores["TATEWARI_MODELO_SINTESIS"].strip(),
    )
