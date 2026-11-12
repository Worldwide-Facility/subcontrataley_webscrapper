"""Metadato de nivel de documento en Subcontrataley.

Ambos niveles usan la **misma** navegación de Cargas Masivas → plantillas
(`llegar_a_cargar_plantillas` / selectores `liquidaciones.*` / `cmsd_*`).
La diferencia es semántica / tipo de documento en el `<select>`:

- FAENA: liquidaciones, libro, pagos (archivo por faena o listado de faena).
- PERSONA: los 15 docs vigentes del trabajador (1 PDF por RUT en la plantilla).

Solo cambia la opción elegida en `liquidaciones.select_tipo` (texto exacto UI).
"""

from __future__ import annotations

from enum import Enum


class NivelCarga(str, Enum):
    FAENA = "faena"
    PERSONA = "persona"
