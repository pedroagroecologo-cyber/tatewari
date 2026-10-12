"""Reportes legibles: qué se procesó, qué salió y qué hay que revisar.

El reporte de «procesar documento» responde, en este orden, a lo que alguien
quiere saber al terminar: qué archivo, cuánto medía, qué se encontró, qué notas
se crearon o se tocaron, qué conviene revisar (duplicados, conflictos, citas sin
verificar) y qué falló. Se imprime en la consola y se guarda en el Vault, en la
carpeta de reportes, enlazado a todas las notas que menciona.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .documento import NR
from .markdown import escribir_frontmatter
from .objetos import ahora
from .validacion import ResultadoValidacion

__all__ = ["ReporteProcesamiento", "reporte_vault"]


@dataclass
class ReporteProcesamiento:
    archivo: str
    tipo: str = NR
    unidades: int = 0
    unidad: str = NR
    fragmentos: int = 0
    trozos: int = 0
    trozos_analizados: int = 0
    modelo: str = NR
    segundos: float = 0.0
    por_tipo: Counter = field(default_factory=Counter)
    nuevas: list[str] = field(default_factory=list)
    actualizadas: list[str] = field(default_factory=list)
    propuestas: list[tuple[str, str]] = field(default_factory=list)
    duplicados: list[tuple[str, list[str]]] = field(default_factory=list)
    conflictos: list[str] = field(default_factory=list)
    referencias: list[str] = field(default_factory=list)
    sin_verificar: int = 0
    insuficientes: int = 0
    nota_fuente: str = NR
    avisos: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    herramientas: list[str] = field(default_factory=list)
    ruta_reporte: Path | None = None

    @property
    def conceptos(self) -> int:
        return sum(self.por_tipo.values())

    def texto(self) -> str:
        """Para la consola."""
        tipos = ", ".join(f"{n} {t}" for t, n in self.por_tipo.most_common()) or "ninguno"
        lineas = [
            f"Archivo procesado   : {self.archivo} ({self.tipo.upper()})",
            f"Extensión           : {self.unidades} {self.unidad}, {self.fragmentos} fragmentos, "
            f"{self.trozos} trozos",
            f"Modelo              : {self.modelo}"
            + (f" · {self.trozos_analizados}/{self.trozos} trozos analizados" if self.trozos else ""),
            f"Conocimiento        : {self.conceptos} objetos ({tipos})",
            f"Notas nuevas        : {len(self.nuevas)}",
            f"Notas actualizadas  : {len(self.actualizadas)}",
            f"Propuestas          : {len(self.propuestas)} (notas que Tatewari no toca)",
            f"Posibles duplicados : {len(self.duplicados)}",
            f"Conflictos          : {len(self.conflictos)}",
            f"Referencias         : {len(self.referencias)}",
            f"Sin verificar       : {self.sin_verificar} afirmaciones sin cita comprobada",
            f"Errores             : {len(self.errores)}",
        ]
        if self.nuevas:
            lineas += ["", "Notas nuevas:"] + [f"  + {n}" for n in self.nuevas]
        if self.actualizadas:
            lineas += ["", "Notas actualizadas:"] + [f"  ~ {n}" for n in self.actualizadas]
        if self.propuestas:
            lineas += ["", "Propuestas en la bandeja (no se tocó la nota):"]
            lineas += [f"  ? {n} — {motivo}" for n, motivo in self.propuestas]
        if self.duplicados:
            lineas += ["", "Posibles duplicados:"]
            lineas += [f"  = {n} ≈ {', '.join(otras)}" for n, otras in self.duplicados]
        if self.conflictos:
            lineas += ["", "Conflictos entre fuentes (se conservan las dos versiones):"]
            lineas += [f"  ! {n}" for n in self.conflictos]
        if self.errores:
            lineas += ["", "Errores:"] + [f"  - {e}" for e in self.errores]
        if self.avisos:
            lineas += ["", f"Avisos ({len(self.avisos)}):"] + [f"  - {a}" for a in self.avisos[:15]]
            if len(self.avisos) > 15:
                lineas.append(f"  … y {len(self.avisos) - 15} más en el reporte del Vault.")
        return "\n".join(lineas)

    def markdown(self) -> str:
        """Para el Vault, con enlaces a cada nota."""
        def lista(elementos, vacio="*Ninguna.*"):
            return "\n".join(elementos) if elementos else vacio

        tipos = "\n".join(f"| {t} | {n} |" for t, n in self.por_tipo.most_common())
        cuerpo = [
            f"# Reporte: {self.archivo}",
            "",
            f"- **Archivo**: {self.archivo} ({self.tipo.upper()})",
            f"- **Nota de fuente**: [[{self.nota_fuente}]]" if self.nota_fuente != NR else "- **Nota de fuente**: NR",
            f"- **Extensión**: {self.unidades} {self.unidad} · {self.fragmentos} fragmentos · {self.trozos} trozos",
            f"- **Modelo**: {self.modelo} · {self.trozos_analizados}/{self.trozos} trozos analizados"
            f" · {self.segundos:.0f} s",
            f"- **Afirmaciones sin cita comprobada**: {self.sin_verificar}",
            f"- **Trozos sin información suficiente**: {self.insuficientes}",
            "",
            "## Conocimiento detectado",
            "",
            "| Tipo | Objetos |\n|---|---|\n" + tipos if tipos else "*No se detectó conocimiento.*",
            "",
            "## Notas nuevas",
            "",
            lista([f"- [[{n}]]" for n in self.nuevas]),
            "",
            "## Notas actualizadas",
            "",
            lista([f"- [[{n}]]" for n in self.actualizadas]),
            "",
            "## Propuestas (Tatewari no tocó estas notas)",
            "",
            lista([f"- [[{n}]] — {m}" for n, m in self.propuestas]),
            "",
            "## Posibles duplicados",
            "",
            lista([f"- [[{n}]] ≈ " + ", ".join(f"[[{o}]]" for o in otras) for n, otras in self.duplicados]),
            "",
            "## Conflictos entre fuentes",
            "",
            lista([f"- [[{n}]]" for n in self.conflictos], "*Ninguno.*"),
            "",
            "## Referencias detectadas",
            "",
            lista([f"- {r}" for r in self.referencias]),
            "",
            "## Errores",
            "",
            lista([f"- {e}" for e in self.errores], "*Ninguno.*"),
            "",
            "## Avisos",
            "",
            lista([f"- {a}" for a in self.avisos], "*Ninguno.*"),
            "",
            "## Herramientas usadas",
            "",
            lista([f"- `{h}`" for h in self.herramientas]),
            "",
        ]
        return (
            escribir_frontmatter({"tipo": "reporte", "tags": ["knowledge-studio", "reporte"], "creado": ahora()})
            + "\n".join(cuerpo)
        )


def reporte_vault(resultado: ResultadoValidacion) -> str:
    """El reporte del estado de todo el Vault, en Markdown."""
    def lista(elementos, vacio="*Ninguno.*"):
        return "\n".join(elementos) if elementos else vacio

    pendientes = [
        f"- [[{destino}]] ← " + ", ".join(f"[[{n}]]" for n in sorted(set(origenes))[:5])
        for destino, origenes in sorted(resultado.pendientes.items())
    ]
    cuerpo = [
        "# Reporte del Vault",
        "",
        "```",
        resultado.resumen(),
        "```",
        "",
        "## Errores",
        "",
        lista([f"- {e}" for e in resultado.errores]),
        "",
        "## Avisos",
        "",
        lista([f"- {a}" for a in resultado.avisos]),
        "",
        "## Conflictos sin resolver",
        "",
        lista([f"- [[{n}]]" for n in resultado.con_conflictos]),
        "",
        "## Editadas a mano (Tatewari ya no las reescribe)",
        "",
        lista([f"- [[{n}]]" for n in resultado.editadas], "*Ninguna.*"),
        "",
        "## Enlaces pendientes",
        "",
        lista(pendientes),
        "",
    ]
    return (
        escribir_frontmatter({"tipo": "reporte", "tags": ["knowledge-studio", "reporte"], "creado": ahora()})
        + "\n".join(cuerpo)
    )
