"""Enrutador de modelos: qué modelo local hace cada tarea.

Knowledge Studio tiene dos clases de tarea de lenguaje:

``extraccion``
    Leer un trozo y devolver objetos en JSON. Es mecánica y se repite por cada
    trozo del documento: conviene un modelo pequeño y rápido.
``sintesis``
    Trabajo más largo y de más juicio, como los borradores de divulgación de
    ZEA MAYZ. Aguanta un modelo más grande si lo hay y si la tarjeta lo soporta.

Quién decide el modelo, de más a menos prioridad:

1. La línea de órdenes: ``--modelo-extraccion`` y ``--modelo-sintesis``.
2. El entorno o el ``.env``: ``TATEWARI_MODELO_EXTRACCION`` y
   ``TATEWARI_MODELO_SINTESIS``.
3. La elección automática que Tatewari ya tenía (`modelo.elegir_modelo`): el
   mejor modelo general que entra en 4 GB de VRAM.

La síntesis automática usa **el mismo** modelo que la extracción. No se sube
sola a un 8B aunque esté instalado: en una tarjeta de 4 GB se desborda a la RAM
y tarda minutos por respuesta. Para usar ``qwen3:8b`` o ``qwen3:14b`` en la
síntesis hay que pedirlo con ``TATEWARI_MODELO_SINTESIS``, sabiendo lo que cuesta.

Ningún nombre de modelo está escrito en el código: todo sale de lo que hay
instalado en Ollama o de la configuración.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..config import Config
from ..modelo import ClienteOllama

__all__ = ["TAREAS", "CONTEXTO", "Enrutador"]

#: Tarea -> variable de entorno que la configura.
TAREAS = {
    "extraccion": "TATEWARI_MODELO_EXTRACCION",
    "sintesis": "TATEWARI_MODELO_SINTESIS",
}

#: Ventana de contexto por tarea. La extracción lee trozos pequeños; la síntesis
#: recibe varios conceptos aprobados y devuelve un guion entero. Un 4B cuantizado
#: con 8192 tokens de contexto sigue entrando en 4 GB de VRAM.
CONTEXTO = {"extraccion": 4096, "sintesis": 8192}


@dataclass
class Enrutador:
    """Da un `ClienteOllama` por tarea, creándolo la primera vez que se pide."""

    direccion: str
    forzados: dict[str, str | None] = field(default_factory=dict)
    cliente_http: Any | None = None
    _clientes: dict[str, ClienteOllama] = field(default_factory=dict, repr=False)

    @classmethod
    def desde_config(
        cls,
        config: Config,
        extraccion: str | None = None,
        sintesis: str | None = None,
        cliente_http: Any | None = None,
    ) -> "Enrutador":
        return cls(
            direccion=config.ollama,
            forzados={
                "extraccion": extraccion or config.modelo_extraccion or None,
                "sintesis": sintesis or config.modelo_sintesis or None,
            },
            cliente_http=cliente_http,
        )

    @classmethod
    def con_clientes(cls, clientes: Mapping[str, ClienteOllama]) -> "Enrutador":
        """Un enrutador con clientes ya hechos. Es lo que usan las pruebas."""
        primero = next(iter(clientes.values()))
        enrutador = cls(direccion=primero.direccion)
        enrutador._clientes.update(clientes)
        return enrutador

    def cliente(self, tarea: str) -> ClienteOllama:
        if tarea not in TAREAS:
            raise ValueError(f"Tarea desconocida: {tarea}")
        if tarea in self._clientes:
            return self._clientes[tarea]
        forzado = self.forzados.get(tarea)
        if tarea == "sintesis" and not forzado:
            # Sin configuración, la síntesis usa el mismo modelo que la extracción,
            # pero con más contexto: un guion en JSON no cabe en 4096 tokens.
            forzado = self.forzados.get("extraccion")
        cliente = ClienteOllama(
            direccion=self.direccion,
            modelo=forzado,
            cliente=self.cliente_http,
            num_ctx=CONTEXTO[tarea],
        )
        self._clientes[tarea] = cliente
        return cliente

    def modelo(self, tarea: str) -> str:
        """El nombre del modelo de esa tarea. Pregunta a Ollama si hace falta."""
        return self.cliente(tarea).elegir()

    def describir(self) -> str:
        """Texto para la CLI: qué modelo hace qué y por qué."""
        lineas = []
        for tarea, variable in TAREAS.items():
            nombre = self.modelo(tarea)
            if self.forzados.get(tarea):
                origen = "configurado"
            elif tarea == "sintesis":
                origen = "el mismo que la extracción; se cambia con " + variable
            else:
                origen = "elegido para 4 GB de VRAM; se cambia con " + variable
            lineas.append(f"  {tarea:<10} : {nombre}  ({origen})")
        return "\n".join(lineas)
