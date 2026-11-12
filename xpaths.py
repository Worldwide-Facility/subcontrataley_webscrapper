"""
Catálogo de selectores Subcontrataley.

Prefijos:
  login.* / post_login.*  — autenticación
  nav.*                   — tronco común hasta Cargar plantillas
  plantilla.*             — elegir tipo de plantilla (rama)
  <flujo>.*               — pasos propios de cada carga
"""

LOGIN_URL = "https://www5.subcontrataley.cl/login.php"

# None = pendiente de captura (el flujo llega al tronco y avisa)
XPATHS = {
    # --- Login ---
    "login.usuario": "/html/body/div[1]/div[1]/div[2]/form/div[2]/div[1]/input",
    "login.password": "/html/body/div[1]/div[1]/div[2]/form/div[2]/div[2]/input",
    "login.boton_iniciar": "/html/body/div[1]/div[1]/div[2]/form/div[4]/button",
    # --- Post-login (modal INFORMACIÓN / avisos) ---
    # Preferir "Cancelar" por texto; el absolute path queda de respaldo
    "post_login.btn_cancelar": (
        "//*[self::button or self::a or self::span]"
        "[contains(normalize-space(.),'Cancelar') "
        "or contains(normalize-space(.),'Cerrar')]"
        # Nunca el link "Cerrar Sesión" (logout.php)
        "[not(contains(@href,'logout'))]"
    ),
    "post_login.boton": "/html/body/div[13]/div[4]/div/div/div[3]/button",
    "post_login.btn_cerrar_x": (
        "//div[contains(@class,'modal')]"
        "//button[contains(@class,'close') or @data-dismiss='modal' "
        "or contains(@class,'btn-close') or @aria-label='Close']"
    ),
    # --- Tronco común → Cargar plantillas ---
    "nav.paso_1": "/html/body/div[6]/div[2]/div[2]/a",
    "nav.paso_2": "/html/body/div[6]/div[1]/div[1]/a[3]",
    "nav.cargar_plantillas": "/html/body/div[6]/div[2]/div[3]/div[1]",
    # --- Rama: elegir plantilla (otras ramas, pendiente) ---
    "plantilla.libro_asistencia": None,
    "plantilla.pagos_afp_afc": None,
    "plantilla.pagos_isapre_fonasa": None,
    # --- Liquidaciones de Sueldo ---
    # 2026-10-09: el portal agregó "Categoría"; div[5] pasó a ser Servicio.
    # Absolutos actualizados (div[6]=Documento, div[7]=Periodo).
    "liquidaciones.select_tipo": (
        "/html/body/div[6]/div[2]/div[3]/div[3]/div[2]/div[6]/select"
    ),
    "liquidaciones.select_periodo": (
        "/html/body/div[6]/div[2]/div[3]/div[3]/div[2]/div[7]/select"
    ),
    "liquidaciones.btn_descargar_plantilla": "//*[@id='cmsd_btn_descargar_plantilla']",
    # Toggle entre tarjetas del form de carga masiva
    "liquidaciones.ir_a_descargar": "/html/body/div[6]/div[2]/div[3]/div[1]",
    # --- Liquidaciones: carga de plantilla + PDFs ---
    "liquidaciones.ir_a_cargar": "/html/body/div[6]/div[2]/div[3]/div[2]",
    "liquidaciones.input_excel": (
        "/html/body/div[6]/div[2]/div[3]/div[3]/div[2]/div[1]/div/div/div[1]/div/div[1]/input"
    ),
    "liquidaciones.btn_enviar_excel": (
        "/html/body/div[6]/div[2]/div[3]/div[3]/div[2]/div[1]/div/div/div[1]/div/div[2]/button"
    ),
    "liquidaciones.zona_upload_liquidaciones": (
        "/html/body/div[6]/div[2]/div[3]/div[3]/div[2]/div[1]/div/div/div[3]/div[2]"
    ),
    # Dropzone documentos (asistencia / carga 1-doc). Confirmado en UI 2026-08-03.
    "asistencias.zona_upload_documentos": (
        "/html/body/div[6]/div[2]/div[3]/div[3]/div[2]/div[1]/div/div/div[3]/div[2]"
    ),
    # Mensaje interno del dropzone (opcional; el input real es .dz-hidden-input)
    "asistencias.zona_upload_documentos_msg": (
        "/html/body/div[6]/div[2]/div[3]/div[3]/div[2]/div[1]/div/div/div[3]/div[2]/div[1]"
    ),
    "liquidaciones.zona_upload_transferencias": (
        "/html/body/div[6]/div[2]/div[3]/div[3]/div[3]/div/div/div/div/div/div"
    ),
    "liquidaciones.btn_confirmar_carga": (
        "/html/body/div[6]/div[2]/div[3]/div[3]/div[2]/div[1]/div/div/div[4]/button"
    ),
    # Alias explícito (mismo botón; id del portal)
    "liquidaciones.btn_validar_documentos": (
        "//*[@id='cmsd_btn_validar_documentos']"
    ),
    # Pantalla 2.3 tras validar OK (0 errores)
    "asistencias.btn_realizar_carga_masiva": (
        "//button[contains(normalize-space(.),'Realizar Carga Masiva')]"
    ),
    # Tras "Realizar Carga Masiva": SOLO cuando el proceso ya terminó de cargar.
    # No clickear de inmediato; espera éxito/fin de carga y luego este botón.
    "liquidaciones.btn_post_confirmar": (
        "/html/body/div[6]/div[2]/div[2]/div[1]/div/div/div/div/div/div/div[5]/div[2]/button/span"
    ),
    # Alias libro de asistencia / misma pantalla post-carga masiva
    # Legacy eliminado: el XPath absoluto apuntaba a 'Realizar Carga Masiva'.
    "asistencias.btn_despues_carga_masiva": None,
    # --- Listado trabajadores (menú finiquitos / personal) ---
    # Tras Carga Masiva (nav.paso_1).
    "trabajadores.paso_1": (
        "//*[self::a or self::div or self::button or self::span]"
        "[contains(normalize-space(.),'Finiquitar trabajadores')]"
    ),
    # "Descarga Plantilla Nueva" en GESTIÓN DE DESVINCULACIÓN…
    "trabajadores.paso_2": "/html/body/div[6]/div[2]/div[3]/div[1]",
    # Botón que dispara la descarga del Excel de trabajadores activos
    "trabajadores.btn_exportar": (
        "/html/body/div[6]/div[2]/div[4]/div/div[2]/div[6]/button"
    ),
    # --- Ingreso trabajadores (Crear trabajadores → Subir plantilla) ---
    # Sidebar <a> con onclick (el contains genérico matchea <html> y el click
    # cae en el centro → card Finiquitar).
    "ingreso.crear_trabajadores": (
        "//a[contains(@class,'menu-left-item')]"
        "[contains(normalize-space(.),'Crear trabajadores')]"
    ),
    # Card derecha en CREAR TRABAJADORES (texto distinto a Finiquitar)
    "ingreso.subir_plantilla": (
        "//div[contains(@class,'col-5')]"
        "[contains(normalize-space(.),'Subir Plantilla')]"
        "[not(contains(normalize-space(.),'Descargar'))]"
    ),
    # Dropzone Crear (estructura distinta a Finiquitar; id portal cmt_*)
    "ingreso.input_excel": (
        "//div[contains(@class,'dropzone') and contains(@class,'dz-clickable')]"
    ),
    # Botón verde Validar Plantilla
    "ingreso.btn_enviar": "//*[@id='cmt_btn_validar_planilla']",
    # Card izquierda: Descargar Nueva Plantilla
    "ingreso.descargar_plantilla": (
        "//div[contains(@class,'col-5')]"
        "[contains(normalize-space(.),'Descargar Nueva Plantilla')]"
    ),
    # Botón verde Descargar Plantilla (plantilla vacía fresca)
    "ingreso.btn_descargar_plantilla": "//*[@id='cmt_btn_descargar_plantilla']",
    # Tras validación OK (0 errores)
    "ingreso.btn_realizar_carga_masiva": "//*[@id='cmt_btn_realizar_carga_masiva']",
}


