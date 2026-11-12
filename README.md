# Subcontrataley webscraper

Scraper Selenium del portal [Subcontrataley](https://www5.subcontrataley.cl/login.php).

## Estructura

```
flows/                         # lógica de cada rama
*_cloudrun.py                  # entry points Cloud Run Job (igual que documentos-instalaciones)
cloudbuild.yaml                # 1 imagen → N jobs
deploy_jobs.sh                 # deploy manual de todos los jobs
run_flujo.py                   # CLI local por rama
```

## Setup

```bash
cd subcontrataley_webscrapper
pip install -r requirements.txt
cp env.example .env   # completar password (comillas si tiene #)
```

## Cloud Run Jobs

Misma forma que `cargas_documentos_instalaciones_webscrapper`:

- **1 imagen** `gcr.io/worldwide-470917/subcontrataley-webscrapper`
- **N jobs**, cada uno con `--command=python --args=*_cloudrun.py`
- Secrets (usuario/password/token) se configuran una vez en el Job; el update
  solo toca vars base (`--update-env-vars`) y no las pisa

| Job | Script |
|-----|--------|
| `subcontrataley-libro-asistencia` | `libro_asistencia_cloudrun.py` |
| `subcontrataley-ingreso-trabajadores` | `ingreso_trabajadores_cloudrun.py` |
| `subcontrataley-liquidaciones` | `liquidaciones_cloudrun.py` |
| `subcontrataley-pagos-afp-afc` | `pagos_afp_afc_cloudrun.py` |
| `subcontrataley-pagos-isapre-fonasa` | `pagos_isapre_fonasa_cloudrun.py` |
| `subcontrataley-pagos-mutualidades` | `pagos_mutualidades_cloudrun.py` |
| `subcontrataley-pagos-cajas` | `pagos_cajas_compensacion_cloudrun.py` |
| `subcontrataley-documentos-trabajador` | `documentos_trabajador_cloudrun.py` |

### Opción 1: Cloud Build desde Git (recomendado)

Igual que `cargas_documentos_instalaciones_webscrapper`: push a `main` → build + update de jobs.

1. Repo GitHub (ej. `wwdiegovarela/subcontrataley_webscrapper`)
2. En [Cloud Build Triggers](https://console.cloud.google.com/cloud-build/triggers?project=worldwide-470917):
   - **CREATE TRIGGER**
   - **Nombre:** `deploy-subcontrataley-jobs`
   - **Event:** Push to a branch
   - **Branch:** `^main$`
   - **Configuration:** Cloud Build configuration file
   - **Location:** `cloudbuild.yaml`
3. Primera vez: configurar secrets en cada Job (ver abajo). Los siguientes deploys no los pisan.

```bash
cd subcontrataley_webscrapper
git push origin main
# o manual:
gcloud builds submit --config=cloudbuild.yaml .
```

### Opción 2: deploy_jobs.sh

```bash
cd subcontrataley_webscrapper
bash deploy_jobs.sh
```

### Secrets (una vez)

```bash
gcloud run jobs update subcontrataley-libro-asistencia --region=us-east1 \
  --update-env-vars="SUBCONTRATALEY_USERNAME=USER,SUBCONTRATALEY_PASSWORD=PASS"

gcloud run jobs update subcontrataley-ingreso-trabajadores --region=us-east1 \
  --update-env-vars="SUBCONTRATALEY_USERNAME=USER,SUBCONTRATALEY_PASSWORD=PASS,TOKEN_CR_CONTRATOS=TOKEN"
```

### Ejecutar

```bash
gcloud run jobs execute subcontrataley-libro-asistencia --region=us-east1
gcloud run jobs execute subcontrataley-ingreso-trabajadores --region=us-east1
gcloud run jobs execute subcontrataley-documentos-trabajador --region=us-east1
```

Documentos vigentes del trabajador: **nivel PERSONA** (por RUT en la sección de
documentos del trabajador). No usan plantillas de faena (`cmsd_*` / Cargar plantillas).
Reutilizan dropzone/validación/Documentos Agregados. XPaths `persona.*` pendientes
de captura. **Origen de PDFs pendiente**; proveedor provisional:
`DOCUMENTOS_TRABAJADOR_FUENTE=local|gcs` (+ `DOCUMENTOS_TRABAJADOR_LOCAL_ROOT` si local).
Filtro: `DOCUMENTOS_TRABAJADOR_CLAVES=...`. Probar: `DRY_RUN=true`.

### Local (simula contenedor)

```bash
HEADLESS=true python libro_asistencia_cloudrun.py
HEADLESS=true python ingreso_trabajadores_cloudrun.py
DRY_RUN=true HEADLESS=true python documentos_trabajador_cloudrun.py
# o pipeline ingreso vía CLI:
python run_flujo.py ingreso_trabajadores_e2e
# un documento vigente:
python run_flujo.py cedulas_identidad
```

**Permisos SA** (`webscrapper@worldwide-470917.iam.gserviceaccount.com`):

- Libro asistencia: `storage.objectViewer` (o similar) en el bucket de documentos
- Ingreso: BigQuery Data Viewer / Job User en `worldwide-470917.cr_reportes`

**Ingreso — pipeline:** listado SCL → BQ/CR (asistencia + contratos + faena ≤1 mes) →
plantilla vacía fresca → rellenar → validar → carga masiva.

## Ramos CLI locales

| CLI | Descripción |
|-----|-------------|
| `liquidaciones` | Liquidaciones de Sueldo |
| `libro_asistencia` | Libro de Asistencia |
| `pagos_afp_afc` | Pagos AFP y AFC |
| `pagos_isapre_fonasa` | Pagos Isapre / FONASA |
| `listado_trabajadores` | Listado finiquitables |
| `ingreso_trabajadores` | Solo subir plantilla ya rellena |
| `ingreso_trabajadores_e2e` | Pipeline completo de ingreso |
| `cedulas_identidad` (y 14 más) | Docs vigentes (nivel PERSONA, por RUT) |

```bash
python run_flujo.py --list
python run_flujo.py liquidaciones
```

## Niveles de carga (faena vs persona)

| Nivel | Flujos | Navegación portal |
|-------|--------|-------------------|
| **FAENA** | liquidaciones, libro, pagos (AFP/Isapre/Mutual/Cajas) | Cargas Masivas → plantillas `cmsd_*` |
| **PERSONA** | 15 docs vigentes del trabajador | Sección documentos del trabajador, por RUT (`persona.*`) |

Enum: `flows.nivel_carga.NivelCarga`.

## Cargas agrupadas por faena

Libro de Asistencia, Pagos Mutualidades y Pagos Cajas de Compensación usan una
plantilla del portal **por faena** (sin columna RUT). Pipeline común
(`compilar_asistencias.compilar_docs_por_faena(base, FuenteDocsFaena)` + `rellenar_plantilla_asistencias(..., etiqueta=)`; la fuente GCS se parametriza por flujo: `FUENTE_ASISTENCIA` y `pagos_config.fuente_por_faena(cfg)`):

1. Descargar la plantilla de **Liquidaciones de Sueldo** (base: RUT → faena).
2. Por faena, bajar de GCS el PDF de cada RUT y fusionarlos en 1 PDF:
   `{faena_slug}_{Etiqueta}_{mes año}.pdf`
   - Libro de Asistencia: `Trabajadores/{rut}/Asistencia/{mes año}/` (orden del Excel), etiqueta `Asistencia`.
   - Mutualidades / Cajas: `Trabajadores/{rut}/Cotizaciones/{YYYY}/{MM}/` (orden por RUT),
     etiquetas `Mutualidades` / `CajasCompensacion`.
3. Descargar la plantilla propia (por faena) y escribir el PDF en `nombre_de_archivo`
   de la fila de esa faena. RUT sin PDF → `resumen_compilacion.json` y log.
4. Subir Excel + PDFs (respeta `DRY_RUN`).

## GCS — Tres raíces (lectura)

Los flujos que bajan PDFs (`liquidaciones`, `libro_asistencia`, pagos) leen el bucket
`worldwide-documentos-instalaciones` vía `gcs_docs.py`.

Rutas canónicas (personales):

```text
Trabajadores/{rut}/Liquidacion/{mes año}/*.pdf
Trabajadores/{rut}/Transferencia/{mes año}/*.pdf
Trabajadores/{rut}/Asistencia/{mes año}/*.pdf
Trabajadores/{rut}/Cotizaciones/{YYYY}/{MM}/*.pdf
```

Documentos vigentes del trabajador: el layout de origen **aún no está cerrado**;
el flujo lee vía proveedor configurable (`flows/proveedor_documentos_trabajador.py`).


Durante la migración se mantiene dual-read: primero `Trabajadores/`, luego globs
legacy (`{cecos}/{Tipo}/...` o `Industry|Security/{cecos}/...`). Si un RUT tiene
ambos, gana la ruta bajo `Trabajadores/`.

Este repo **no escribe** GCS (solo lista/descarga y sube al portal Subcontrataley).

## Convención de captura

```text
flujo: liquidaciones
xpath plantilla: /html/body/...
```
