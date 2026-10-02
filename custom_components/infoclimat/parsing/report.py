"""Rapport de parsing : ce qui a été trouvé, déduit, ou manqué.

Un scraping qui casse en silence est pire qu'un scraping qui échoue. Ce
rapport rend chaque exécution auditable : quel sélecteur a servi, quelles
colonnes ont été reconnues, quelle ligne a été retenue, quels champs sont
vides. Le coordinateur le journalise en une ligne, et en détail en debug.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .notices import Notice

__all__ = ["ParseReport", "STATUS_OK", "STATUS_EMPTY", "STATUS_ABSENT"]

STATUS_OK = "ok"
STATUS_EMPTY = "vide"
STATUS_ABSENT = "absent"


@dataclass
class ParseReport:
    """Traçabilité d'un cycle de parsing."""

    table_selector: str | None = None
    table_fallback: bool = False
    header_fallback: bool = False
    columns: dict[str, str] = field(default_factory=dict)
    unknown_columns: list[str] = field(default_factory=list)
    rows_total: int = 0
    row_index: int | None = None
    row_time: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    carried: list[str] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        """Consigne un avertissement (dédupliqué)."""
        if message not in self.warnings:
            self.warnings.append(message)

    @property
    def missing(self) -> list[str]:
        """Champs attendus mais absents du relevé."""
        return [name for name, status in self.fields.items() if status != STATUS_OK]

    def summary(self) -> str:
        """Résumé compact, destiné au journal."""
        parts = [
            f"table={self.table_selector or 'introuvable'}",
            f"colonnes={len(self.columns)}",
            f"lignes={self.rows_total}",
            f"relevé={self.row_time or '?'}",
        ]
        if self.missing:
            parts.append("champs absents=" + ",".join(sorted(self.missing)))
        if self.carried:
            parts.append("reportés=" + ",".join(sorted(self.carried)))
        if self.notices:
            parts.append(f"popups={len(self.notices)}")
        if self.warnings:
            parts.append("alertes=" + " | ".join(self.warnings))
        return " ; ".join(parts)

    def details(self) -> str:
        """Rapport multiligne, destiné au journal en mode debug."""
        lines = ["Rapport de parsing Infoclimat", f"  {self.summary()}"]
        if self.columns:
            lines.append("  Colonnes reconnues :")
            lines.extend(f"    {role} ← « {label} »" for role, label in sorted(self.columns.items()))
        if self.unknown_columns:
            lines.append("  Colonnes ignorées : " + ", ".join(self.unknown_columns))
        if self.row_index is not None:
            lines.append(f"  Ligne retenue : index {self.row_index}")
        lines.append(
            "  Champs : "
            + ", ".join(f"{k}={v}" for k, v in sorted(self.fields.items()))
        )
        if self.carried:
            lines.append(
                "  Reportés du relevé précédent : " + ", ".join(sorted(self.carried))
            )
        for notice in self.notices:
            lines.append(f"  Popup : {notice}")
        for warning in self.warnings:
            lines.append(f"  ⚠ {warning}")
        return "\n".join(lines)
