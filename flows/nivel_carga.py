"""Nivel de carga en el portal Subcontrataley.

Hay dos familias de flujos:

- FAENA: Cargas Masivas → Subir documentos → plantilla Excel (liquidaciones,
  libro de asistencia, pagos AFP/Isapre/Mutualidades/Cajas). Un archivo
  puede representar una faena o un listado masivo ligado a faena/periodo.
- PERSONA: sección de documentos del trabajador, carga por RUT (los 15
  documentos vigentes: cédula, contrato, EPP, tomas de conocimiento, etc.).

No mezclar navegación: PERSONA no usa `llegar_a_cargar_plantillas` (cmsd_*).
"""

from __future__ import annotations

from enum import Enum


class NivelCarga(str, Enum):
    FAENA = "faena"
    PERSONA = "persona"
