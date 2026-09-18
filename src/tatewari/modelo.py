"""Cliente de Ollama: el único modelo de lenguaje de Tatewari, y es local.

El modelo corre en la máquina de quien usa el programa, en la dirección que diga
`TATEWARI_OLLAMA` (por defecto `http://localhost:11434`). Está **prohibido**
llamar a un modelo en la nube desde aquí o desde cualquier otro módulo: ni
OpenAI, ni Anthropic, ni Gemini, ni Cohere, ni Mistral alojado (AGENTS.md,
regla 1). Este archivo solo habla con `localhost`, y el corpus no sale de la
máquina.

Elegir el modelo con 4 GB de VRAM
---------------------------------

La máquina de referencia tiene **4 GB de VRAM**, y eso decide todo. Un modelo de
8B cuantizado a 4 bits pesa unos 4,7 GB: no entra, así que Ollama lo reparte
entre la tarjeta y la RAM del sistema, y la generación pasa de segundos a
minutos. Un 3B a 4 bits pesa unos 2 GB, entra entero y deja sitio para el
contexto.

Por eso `elegir_modelo` ordena así, de mejor a peor:

1. De 3B a 4B **cuantizado a 4 bits**. El punto dulce: entra en la tarjeta y
   entiende una instrucción.
2. De 3B a 4B sin cuantizar a 4 bits.
3. De 1B a 3B cuantizado, y luego sin cuantizar. Entran de sobra, pero razonan
   peor.
4. Menos de 1B. Entran en cualquier sitio y se equivocan demasiado.
5. Más de 4B y menos de 8B cuantizado, y luego sin cuantizar. Van justos.
6. Tamaño desconocido: no se puede prometer nada, así que va después de todo lo
   que sí se conoce.
7. **8B o más**: se desborda a RAM y se arrastra. Último.

A igualdad de grupo, gana el modelo **general** sobre el especializado en código,
luego el que dice ser instruido (*instruct*, *it*, *chat*) y después el **más
pequeño**: con 4 GB, lo que sobra de VRAM es contexto.

Los modelos de *embeddings* se descartan del todo: no generan texto, y pedirles
una decisión devuelve un error o un disparate. Los de código **no** se descartan
—generan texto y responden— pero se van al final de su grupo: aquí hay que leer
un resumen científico en español, no escribir una función. Sin esa regla, una
máquina con `qwen2.5-coder:3b` y `qwen3:4b` instalados elegía el de código por ser
0,9 mil millones de parámetros más pequeño, que es exactamente la decisión
equivocada.

Nada de esto se adivina a ciegas: sale de `details.parameter_size` y
`details.quantization_level`, que es lo que `/api/tags` informa de cada modelo
descargado. Si Ollama no lo dice, el tamaño se intenta leer de la etiqueta del
nombre (`llama3.2:3b`), y si tampoco está, queda en desconocido, nunca en un
número inventado (AGENTS.md, regla 2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .config import Config
from .http import ClienteHttp, ErrorHttp, ErrorRed

__all__ = [
    "DIRECCION_POR_DEFECTO",
    "RUTA_TAGS",
    "RUTA_GENERAR",
    "NUM_CTX",
    "TEMPERATURA",
    "TIEMPO_ESPERA_TAGS",
    "TIEMPO_ESPERA_GENERAR",
    "MODELO_SUGERIDO",
    "ModeloInstalado",
    "Generacion",
    "ClienteOllama",
    "ErrorOllama",
    "OllamaNoResponde",
    "SinModelosUtiles",
    "ModeloNoInstalado",
    "leer_modelos",
    "elegir_modelo",
    "orden_de_preferencia",
]

DIRECCION_POR_DEFECTO = "http://localhost:11434"
RUTA_TAGS = "/api/tags"
RUTA_GENERAR = "/api/generate"

#: Ventana de contexto, **explícita**. Si no se manda, Ollama usa la que traiga
#: el Modelfile del modelo, que cambia de un modelo a otro: el mismo prompt
#: daría respuestas distintas según lo que hubiera descargado la máquina, y el
#: cribado dejaría de ser reproducible.
NUM_CTX = 4096

#: Temperatura 0: se le pide una decisión, no una redacción. Con temperatura
#: alta, dos ejecuciones sobre el mismo registro pueden decidir distinto, y eso
#: en una revisión sistemática no vale.
TEMPERATURA = 0.0

#: Listar los modelos descargados es instantáneo. Si en diez segundos no
#: contesta, Ollama no está levantado y hay que decirlo ya, no dentro de cinco
#: minutos.
TIEMPO_ESPERA_TAGS = 10.0

#: Generar es otra cosa: un modelo local en una tarjeta de 4 GB tarda segundos
#: por registro, y el primero tarda más porque tiene que cargar el modelo en
#: memoria. Cinco minutos de margen por petición.
TIEMPO_ESPERA_GENERAR = 300.0

#: Un intento y un reintento. Más no: si Ollama devuelve un 500 dos veces, el
#: problema no se arregla esperando, y cada intento cuesta minutos.
INTENTOS = 2

#: El que se sugiere en los mensajes de error. Es una sugerencia concreta y
#: accionable, no una promesa: entra en 4 GB de VRAM.
MODELO_SUGERIDO = "llama3.2:3b"

#: Marcas de que un modelo está afinado para obedecer instrucciones.
_MARCAS_INSTRUIDO = ("instruct", "-it", ":it", "chat", "-ins")

#: Marcas de un modelo de embeddings, que no genera texto.
_MARCAS_EMBEDDING = ("embed", "embedding", "bge-", "gte-", "e5-")

#: Marcas de un modelo especializado en código. No se descarta —genera texto y
#: puede responder— pero se queda por detrás de un modelo general del mismo
#: tamaño: aquí hay que leer un resumen científico en español, no escribir una
#: función. En la máquina de referencia esto es lo que separa a `qwen2.5-coder:3b`
#: de `qwen3:4b`, y la diferencia se nota en las respuestas.
_MARCAS_CODIGO = (
    "coder",
    "codellama",
    "codegemma",
    "codestral",
    "starcoder",
    "sqlcoder",
    "code-",
    "-code",
)

#: «3.2B», «7b», «1.5 B»… tal como los escribe `details.parameter_size`.
_TAMANO = re.compile(r"(\d+(?:[.,]\d+)?)\s*b\b", re.IGNORECASE)

#: «q4», «Q4_K_M», «q4_0»…
_CUATRO_BITS = re.compile(r"q4", re.IGNORECASE)


class ErrorOllama(Exception):
    """No se puede usar el modelo local. El mensaje dice qué hacer."""


class OllamaNoResponde(ErrorOllama):
    """No hay nadie escuchando en la dirección de Ollama."""


class SinModelosUtiles(ErrorOllama):
    """Ollama responde, pero no tiene ningún modelo que pueda generar texto."""


class ModeloNoInstalado(ErrorOllama):
    """Se forzó con `--modelo` un modelo que no está descargado."""


def _mensaje_no_responde(direccion: str, detalle: str = "") -> str:
    """El error más probable de todos, así que se explica entero."""
    cola = f"\n\nDetalle técnico: {detalle}" if detalle else ""
    return (
        f"No se pudo hablar con Ollama en {direccion}.\n"
        f"\n"
        f"Qué hacer, por orden:\n"
        f"  1. Arranca el servidor, en otra consola:  ollama serve\n"
        f"  2. Descarga un modelo pequeño:            ollama pull {MODELO_SUGERIDO}\n"
        f"  3. Comprueba que responde:                ollama list\n"
        f"  4. Vuelve a lanzar esta orden.\n"
        f"\n"
        f"Si Ollama escucha en otra dirección, ponla en TATEWARI_OLLAMA dentro de\n"
        f"tu archivo .env.\n"
        f"\n"
        f"Tatewari no tiene ningún modelo de repuesto en la nube, y no lo va a\n"
        f"tener: el único modelo es el de esta máquina (AGENTS.md, regla 1)."
        f"{cola}"
    )


def _numero(texto: Any) -> float | None:
    """Lee «3.2B» o «1,5 b» y devuelve 3.2 o 1.5. Devuelve `None` si no hay nada."""
    if texto is None:
        return None
    encontrado = _TAMANO.search(str(texto))
    if encontrado is None:
        return None
    try:
        return float(encontrado.group(1).replace(",", "."))
    except ValueError:
        return None


@dataclass(frozen=True)
class ModeloInstalado:
    """Un modelo descargado en Ollama, con lo que hace falta para elegirlo.

    `tamano` son miles de millones de parámetros, y puede ser `None`: un tamaño
    desconocido se deja desconocido y pesa en la elección, pero no se inventa.
    """

    nombre: str
    tamano: float | None = None
    cuantizacion: str = "NR"
    familia: str = "NR"
    bytes_en_disco: int | None = None

    @property
    def es_embedding(self) -> bool:
        """¿Es un modelo de embeddings? Entonces no sirve para decidir."""
        minusculas = self.nombre.lower()
        return any(marca in minusculas for marca in _MARCAS_EMBEDDING)

    @property
    def es_instruido(self) -> bool:
        """¿Dice el nombre que está afinado para obedecer instrucciones?

        Es una pista, no una certeza: muchos modelos instruidos no lo llevan en
        el nombre (`llama3.2:3b` lo es). Por eso solo desempata, nunca descarta.
        """
        minusculas = self.nombre.lower()
        return any(marca in minusculas for marca in _MARCAS_INSTRUIDO)

    @property
    def es_de_codigo(self) -> bool:
        """¿Está especializado en código?

        No lo descalifica —genera texto— pero lo manda al final de su grupo: lo
        que hay que leer aquí es un resumen científico en español.
        """
        minusculas = self.nombre.lower()
        return any(marca in minusculas for marca in _MARCAS_CODIGO)

    @property
    def es_cuatro_bits(self) -> bool:
        """¿Cuantizado a 4 bits? Es lo que hace que un 3B entre en 4 GB."""
        return bool(
            _CUATRO_BITS.search(self.cuantizacion)
            or _CUATRO_BITS.search(self.nombre)
        )

    @property
    def gigabytes(self) -> float | None:
        if self.bytes_en_disco is None:
            return None
        return self.bytes_en_disco / 1_000_000_000

    def resumen(self) -> str:
        """Una línea para la CLI."""
        tamano = f"{self.tamano:g}B" if self.tamano is not None else "tamaño NR"
        peso = f", {self.gigabytes:.1f} GB" if self.gigabytes is not None else ""
        return f"{self.nombre} ({tamano}, {self.cuantizacion}{peso})"


def leer_modelos(datos: Any) -> tuple[ModeloInstalado, ...]:
    """Convierte la respuesta de `/api/tags` en objetos `ModeloInstalado`.

    Tolera que falten campos: Ollama cambia de versión y lo que no venga se
    queda en `"NR"` o en `None`, nunca en un valor inventado.
    """
    if not isinstance(datos, dict):
        return ()
    crudos = datos.get("models")
    if not isinstance(crudos, list):
        return ()

    modelos: list[ModeloInstalado] = []
    for crudo in crudos:
        if not isinstance(crudo, dict):
            continue
        nombre = str(crudo.get("name") or crudo.get("model") or "").strip()
        if not nombre:
            continue
        detalles = crudo.get("details")
        detalles = detalles if isinstance(detalles, dict) else {}

        # El tamaño de `details` es el bueno. Si no está, se intenta leer de la
        # etiqueta del nombre («llama3.2:3b» -> 3), nunca del nombre entero:
        # «llama3.2» daría 3.2 por la versión, que no es el tamaño.
        tamano = _numero(detalles.get("parameter_size"))
        if tamano is None and ":" in nombre:
            tamano = _numero(nombre.split(":", 1)[1])

        modelos.append(
            ModeloInstalado(
                nombre=nombre,
                tamano=tamano,
                cuantizacion=str(detalles.get("quantization_level") or "NR"),
                familia=str(detalles.get("family") or "NR"),
                bytes_en_disco=(
                    crudo.get("size") if isinstance(crudo.get("size"), int) else None
                ),
            )
        )
    return tuple(modelos)


#: Grupos de preferencia, de mejor a peor. El número no significa nada por sí
#: mismo; lo único que importa es el orden. Ver la cabecera del módulo.
GRUPO_3B_Q4 = 0
GRUPO_3B = 1
GRUPO_PEQUENO_Q4 = 2
GRUPO_PEQUENO = 3
GRUPO_DIMINUTO = 4
GRUPO_MEDIANO_Q4 = 5
GRUPO_MEDIANO = 6
GRUPO_DESCONOCIDO = 7
GRUPO_DESBORDA = 8


def _grupo(modelo: ModeloInstalado) -> int:
    """En qué grupo de preferencia cae. Menor es mejor. Ver la cabecera."""
    tamano = modelo.tamano
    cuatro = modelo.es_cuatro_bits

    if tamano is None:
        return GRUPO_DESCONOCIDO
    if 3.0 <= tamano <= 4.0:
        return GRUPO_3B_Q4 if cuatro else GRUPO_3B
    if 1.0 <= tamano < 3.0:
        return GRUPO_PEQUENO_Q4 if cuatro else GRUPO_PEQUENO
    if tamano < 1.0:
        return GRUPO_DIMINUTO
    if tamano < 8.0:
        return GRUPO_MEDIANO_Q4 if cuatro else GRUPO_MEDIANO
    return GRUPO_DESBORDA


def orden_de_preferencia(
    modelo: ModeloInstalado,
) -> tuple[int, int, int, float, str]:
    """Clave de ordenación: el primero de la lista ordenada es el elegido.

    Por orden: el grupo de tamaño; el modelo general antes que el de código; el
    que dice ser instruido antes que el que no lo dice; el **más pequeño** —lo
    que sobra de VRAM es contexto—; y por último el nombre.

    El nombre desempata para que la elección sea **determinista**: dos máquinas
    con los mismos modelos eligen el mismo, y no el que Ollama devolviera
    primero. Ese último criterio es arbitrario a propósito: cuando dos modelos
    empatan en todo lo que se puede medir, lo que hace falta es que la elección
    no cambie sola entre ejecuciones.
    """
    return (
        _grupo(modelo),
        1 if modelo.es_de_codigo else 0,
        0 if modelo.es_instruido else 1,
        modelo.tamano if modelo.tamano is not None else float("inf"),
        modelo.nombre,
    )


def elegir_modelo(modelos: Iterable[ModeloInstalado]) -> ModeloInstalado:
    """Elige el modelo más apropiado para 4 GB de VRAM.

    Lanza `SinModelosUtiles` si no hay ninguno que genere texto.
    """
    utiles = [m for m in modelos if not m.es_embedding]
    if not utiles:
        descartados = [m.nombre for m in modelos]
        if descartados:
            raise SinModelosUtiles(
                f"Ollama solo tiene modelos de embeddings descargados "
                f"({', '.join(sorted(descartados))}), y esos no generan texto: "
                f"no pueden decidir sobre un registro.\n"
                f"\n"
                f"Descarga uno que sí genere:  ollama pull {MODELO_SUGERIDO}"
            )
        raise SinModelosUtiles(
            f"Ollama responde, pero no tiene ningún modelo descargado.\n"
            f"\n"
            f"Descarga uno pequeño, que entra en 4 GB de VRAM:\n"
            f"  ollama pull {MODELO_SUGERIDO}"
        )
    return min(utiles, key=orden_de_preferencia)


@dataclass(frozen=True)
class Generacion:
    """Lo que devolvió el modelo, con lo que hace falta para el rastro."""

    texto: str
    modelo: str
    #: Segundos que tardó. Ollama lo informa en nanosegundos; aquí ya está
    #: convertido. Es `None` si no lo informó.
    duracion: float | None = None
    tokens: int | None = None


@dataclass
class ClienteOllama:
    """Habla con el Ollama de esta máquina.

    `cliente` es el `ClienteHttp` del proyecto, inyectable para que las pruebas
    corran **sin Ollama instalado y sin red** (AGENTS.md, regla 6).

    `modelo` fuerza uno concreto, que es lo que hace `--modelo`. Si se deja en
    `None`, se elige automáticamente la primera vez que hace falta y se recuerda:
    así una revisión entera la decide **un solo** modelo, y no uno distinto por
    registro según lo que Ollama tuviera cargado.
    """

    direccion: str = DIRECCION_POR_DEFECTO
    modelo: str | None = None
    cliente: Any | None = None
    num_ctx: int = NUM_CTX
    temperatura: float = TEMPERATURA
    #: Si se le deja «pensar» en voz alta. Va en `False` a propósito: para una
    #: decisión de cribado no hace falta un presupuesto de razonamiento, tarda
    #: más, y un modelo de razonamiento con esto en `True` manda la respuesta al
    #: campo `thinking` y deja `response` **vacío**. Medido con `qwen3:4b`.
    pensar: bool = False
    tiempo_espera_generar: float = TIEMPO_ESPERA_GENERAR
    tiempo_espera_tags: float = TIEMPO_ESPERA_TAGS
    _elegido: str | None = field(default=None, init=False, repr=False)
    _validado: bool = field(default=False, init=False, repr=False)
    _instalados: tuple[ModeloInstalado, ...] | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.direccion = (self.direccion or DIRECCION_POR_DEFECTO).rstrip("/")
        if self.cliente is None:
            self.cliente = ClienteHttp(
                tiempo_espera=self.tiempo_espera_generar, intentos=INTENTOS
            )
        if self.modelo:
            self._elegido = self.modelo

    @classmethod
    def desde_config(
        cls, config: Config, modelo: str | None = None, cliente: Any | None = None
    ) -> "ClienteOllama":
        """Cliente apuntando a donde diga `TATEWARI_OLLAMA`."""
        return cls(
            direccion=config.ollama or DIRECCION_POR_DEFECTO,
            modelo=modelo,
            cliente=cliente,
        )

    # -- Modelos -----------------------------------------------------------

    @property
    def url_tags(self) -> str:
        return f"{self.direccion}{RUTA_TAGS}"

    @property
    def url_generar(self) -> str:
        return f"{self.direccion}{RUTA_GENERAR}"

    def instalados(self) -> tuple[ModeloInstalado, ...]:
        """Los modelos descargados, preguntando a `/api/tags` una sola vez."""
        if self._instalados is not None:
            return self._instalados
        try:
            datos = self.cliente.obtener_json(
                self.url_tags, tiempo_espera=self.tiempo_espera_tags
            )
        except ErrorRed as error:
            raise OllamaNoResponde(
                _mensaje_no_responde(self.direccion, str(error))
            ) from error
        except ErrorHttp as error:
            raise OllamaNoResponde(
                _mensaje_no_responde(self.direccion, str(error))
            ) from error
        self._instalados = leer_modelos(datos)
        return self._instalados

    def elegir(self) -> str:
        """El nombre del modelo que va a decidir. Se calcula una vez y se guarda.

        Con `--modelo` se comprueba que esté descargado: mejor plantarse ahora
        que después de veinte minutos de cribado con un nombre mal escrito.
        """
        if self._elegido is None:
            self._elegido = elegir_modelo(self.instalados()).nombre
        elif not self._validado:
            self._exigir_instalado(self._elegido)
        self._validado = True
        return self._elegido

    def _exigir_instalado(self, nombre: str) -> None:
        instalados = {m.nombre for m in self.instalados()}
        if nombre in instalados:
            return
        # Ollama admite «llama3.2» para «llama3.2:latest», así que un nombre
        # **sin etiqueta** vale si coincide con el nombre base de alguno. Con
        # etiqueta, en cambio, tiene que coincidir exactamente: «llama3.2:3b-xyz»
        # no es «llama3.2:3b», y darlo por bueno sería descubrir el error a mitad
        # del cribado, cuando Ollama lo rechace.
        if ":" not in nombre:
            bases = {m.nombre.split(":", 1)[0] for m in self.instalados()}
            if nombre in bases:
                return
        disponibles = ", ".join(sorted(instalados)) or "ninguno"
        raise ModeloNoInstalado(
            f"El modelo «{nombre}» no está descargado en Ollama.\n"
            f"\n"
            f"Descárgalo:        ollama pull {nombre}\n"
            f"O usa uno de los que ya tienes: {disponibles}\n"
            f"O quita --modelo y deja que Tatewari elija el que mejor entre en "
            f"esta tarjeta."
        )

    def comprobar(self) -> ModeloInstalado:
        """Comprueba que Ollama responde y devuelve el modelo que se usaría.

        Es lo que conviene llamar **antes** de empezar un cribado largo: si algo
        falla, falla en el primer segundo y con un mensaje que dice qué hacer.
        """
        nombre = self.elegir()
        for modelo in self.instalados():
            if modelo.nombre == nombre:
                return modelo
        return ModeloInstalado(nombre=nombre)

    # -- Generación --------------------------------------------------------

    def generar(self, prompt: str, formato_json: bool = False) -> Generacion:
        """Pide una generación con temperatura 0 y `num_ctx` explícito.

        Con `formato_json` se le pide a Ollama que fuerce una respuesta JSON
        válida. Ayuda, pero no basta: un modelo pequeño puede devolver un JSON
        impecable con las claves equivocadas, así que quien llama sigue teniendo
        que interpretar la respuesta con tolerancia.
        """
        nombre = self.elegir()
        cuerpo: dict[str, Any] = {
            "model": nombre,
            "prompt": prompt,
            "stream": False,
            "think": self.pensar,
            "options": {
                "temperature": self.temperatura,
                "num_ctx": self.num_ctx,
            },
        }
        if formato_json:
            cuerpo["format"] = "json"

        try:
            datos = self.cliente.enviar_json(
                self.url_generar, cuerpo, tiempo_espera=self.tiempo_espera_generar
            )
        except ErrorRed as error:
            raise OllamaNoResponde(
                _mensaje_no_responde(self.direccion, str(error))
            ) from error
        except ErrorHttp as error:
            raise ErrorOllama(
                f"Ollama falló al generar con «{nombre}»: {error}\n"
                f"\n"
                f"Si el modelo no entra en la tarjeta, prueba con uno más "
                f"pequeño:  ollama pull {MODELO_SUGERIDO}"
            ) from error

        if not isinstance(datos, dict):
            raise ErrorOllama(
                f"Ollama devolvió algo que no es un objeto JSON al generar con "
                f"«{nombre}»."
            )

        nanosegundos = datos.get("total_duration")
        # Red de seguridad para los modelos de razonamiento. Con `think: False`
        # la respuesta viene donde debe, pero si una versión de Ollama ignora ese
        # campo, el modelo «piensa» y deja `response` vacío con todo el contenido
        # en `thinking`. Antes de darlo por perdido, se mira ahí.
        texto = str(datos.get("response") or "")
        if not texto.strip():
            texto = str(datos.get("thinking") or "")

        return Generacion(
            texto=texto,
            modelo=str(datos.get("model") or nombre),
            duracion=(
                nanosegundos / 1_000_000_000
                if isinstance(nanosegundos, (int, float))
                else None
            ),
            tokens=(
                datos.get("eval_count")
                if isinstance(datos.get("eval_count"), int)
                else None
            ),
        )

    def resumen(self) -> str:
        """Texto para la CLI: dónde está Ollama y con qué va a decidir."""
        modelo = self.comprobar()
        instalados: Sequence[ModeloInstalado] = self.instalados()
        lineas = [
            f"Ollama   : {self.direccion}",
            f"Modelo   : {modelo.resumen()}",
            f"Contexto : {self.num_ctx} tokens, temperatura {self.temperatura:g}",
        ]
        if len(instalados) > 1:
            otros = ", ".join(
                m.nombre for m in sorted(instalados, key=orden_de_preferencia)
                if m.nombre != modelo.nombre
            )
            lineas.append(f"Otros    : {otros}")
        return "\n".join(lineas)
