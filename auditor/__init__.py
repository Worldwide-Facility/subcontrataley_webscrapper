"""Auditor Subcontrataley: cruce portal × GCS/BQ, descargas dirigidas y reporte."""

__all__ = ["AuditorConfig", "cargar_config"]


def __getattr__(name: str):
    if name in __all__:
        from auditor import config as _config

        return getattr(_config, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
