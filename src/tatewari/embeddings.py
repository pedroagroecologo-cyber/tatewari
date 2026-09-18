"""Vectores locales para buscar por parecido. Capa **opcional**.

Qué es y qué no es
------------------

Esto convierte cada registro en un vector y permite tres cosas: ordenar por
cercanía a la pregunta de investigación, buscar los parecidos a uno dado, y
encontrar los casi duplicados que la deduplicación por DOI y título no atrapó.

**La similitud es una ayuda de lectura, no un criterio de inclusión.** Ninguna
función de este módulo escribe en `decisiones.json` ni toca una decisión del
cribado, y no va a hacerlo: un número de coseno no es evidencia de que un
artículo cumpla un criterio del protocolo. Sirve para decidir **qué leer
primero** cuando el cribado deja cien dudosos, y ahí se acaba su trabajo.

Es opcional de verdad: si `nomic-embed-text` no está descargado, estas tres
órdenes fallan con un mensaje que dice qué hacer, y **todo lo demás sigue
funcionando igual**. Nada del cribado, la cosecha o el PRISMA depende de este
módulo.

Los dos endpoints
-----------------

Ollama cambió de sitio los embeddings a mitad de camino:

- ``/api/embed`` es el nuevo. Acepta una **lista** en ``input`` y devuelve
  ``embeddings``, así que vectoriza un lote entero de una vez.
- ``/api/embeddings`` es el viejo. Acepta un solo ``prompt`` y devuelve
  ``embedding``, uno por petición.

Se prueba el nuevo y, si responde 404 —la ruta no existe en esa versión—, se usa
el viejo. La ruta que funcionó se recuerda para no repetir la prueba en cada
lote. El orden importa: primero se comprueba que el modelo esté descargado, y así
un 404 solo puede significar «esa ruta no existe» y no «ese modelo no está».

Qué se vectoriza
----------------

Título más resumen. Si no hay resumen, **solo el título**, y el vector queda
marcado como de **baja calidad**: un título son diez palabras y un resumen
doscientas, así que el parecido calculado sobre el título solo es mucho más
grueso. Marcarlo es lo honesto; hacer como si valiera lo mismo sería engañar a
quien lee el orden.

La caché
--------

Vectorizar es lo caro de todo esto, así que los vectores se guardan en
`vectores.json`, dentro de la carpeta de la revisión, indexados por el
identificador estable del registro y por un **hash del texto**. Si el texto no
cambió, el vector no se vuelve a pedir. Si cambió —llegó el resumen que faltaba—
se recalcula **solo ese**.

Dos avisos sobre la caché:

- Si se cambia el modelo de embeddings, la caché entera se descarta. Los vectores
  de dos modelos distintos viven en espacios distintos y **no son comparables**:
  mezclarlos daría un orden con toda la pinta de ser correcto y sin ningún
  sentido.
- Se guarda en JSON, con los valores redondeados a seis decimales. En JSON porque
  el proyecto no arrastra numpy ni un formato binario por esto, y redondeados
  porque a seis decimales el coseno no se mueve ni en 1e-6 y el archivo baja a la
  mitad. Aun así, un millar de registros son unos quince megas: es el precio de
  no meter una dependencia.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from hashlib import sha256
from operator import mul
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .config import Config
from .fuentes import NR
from .http import ErrorHttp, ErrorHttpCliente, ErrorRed
from .modelo import ClienteOllama, ModeloInstalado, OllamaNoResponde
from .texto import texto_buscable

__all__ = [
    "MODELO_EMBED_POR_DEFECTO",
    "NOMBRE_VECTORES",
    "RUTA_EMBED",
    "RUTA_EMBEDDINGS",
    "LOTE_POR_DEFECTO",
    "UMBRAL_CASI_DUPLICADO",
    "DECIMALES",
    "Vector",
    "Almacen",
    "ClienteEmbeddings",
    "Parecido",
    "ParCasiDuplicado",
    "ResultadoVectores",
    "ErrorEmbeddings",
    "ModeloEmbedNoInstalado",
    "EmbeddingsNoDisponibles",
    "coseno",
    "hash_de_texto",
    "texto_de_registro",
    "vectorizar",
    "ordenar_por_parecido",
    "mas_parecidos",
    "casi_duplicados",
]

MODELO_EMBED_POR_DEFECTO = "nomic-embed-text"

NOMBRE_VECTORES = "vectores.json"

RUTA_EMBED = "/api/embed"
RUTA_EMBEDDINGS = "/api/embeddings"

#: Registros por petición al endpoint nuevo. Ni tan pocos que se pierda la
#: ventaja del lote, ni tantos que una petición tarde minutos y no se vea avance.
LOTE_POR_DEFECTO = 16

#: Por encima de esto, dos registros son casi con seguridad el mismo trabajo: el
#: preprint y la versión publicada, o el mismo artículo con el título retocado.
#: Alto a propósito: con 0,90 saldrían pares que solo comparten el tema, y una
#: lista llena de falsos positivos no la revisa nadie.
UMBRAL_CASI_DUPLICADO = 0.97

#: Decimales que se guardan en la caché. Ver la cabecera del módulo.
DECIMALES = 6

#: Cuántos caracteres del hash se guardan. 16 hex son 64 bits: de sobra para
#: distinguir dos textos, y una línea de caché que se puede leer.
LARGO_HASH = 16

#: Lo que dice Ollama cuando el modelo cargado no sabe generar vectores.
_SIN_SOPORTE = "does not support embeddings"


class ErrorEmbeddings(Exception):
    """No se pueden calcular vectores. El mensaje dice qué hacer."""


class ModeloEmbedNoInstalado(ErrorEmbeddings):
    """El modelo de embeddings no está descargado en Ollama."""


class EmbeddingsNoDisponibles(ErrorEmbeddings):
    """Ollama responde pero no devuelve vectores con ese modelo."""


class _RutaInexistente(Exception):
    """Señal interna: esa ruta no existe en esta versión de Ollama.

    No sale de este módulo. Solo sirve para que la primera petición al endpoint
    nuevo pueda decir «prueba con el viejo» sin confundirse con un error de
    verdad.
    """


# ---------------------------------------------------------------------------
# Texto, hash y coseno
# ---------------------------------------------------------------------------


def texto_de_registro(registro: Mapping[str, Any]) -> tuple[str, bool]:
    """El texto que se vectoriza y si el vector sale de baja calidad.

    Devuelve ``(texto, baja_calidad)``. Con resumen, es título más resumen. Sin
    resumen, solo el título, y `baja_calidad` es `True`.
    """
    titulo = registro.get("titulo")
    resumen = registro.get("resumen")
    sin_resumen = resumen is None or str(resumen).strip() in ("", NR)
    if sin_resumen:
        return texto_buscable(titulo), True
    return texto_buscable(titulo, resumen), False


def hash_de_texto(texto: str) -> str:
    """Huella del texto, para saber si hay que recalcular su vector."""
    return sha256(texto.encode("utf-8")).hexdigest()[:LARGO_HASH]


def coseno(uno: Sequence[float], otro: Sequence[float]) -> float:
    """Similitud coseno entre dos vectores. Devuelve 0.0 si alguno es nulo.

    No falla si las dimensiones no coinciden: compara lo que tienen en común y
    ya. Eso no debería pasar —la caché se descarta al cambiar de modelo— pero un
    archivo editado a mano no puede tumbar el programa.
    """
    if not uno or not otro:
        return 0.0
    producto = sum(map(mul, uno, otro))
    norma_uno = math.sqrt(sum(valor * valor for valor in uno))
    norma_otro = math.sqrt(sum(valor * valor for valor in otro))
    if not norma_uno or not norma_otro:
        return 0.0
    return producto / (norma_uno * norma_otro)


def _unitario(valores: Sequence[float]) -> tuple[float, ...]:
    """El vector normalizado a longitud 1, o vacío si es nulo.

    Con los vectores ya normalizados, el coseno es un producto punto y se ahorra
    calcular dos raíces por cada par. Con miles de registros, los pares crecen al
    cuadrado y eso se nota.
    """
    norma = math.sqrt(sum(valor * valor for valor in valores))
    if not norma:
        return ()
    return tuple(valor / norma for valor in valores)


# ---------------------------------------------------------------------------
# Los vectores y su caché
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Vector:
    """El vector de un registro, con lo necesario para saber si sigue valiendo."""

    identificador: str
    hash: str
    valores: tuple[float, ...]
    baja_calidad: bool = False

    @property
    def dimension(self) -> int:
        return len(self.valores)

    def como_json(self) -> dict[str, Any]:
        return {
            "hash": self.hash,
            "baja_calidad": self.baja_calidad,
            "vector": [round(valor, DECIMALES) for valor in self.valores],
        }


@dataclass
class Almacen:
    """La caché de vectores de una revisión, en `vectores.json`."""

    ruta: Path
    modelo: str
    vectores: dict[str, Vector] = field(default_factory=dict)
    #: Si al leer se descartó una caché de otro modelo. La CLI lo cuenta, porque
    #: explica por qué la siguiente corrida tarda tanto.
    descartada: str = ""

    @classmethod
    def leer(cls, ruta: Path | str, modelo: str) -> "Almacen":
        """Lee la caché. Si era de otro modelo, la descarta entera.

        Los vectores de dos modelos distintos no son comparables, así que
        reutilizar los de antes daría un orden sin sentido con toda la pinta de
        estar bien.
        """
        ruta = Path(ruta)
        almacen = cls(ruta=ruta, modelo=modelo)
        if not ruta.is_file():
            return almacen
        try:
            with open(ruta, encoding="utf-8") as manejador:
                datos = json.load(manejador)
        except (json.JSONDecodeError, OSError):
            # Una caché ilegible no es un problema: se recalcula. Es lo único
            # del proyecto que se puede tirar sin perder información.
            almacen.descartada = "la caché anterior no se pudo leer"
            return almacen
        if not isinstance(datos, dict):
            almacen.descartada = "la caché anterior no tenía la forma esperada"
            return almacen

        guardado = str(datos.get("modelo") or "")
        if guardado and guardado != modelo:
            almacen.descartada = (
                f"la caché anterior era de «{guardado}» y ahora se usa "
                f"«{modelo}»; los vectores de dos modelos no son comparables"
            )
            return almacen

        crudos = datos.get("vectores")
        if not isinstance(crudos, dict):
            return almacen
        for identificador, crudo in crudos.items():
            if not isinstance(crudo, dict):
                continue
            valores = crudo.get("vector")
            if not isinstance(valores, list) or not valores:
                continue
            almacen.vectores[str(identificador)] = Vector(
                identificador=str(identificador),
                hash=str(crudo.get("hash") or ""),
                valores=tuple(float(v) for v in valores),
                baja_calidad=bool(crudo.get("baja_calidad")),
            )
        return almacen

    def guardar(self) -> Path:
        """Escribe la caché, ordenada por identificador."""
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        salida = {
            "modelo": self.modelo,
            "dimension": self.dimension,
            "vectores": {
                identificador: self.vectores[identificador].como_json()
                for identificador in sorted(self.vectores)
            },
        }
        with open(self.ruta, "w", encoding="utf-8") as manejador:
            json.dump(salida, manejador, ensure_ascii=False, indent=1)
            manejador.write("\n")
        return self.ruta

    @property
    def dimension(self) -> int:
        for vector in self.vectores.values():
            return vector.dimension
        return 0

    def vigente(self, identificador: str, huella: str) -> Vector | None:
        """El vector guardado de ese registro, si el texto no ha cambiado."""
        vector = self.vectores.get(identificador)
        if vector is None or vector.hash != huella:
            return None
        return vector

    def poner(self, vector: Vector) -> None:
        self.vectores[vector.identificador] = vector


# ---------------------------------------------------------------------------
# El cliente
# ---------------------------------------------------------------------------


def _mensaje_no_instalado(modelo: str, instalados: Iterable[str]) -> str:
    disponibles = ", ".join(sorted(instalados)) or "ninguno"
    return (
        f"El modelo de embeddings «{modelo}» no está descargado en Ollama.\n"
        f"\n"
        f"Descárgalo:  ollama pull {modelo}\n"
        f"\n"
        f"Modelos que sí tienes: {disponibles}\n"
        f"\n"
        f"La búsqueda por parecido es una capa **opcional** de Tatewari: sin ella,\n"
        f"la cosecha, el cribado, el PRISMA y las decisiones funcionan igual. Solo\n"
        f"no podrás usar «ordenar», «similares» ni «casi-duplicados»."
    )


@dataclass
class ClienteEmbeddings:
    """Pide vectores al Ollama de esta máquina.

    `ollama` es el `ClienteOllama` del proyecto: de él salen la dirección, el
    cliente HTTP con sus reintentos y la lista de modelos descargados. Inyectarlo
    es lo que permite que las pruebas corran **sin Ollama y sin modelo**
    (AGENTS.md, regla 6).
    """

    ollama: ClienteOllama
    modelo: str = MODELO_EMBED_POR_DEFECTO
    _ruta: str | None = field(default=None, init=False, repr=False)
    _comprobado: bool = field(default=False, init=False, repr=False)

    @classmethod
    def desde_config(
        cls,
        config: Config,
        modelo: str | None = None,
        cliente: Any | None = None,
    ) -> "ClienteEmbeddings":
        return cls(
            ollama=ClienteOllama.desde_config(config, cliente=cliente),
            modelo=modelo or MODELO_EMBED_POR_DEFECTO,
        )

    @property
    def ruta_usada(self) -> str | None:
        """Qué endpoint acabó funcionando. `None` hasta la primera petición."""
        return self._ruta

    def comprobar(self) -> ModeloInstalado:
        """Comprueba que el modelo de embeddings esté descargado.

        Se llama antes de pedir el primer vector, y por dos razones: para fallar
        en el primer segundo en vez de a mitad de la vectorización, y para que un
        404 posterior solo pueda significar «esa ruta no existe».
        """
        instalados = self.ollama.instalados()
        nombres = {m.nombre for m in instalados}
        bases = {nombre.split(":", 1)[0] for nombre in nombres}
        if self.modelo not in nombres and self.modelo.split(":", 1)[0] not in bases:
            raise ModeloEmbedNoInstalado(
                _mensaje_no_instalado(self.modelo, nombres)
            )
        self._comprobado = True
        for modelo in instalados:
            if modelo.nombre == self.modelo:
                return modelo
        return ModeloInstalado(nombre=self.modelo)

    def vectores(self, textos: Sequence[str]) -> list[tuple[float, ...]]:
        """Los vectores de estos textos, en el mismo orden.

        Usa el endpoint nuevo con el lote entero. Si esa ruta no existe en esta
        versión de Ollama —404—, se pasa al viejo y lo recuerda. La primera
        petición de verdad es la que descubre el endpoint: probarlo aparte
        gastaría una vectorización de más en cada corrida.
        """
        if not textos:
            return []
        if not self._comprobado:
            self.comprobar()

        if self._ruta is None or self._ruta == RUTA_EMBED:
            try:
                valores = self._con_embed(textos)
            except _RutaInexistente:
                # Ollama viejo: la ruta nueva no está. El lote se rehace de uno
                # en uno, que es lo único que admite el endpoint antiguo.
                self._ruta = RUTA_EMBEDDINGS
            else:
                self._ruta = RUTA_EMBED
                return valores

        return [self._con_embeddings(texto) for texto in textos]

    def vector(self, texto: str) -> tuple[float, ...]:
        """El vector de un solo texto. Para la pregunta de `ordenar`."""
        obtenidos = self.vectores([texto])
        if not obtenidos:
            raise EmbeddingsNoDisponibles(
                f"Ollama no devolvió ningún vector para «{self.modelo}»."
            )
        return obtenidos[0]

    # -- Endpoints ---------------------------------------------------------

    def _con_embed(self, textos: Sequence[str]) -> list[tuple[float, ...]]:
        datos = self._pedir(
            RUTA_EMBED,
            {"model": self.modelo, "input": list(textos)},
            # Solo mientras no sepamos qué endpoint hay: una vez elegido, un 404
            # ya no es «esa ruta no existe», es un problema de verdad.
            permitir_404=self._ruta is None,
        )
        crudos = datos.get("embeddings")
        if not isinstance(crudos, list) or len(crudos) != len(textos):
            raise EmbeddingsNoDisponibles(
                f"Ollama devolvió {_cuantos(crudos)} vectores para "
                f"{len(textos)} textos en {RUTA_EMBED}, con el modelo "
                f"«{self.modelo}». Prueba con un lote más pequeño "
                f"(--lote 1) para ver cuál falla."
            )
        return [_a_vector(crudo, self.modelo) for crudo in crudos]

    def _con_embeddings(self, texto: str) -> tuple[float, ...]:
        datos = self._pedir(
            RUTA_EMBEDDINGS, {"model": self.modelo, "prompt": texto}
        )
        return _a_vector(datos.get("embedding"), self.modelo)

    def _pedir(
        self, ruta: str, cuerpo: dict[str, Any], permitir_404: bool = False
    ) -> dict[str, Any]:
        url = f"{self.ollama.direccion}{ruta}"
        try:
            datos = self.ollama.cliente.enviar_json(
                url, cuerpo, tiempo_espera=self.ollama.tiempo_espera_generar
            )
        except ErrorRed as error:
            raise OllamaNoResponde(str(error)) from error
        except ErrorHttpCliente as error:
            if permitir_404 and error.estado == 404:
                raise _RutaInexistente(ruta) from error
            raise self._traducir(error, ruta) from error
        except ErrorHttp as error:
            raise self._traducir(error, ruta) from error
        if not isinstance(datos, dict):
            raise EmbeddingsNoDisponibles(
                f"Ollama devolvió algo que no es un objeto JSON en {ruta}."
            )
        return datos

    def _traducir(self, error: ErrorHttp, ruta: str) -> ErrorEmbeddings:
        """Convierte un fallo HTTP en un mensaje que diga qué hacer."""
        if _SIN_SOPORTE in (error.cuerpo or "").lower():
            return EmbeddingsNoDisponibles(
                f"Ollama cargó «{self.modelo}» pero ese modelo no sabe generar "
                f"vectores.\n"
                f"\n"
                f"Respondió: {error.cuerpo}\n"
                f"\n"
                f"Pasa cuando se le pide un vector a un modelo **generativo**. "
                f"Usa un modelo\n"
                f"de embeddings de verdad:\n"
                f"  ollama pull {MODELO_EMBED_POR_DEFECTO}\n"
                f"y vuelve a lanzar la orden sin --modelo-embed, o con "
                f"--modelo-embed {MODELO_EMBED_POR_DEFECTO}."
            )
        return EmbeddingsNoDisponibles(
            f"Ollama falló al calcular vectores con «{self.modelo}» en {ruta}: "
            f"{error}\n"
            f"\n"
            f"{('Respondió: ' + error.cuerpo) if error.cuerpo else ''}".rstrip()
        )


def _cuantos(crudos: Any) -> str:
    return str(len(crudos)) if isinstance(crudos, list) else "0"


def _a_vector(crudo: Any, modelo: str) -> tuple[float, ...]:
    """Convierte la lista de números de Ollama en un vector, o falla claro."""
    if not isinstance(crudo, list) or not crudo:
        raise EmbeddingsNoDisponibles(
            f"Ollama no devolvió un vector utilizable con «{modelo}»: "
            f"llegó {type(crudo).__name__}."
        )
    try:
        return tuple(float(valor) for valor in crudo)
    except (TypeError, ValueError) as error:
        raise EmbeddingsNoDisponibles(
            f"El vector que devolvió «{modelo}» tiene valores que no son "
            f"números."
        ) from error


# ---------------------------------------------------------------------------
# Vectorizar una revisión
# ---------------------------------------------------------------------------


@dataclass
class ResultadoVectores:
    """Lo que pasó al vectorizar una revisión."""

    modelo: str
    calculados: int = 0
    reutilizados: int = 0
    baja_calidad: int = 0
    dimension: int = 0
    descartada: str = ""

    @property
    def total(self) -> int:
        return self.calculados + self.reutilizados

    def resumen(self) -> str:
        """Texto para la CLI."""
        lineas = [
            f"Modelo de embeddings : {self.modelo}",
            f"Registros vectorizados: {self.total} "
            f"({self.calculados} calculados, {self.reutilizados} de la caché)",
        ]
        if self.dimension:
            lineas.append(f"Dimensión            : {self.dimension}")
        if self.baja_calidad:
            lineas.append(
                f"Vectores de baja calidad: {self.baja_calidad} (sin resumen, "
                f"solo con el título)"
            )
        if self.descartada:
            lineas.append(f"Aviso: {self.descartada}.")
        return "\n".join(lineas)


def vectorizar(
    registros: Iterable[Mapping[str, Any]],
    cliente: ClienteEmbeddings,
    almacen: Almacen,
    lote: int = LOTE_POR_DEFECTO,
    avance: Callable[[int, int, int], None] | None = None,
) -> ResultadoVectores:
    """Deja en `almacen` el vector de cada registro, calculando solo lo que falte.

    `avance` recibe ``(hechos, total, en_este_lote)`` después de cada lote: un
    modelo local tarda, y sin avance parece que el programa se colgó.

    No guarda el almacén en disco; eso lo decide quien llama, después de que todo
    haya ido bien.
    """
    resultado = ResultadoVectores(
        modelo=cliente.modelo, descartada=almacen.descartada
    )
    pendientes: list[tuple[str, str, str, bool]] = []

    for registro in registros:
        identificador = str(registro.get("identificador") or "")
        if not identificador:
            continue
        texto, baja = texto_de_registro(registro)
        if not texto.strip():
            # Sin título y sin resumen no hay nada que vectorizar. No se inventa
            # un vector: el registro simplemente no entra en el parecido.
            continue
        huella = hash_de_texto(texto)
        guardado = almacen.vigente(identificador, huella)
        if guardado is not None:
            resultado.reutilizados += 1
            if guardado.baja_calidad:
                resultado.baja_calidad += 1
            continue
        pendientes.append((identificador, texto, huella, baja))

    total = len(pendientes)
    hechos = 0
    tamano = max(1, lote)

    for inicio in range(0, total, tamano):
        tanda = pendientes[inicio : inicio + tamano]
        valores = cliente.vectores([texto for _, texto, _, _ in tanda])
        for (identificador, _, huella, baja), vector in zip(tanda, valores):
            almacen.poner(
                Vector(
                    identificador=identificador,
                    hash=huella,
                    valores=vector,
                    baja_calidad=baja,
                )
            )
            resultado.calculados += 1
            if baja:
                resultado.baja_calidad += 1
        hechos += len(tanda)
        if avance is not None:
            avance(hechos, total, len(tanda))

    resultado.dimension = almacen.dimension
    return resultado


# ---------------------------------------------------------------------------
# Los tres usos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Parecido:
    """Un registro y su parecido con lo que se preguntó."""

    identificador: str
    similitud: float
    baja_calidad: bool = False
    decision: Any = None

    @property
    def registro(self) -> Mapping[str, Any]:
        return getattr(self.decision, "registro", {}) or {}

    def linea(self) -> str:
        """Una línea para la CLI."""
        marca = "  (solo título)" if self.baja_calidad else ""
        registro = self.registro
        decision = getattr(self.decision, "decision", "NR")
        return (
            f"{self.similitud:.3f}  {self.identificador}  "
            f"{registro.get('anio', 'NR')}  [{decision}]{marca}\n"
            f"        {registro.get('titulo', 'NR')}"
        )


def _unitarios(
    decisiones: Sequence[Any], almacen: Almacen
) -> dict[str, tuple[tuple[float, ...], bool]]:
    """Los vectores normalizados de los registros que tienen vector."""
    unitarios: dict[str, tuple[tuple[float, ...], bool]] = {}
    for decision in decisiones:
        vector = almacen.vectores.get(decision.identificador)
        if vector is None:
            continue
        valores = _unitario(vector.valores)
        if valores:
            unitarios[decision.identificador] = (valores, vector.baja_calidad)
    return unitarios


def ordenar_por_parecido(
    decisiones: Sequence[Any],
    almacen: Almacen,
    vector_pregunta: Sequence[float],
) -> list[Parecido]:
    """Ordena los registros por parecido con la pregunta, de más a menos.

    Sirve para leer primero lo más cercano cuando el cribado deja cien dudosos.
    **No cambia ninguna decisión**: solo dice en qué orden mirarlos.
    """
    pregunta = _unitario(vector_pregunta)
    if not pregunta:
        return []
    unitarios = _unitarios(decisiones, almacen)

    parecidos = [
        Parecido(
            identificador=decision.identificador,
            similitud=sum(map(mul, pregunta, unitarios[decision.identificador][0])),
            baja_calidad=unitarios[decision.identificador][1],
            decision=decision,
        )
        for decision in decisiones
        if decision.identificador in unitarios
    ]
    # A igual similitud, por identificador: dos corridas dan el mismo orden.
    parecidos.sort(key=lambda p: (-p.similitud, p.identificador))
    return parecidos


def mas_parecidos(
    identificador: str,
    decisiones: Sequence[Any],
    almacen: Almacen,
    cuantos: int = 10,
) -> list[Parecido]:
    """Los `cuantos` registros más parecidos a `identificador`, sin contarlo a él.

    Lanza `KeyError` si ese registro no tiene vector: es distinto de «no se
    parece a nada» y quien llama tiene que poder decirlo.
    """
    vector = almacen.vectores.get(identificador)
    if vector is None:
        raise KeyError(identificador)
    unitario = _unitario(vector.valores)
    if not unitario:
        return []

    unitarios = _unitarios(decisiones, almacen)
    parecidos = [
        Parecido(
            identificador=decision.identificador,
            similitud=sum(map(mul, unitario, unitarios[decision.identificador][0])),
            baja_calidad=unitarios[decision.identificador][1],
            decision=decision,
        )
        for decision in decisiones
        if decision.identificador in unitarios
        and decision.identificador != identificador
    ]
    parecidos.sort(key=lambda p: (-p.similitud, p.identificador))
    return parecidos[: max(0, cuantos)]


@dataclass(frozen=True)
class ParCasiDuplicado:
    """Dos registros que se parecen tanto que probablemente son el mismo trabajo."""

    uno: str
    otro: str
    similitud: float
    diagnostico: str
    decision_uno: Any = None
    decision_otro: Any = None
    baja_calidad: bool = False

    def lineas(self) -> list[str]:
        """El par, para la CLI."""
        def titulo(decision: Any) -> str:
            return (getattr(decision, "registro", {}) or {}).get("titulo", "NR")

        def doi(decision: Any) -> str:
            return (getattr(decision, "registro", {}) or {}).get("doi", "NR")

        marca = "  (vector de baja calidad)" if self.baja_calidad else ""
        return [
            f"{self.similitud:.4f}  {self.uno} ↔ {self.otro}   "
            f"{self.diagnostico}{marca}",
            f"        {self.uno}: {titulo(self.decision_uno)}",
            f"              DOI: {doi(self.decision_uno)}",
            f"        {self.otro}: {titulo(self.decision_otro)}",
            f"              DOI: {doi(self.decision_otro)}",
        ]


def _diagnostico(uno: Mapping[str, Any], otro: Mapping[str, Any]) -> str:
    """Por qué la deduplicación no atrapó este par.

    Se dice en vez de suponerlo: quien revisa el par necesita saber si es un
    preprint con su propio DOI o un título retocado.
    """
    doi_uno = str(uno.get("doi") or NR)
    doi_otro = str(otro.get("doi") or NR)
    sin_uno = doi_uno == NR
    sin_otro = doi_otro == NR

    if sin_uno and sin_otro:
        return "ninguno trae DOI; se agruparon por título y los títulos difieren"
    if sin_uno or sin_otro:
        return "uno de los dos no trae DOI, así que no había con qué compararlos"
    return "DOI distintos: puede ser el preprint y la versión publicada"


def casi_duplicados(
    decisiones: Sequence[Any],
    almacen: Almacen,
    umbral: float = UMBRAL_CASI_DUPLICADO,
) -> list[ParCasiDuplicado]:
    """Pares que la deduplicación por DOI y título **no** atrapó.

    Todos los registros que llegan aquí sobrevivieron a la deduplicación, así que
    cada uno tiene una clave distinta: DOI distinto, o título distinto sin DOI.
    Por eso el parecido de los vectores es lo único que queda para encontrar el
    preprint y su versión publicada.

    **Se reportan, no se fusionan.** Fusionar dos registros es decidir que son el
    mismo trabajo, y eso lo decide una persona mirando los dos: un umbral de 0,97
    también junta dos estudios del mismo grupo sobre el mismo humedal, que son
    artículos distintos y cuentan por separado.
    """
    unitarios = _unitarios(decisiones, almacen)
    por_identificador = {d.identificador: d for d in decisiones}
    ordenados = [d.identificador for d in decisiones if d.identificador in unitarios]

    pares: list[ParCasiDuplicado] = []
    for indice, uno in enumerate(ordenados):
        vector_uno, baja_uno = unitarios[uno]
        for otro in ordenados[indice + 1 :]:
            vector_otro, baja_otro = unitarios[otro]
            similitud = sum(map(mul, vector_uno, vector_otro))
            if similitud < umbral:
                continue
            decision_uno = por_identificador[uno]
            decision_otro = por_identificador[otro]
            pares.append(
                ParCasiDuplicado(
                    uno=uno,
                    otro=otro,
                    similitud=similitud,
                    diagnostico=_diagnostico(
                        getattr(decision_uno, "registro", {}) or {},
                        getattr(decision_otro, "registro", {}) or {},
                    ),
                    decision_uno=decision_uno,
                    decision_otro=decision_otro,
                    baja_calidad=baja_uno or baja_otro,
                )
            )

    pares.sort(key=lambda p: (-p.similitud, p.uno, p.otro))
    return pares
