"""Flujos Subcontrataley: tronco + ramas de carga de plantillas."""

from __future__ import annotations

from collections.abc import Callable

from flows.llegar_a_plantillas import (
    hacer_login,
    llegar_a_cargar_plantillas,
    navegar_a_cargar_plantillas,
)


def _flujos() -> dict[str, tuple[str, Callable]]:
    from flows.carga_ingreso_trabajadores import (
        ejecutar as ejecutar_ingreso_trabajadores,
    )
    from flows.carga_libro_asistencia import ejecutar as ejecutar_libro_asistencia
    from flows.carga_liquidaciones import ejecutar as ejecutar_liquidaciones
    from flows.carga_pagos_afp_afc import ejecutar as ejecutar_pagos_afp_afc
    from flows.carga_pagos_cajas_compensacion import (
        ejecutar as ejecutar_pagos_cajas,
    )
    from flows.carga_pagos_isapre_fonasa import (
        ejecutar as ejecutar_pagos_isapre_fonasa,
    )
    from flows.carga_pagos_mutualidades import (
        ejecutar as ejecutar_pagos_mutualidades,
    )
    from flows.descargar_listado_trabajadores import (
        ejecutar as ejecutar_listado_trabajadores,
    )
    from flows.documentos_trabajador import DOCUMENTOS_TRABAJADOR, ejecutar_documento
    from flows.pipeline_ingreso_trabajadores import (
        ejecutar as ejecutar_ingreso_e2e,
    )

    flujos = {
        "liquidaciones": ("Liquidaciones de Sueldo", ejecutar_liquidaciones),
        "libro_asistencia": ("Libro de Asistencia", ejecutar_libro_asistencia),
        "pagos_afp_afc": ("Pagos AFP y AFC", ejecutar_pagos_afp_afc),
        "pagos_isapre_fonasa": ("Pagos Isapre / FONASA", ejecutar_pagos_isapre_fonasa),
        "pagos_mutualidades": ("Pagos Mutualidades", ejecutar_pagos_mutualidades),
        "pagos_cajas_compensacion": (
            "Pagos Cajas de Compensación",
            ejecutar_pagos_cajas,
        ),
        "listado_trabajadores": (
            "Listado trabajadores (finiquitables)",
            ejecutar_listado_trabajadores,
        ),
        "ingreso_trabajadores": (
            "Ingreso trabajadores (subir plantilla)",
            ejecutar_ingreso_trabajadores,
        ),
        "ingreso_trabajadores_e2e": (
            "Ingreso trabajadores (pipeline completo)",
            ejecutar_ingreso_e2e,
        ),
    }
    for cfg in DOCUMENTOS_TRABAJADOR:
        flujos[cfg.clave] = (cfg.nombre_ui, ejecutar_documento(cfg))
    return flujos


class _FlujosProxy(dict):
    """Carga las ramas solo cuando se consultan (evita imports circulares)."""

    _loaded = False

    def _ensure(self) -> None:
        if not self._loaded:
            self.update(_flujos())
            self._loaded = True

    def __getitem__(self, key):
        self._ensure()
        return super().__getitem__(key)

    def keys(self):
        self._ensure()
        return super().keys()

    def items(self):
        self._ensure()
        return super().items()

    def __iter__(self):
        self._ensure()
        return super().__iter__()

    def __contains__(self, key):
        self._ensure()
        return super().__contains__(key)


FLUJOS_CARGA: dict[str, tuple[str, Callable]] = _FlujosProxy()

__all__ = [
    "hacer_login",
    "navegar_a_cargar_plantillas",
    "llegar_a_cargar_plantillas",
    "FLUJOS_CARGA",
]