def xp(key: str) -> str:
    """Obtiene un XPath por clave. Falla claro si falta o está pendiente."""
    if key not in XPATHS:
        raise KeyError(
            f"XPath no definido: '{key}'. Agrégalo en xpaths.py tras capturarlo."
        )
    value = XPATHS[key]
    if not value:
        raise KeyError(
            f"XPath pendiente de captura: '{key}'. "
            "Pásalo en el chat y lo cableamos."
        )
    return value


def xpath_pendiente(key: str) -> bool:
    return key in XPATHS and not XPATHS[key] and not FALLBACKS.get(key)


# ---------------------------------------------------------------------------
# Selectores con respaldo (robustez ante cambios de XPath / id)
# ---------------------------------------------------------------------------
# Para cada clave: lista ORDENADA de XPaths candidatos.
#   1) atributos estables (id / name / data-* / aria-label / onclick)
#   2) texto / label relativo, acotado a un contenedor
#   3) el XPath absoluto histórico (XPATHS[key]) SIEMPRE al final
# browser.resolver_selector() prueba en orden y exige 1 solo match visible;
# si gana un candidato que no es el primero, emite WARNING (drift).
#
# Las claves que no estén aquí usan solo XPATHS[key] (compatibilidad total).
FALLBACKS: dict[str, list[str]] = {
    # --- Login (DOM real 2026-10-09: form#loginform, input#username/#password) ---
    "login.usuario": [
        "//form[@id='loginform']//input[@id='username']",
        "//input[@name='inputUsername']",
        "//form[@id='loginform']//input[@type='text' and @placeholder='Usuario']",
    ],
    "login.password": [
        "//form[@id='loginform']//input[@id='password']",
        "//input[@name='inputPassword']",
        "//form[@id='loginform']//input[@type='password']",
    ],
    "login.boton_iniciar": [
        "//form[@id='loginform']//button[@type='submit']",
        "//form[@id='loginform']//button[normalize-space(.)='Iniciar sesión']",
    ],
    # --- Modal INFORMACIÓN post-login (div#md_video, Bootstrap .modal.in) ---
    "post_login.btn_cancelar": [
        "//div[contains(@class,'modal') and contains(@class,'in')]"
        "//div[contains(@class,'modal-footer')]"
        "//button[@data-dismiss='modal' or @data-bs-dismiss='modal']",
        "//div[@id='md_video']//button[@data-dismiss='modal'][normalize-space(.)='Cerrar']",
    ],
    "post_login.boton": [
        "//div[@id='md_video']//div[contains(@class,'modal-footer')]//button",
    ],
    "post_login.btn_cerrar_x": [
        "//div[contains(@class,'modal') and contains(@class,'in')]"
        "//button[contains(@class,'close') and (@data-dismiss='modal' or @data-bs-dismiss='modal')]",
    ],
    # --- Tronco: Home → Cargas Masivas → Subir documentos → Descarga Plantilla ---
    "nav.paso_1": [
        "//a[@href='/carga_masiva.php']",
        "//a[contains(@class,'btn-modulos-administrables')]"
        "[contains(normalize-space(.),'Cargas Masivas')]",
    ],
    "nav.paso_2": [
        "//a[contains(@onclick,'getContentCargaMasivaSubirDocumentos(')]",
        "//div[@id='left-menu']//a[contains(@class,'menu-left-item')]"
        "[contains(normalize-space(.),'Subir documentos')]",
    ],
    "nav.cargar_plantillas": [
        "//div[@id='cmsd_opt_download']",
        "//div[@id='datos']//div[contains(@class,'cursor-pointer')]"
        "[normalize-space(.)='Descarga Plantilla Nueva']",
    ],
    # --- Subir documentos: selects (ids cmsd_*) ---
    "liquidaciones.select_tipo": [
        "//select[@id='cmsd_documento']",
        "//select[@name='cmsd_documento']",
        "//label[@for='cmsd_documento' or normalize-space(.)='Documento']"
        "/following-sibling::select[1]",
    ],
    "liquidaciones.select_periodo": [
        "//select[@id='cmsd_periodos']",
        "//select[@name='cmsd_periodos']",
        "//label[@for='cmsd_periodos' or normalize-space(.)='Periodo Correspondiente']"
        "/following-sibling::select[1]",
    ],
    "liquidaciones.btn_descargar_plantilla": [
        "//button[@id='cmsd_btn_descargar_plantilla']",
        "//button[@name='cmsd_btn_descargar_plantilla']",
    ],
    "liquidaciones.ir_a_descargar": [
        "//div[@id='cmsd_opt_download']",
        "//div[@id='datos']//div[contains(@class,'cursor-pointer')]"
        "[normalize-space(.)='Descarga Plantilla Nueva']",
    ],
    "liquidaciones.ir_a_cargar": [
        "//div[@id='cmsd_opt_upload']",
        "//div[@id='datos']//div[contains(@class,'cursor-pointer')]"
        "[normalize-space(.)='Subir Plantilla']",
    ],
    # --- Subir documentos: pantalla 2 (subir plantilla + dropzones) ---
    "liquidaciones.input_excel": [
        "//input[@id='cmsd_archivo_excel']",
        "//input[@type='file' and @aria-label='Upload Excel file']",
        "//div[@id='cmsd_subtitulo_cargar_excel']//input[@type='file']",
    ],
    "liquidaciones.btn_enviar_excel": [
        "//button[@id='cmsd_btn_archivo_excel']",
        "//div[@id='cmsd_subtitulo_cargar_excel']//button[contains(normalize-space(.),'Cargar Excel')]",
    ],
    # Dropzone principal: oculto (hidden) hasta que el portal acepta el Excel
    "liquidaciones.zona_upload_liquidaciones": [
        "//div[@id='cmsd_frm_dropzone']",
        "//div[@id='cmsd_subtitulo_cargar_documentos']//div[contains(@class,'dropzone')]",
    ],
    "asistencias.zona_upload_documentos": [
        "//div[@id='cmsd_frm_dropzone']",
        "//div[@id='cmsd_subtitulo_cargar_documentos']//div[contains(@class,'dropzone')]",
    ],
    "asistencias.zona_upload_documentos_msg": [
        "//div[@id='cmsd_frm_dropzone']/div[contains(@class,'dz-message')]",
    ],
    # Documentos asociados (transferencias): contenido inyectado por el portal en
    # #cmsd_documentos_asociados tras aceptar el Excel (documentoform_id 2/4).
    "liquidaciones.zona_upload_transferencias": [
        "//div[@id='cmsd_documentos_asociados']//div[contains(@class,'dropzone')]",
    ],
    # Botón "Validar Documentos": lo inserta el JS del portal (id fijo) cuando
    # el dropzone tiene >=1 archivo.
    "liquidaciones.btn_confirmar_carga": [
        "//button[@id='cmsd_btn_validar_documentos']",
        "//div[@id='cmsd_div_btn_validar_documentos']//button",
    ],
    "liquidaciones.btn_validar_documentos": [
        "//button[@id='cmsd_btn_validar_documentos']",
        "//div[@id='cmsd_div_btn_validar_documentos']//button",
    ],
    # Pantalla 2.3 (tras Validar Documentos, 0 errores): botón FINAL que ejecuta la
    # carga. Verificado en vivo 2026-10-09 (prueba liquidaciones 1 persona, sin click):
    # el XPath absoluto legacy de btn_post_confirmar apunta a este mismo botón.
    "liquidaciones.btn_post_confirmar": [
        "//button[@id='cmsd_btn_realizar_carga_masiva']",
        "//button[contains(normalize-space(.),'Realizar Carga Masiva')]",
    ],
    "asistencias.btn_realizar_carga_masiva": [
        "//button[@id='cmsd_btn_realizar_carga_masiva']",
    ],
    # Post-carga: NUNCA debe coincidir con 'Realizar Carga Masiva' (el XPath absoluto
    # legacy apunta a ese mismo botón en la pantalla 2.3).
    "asistencias.btn_despues_carga_masiva": [
        "//div[contains(@class,'modal') and contains(@class,'in')]//button"
        "[not(@id='cmsd_btn_realizar_carga_masiva')]"
        "[not(contains(normalize-space(.),'Realizar Carga Masiva'))]"
        "[contains(.,'Aceptar') or contains(.,'Continuar') or contains(.,'Finalizar')]",
    ],
    # --- Finiquitar trabajadores (listado) ---
    "trabajadores.paso_1": [
        "//a[contains(@onclick,'getContentCargaMasivaFiniquitarTrabajadores(')]",
        "//div[@id='left-menu']//a[contains(@class,'menu-left-item')]"
        "[contains(normalize-space(.),'Finiquitar trabajadores')]",
    ],
    # Ojo: Crear trabajadores usa el MISMO id cmct_opt_download (sin onclick);
    # en Finiquitar la tarjeta tiene onclick="descargar()" y vive en #div_opciones.
    "trabajadores.paso_2": [
        "//div[@id='cmct_opt_download'][@onclick='descargar()']",
        "//div[@id='div_opciones']/div[contains(@class,'cursor-pointer')]"
        "[normalize-space(.)='Descarga Plantilla Nueva']",
    ],
    "trabajadores.btn_exportar": [
        "//button[@id='cmt_btn_descargar_plantilla']",
        "//button[@name='cmt_btn_descargar_plantilla']",
    ],
    # --- Crear trabajadores (ingreso) ---
    "ingreso.crear_trabajadores": [
        "//a[contains(@onclick,'getContentCargaMasivaTrabajadores(')]",
    ],
    "ingreso.subir_plantilla": [
        "//div[@id='cmt_content_subida']//div[@id='cmct_opt_upload']",
    ],
    "ingreso.descargar_plantilla": [
        "//div[@id='cmt_content_subida']//div[@id='cmct_opt_download']",
    ],
    "ingreso.input_excel": [
        "//div[@id='cmt_content_subida']//div[@id='frm_dropzone']",
        "//div[@id='frm_dropzone']",
    ],
    "ingreso.btn_enviar": [
        "//button[@id='cmt_btn_validar_planilla']",
        "//button[@name='cmt_btn_validar_planilla']",
    ],
    "ingreso.btn_descargar_plantilla": [
        "//div[@id='cmt_content_subida']//button[@id='cmt_btn_descargar_plantilla']",
        "//button[@id='cmt_btn_descargar_plantilla']",
    ],
    # Existe 2 veces en el DOM (oculto); el resolver exige 1 visible.
    "ingreso.btn_realizar_carga_masiva": [
        "//button[@id='cmt_btn_realizar_carga_masiva']",
    ],
}


def candidatos(key: str) -> list[str]:
    """
    Lista ordenada de XPaths candidatos para una clave.
    El XPath histórico (XPATHS[key]) va siempre al final como último respaldo.
    """
    if key not in XPATHS and key not in FALLBACKS:
        raise KeyError(
            f"XPath no definido: '{key}'. Agrégalo en xpaths.py tras capturarlo."
        )
    out: list[str] = []
    for c in FALLBACKS.get(key, []):
        if c and c not in out:
            out.append(c)
    legado = XPATHS.get(key)
    if legado and legado not in out:
        out.append(legado)
    if not out:
        raise KeyError(
            f"XPath pendiente de captura: '{key}'. "
            "Pásalo en el chat y lo cableamos."
        )
    return out
