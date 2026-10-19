# Cloud Run Job — Subcontrataley (Libro Asistencia / Ingreso Trabajadores)
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    unzip \
    curl \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    libu2f-udev \
    libvulkan1 \
    && rm -rf /var/lib/apt/lists/*

# Google Chrome
RUN mkdir -p /etc/apt/keyrings && \
    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub \
      | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg && \
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
      > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

# ChromeDriver compatible
RUN CHROME_VERSION=$(google-chrome --version | awk '{print $3}' | cut -d. -f1) && \
    CHROMEDRIVER_VERSION=$(curl -sS "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_${CHROME_VERSION}") && \
    wget -q -O /tmp/chromedriver.zip \
      "https://storage.googleapis.com/chrome-for-testing-public/${CHROMEDRIVER_VERSION}/linux64/chromedriver-linux64.zip" && \
    unzip -q /tmp/chromedriver.zip -d /tmp/ && \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver && \
    chmod +x /usr/local/bin/chromedriver && \
    rm -rf /tmp/chromedriver* && \
    chromedriver --version

ENV CHROME_BIN=/usr/bin/google-chrome
ENV CHROMEDRIVER_PATH=/usr/local/bin/chromedriver
ENV HEADLESS=true
ENV PYTHONUNBUFFERED=1
ENV DOWNLOAD_DIR=/tmp/subcontrataley_downloads
ENV DEBUG_DIR=/tmp/subcontrataley_debug

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código de la app (sin secrets ni downloads locales)
COPY config.py browser.py login.py xpaths.py gcs_docs.py plantilla_liquidaciones_store.py ./
COPY parse_liquidacion.py generar_transferencia.py rellenar_plantilla.py rellenar_plantilla_unico.py ./
COPY assets/formato_transferencia.pdf ./assets/formato_transferencia.pdf
COPY rellenar_plantilla_asistencias.py compilar_asistencias.py ./
COPY rellenar_plantilla_trabajadores.py mapa_instalaciones_walmart.py ./
COPY bq_empleados.py bq_asistencia.py cr_contratos.py ./
COPY comparar_trabajadores.py leer_listado_trabajadores.py ./
COPY run_flujo.py libro_asistencia_cloudrun.py ingreso_trabajadores_cloudrun.py ./
COPY liquidaciones_cloudrun.py pagos_afp_afc_cloudrun.py pagos_isapre_fonasa_cloudrun.py ./
COPY pagos_mutualidades_cloudrun.py pagos_cajas_compensacion_cloudrun.py ./
COPY flows/ ./flows/

RUN mkdir -p /tmp/subcontrataley_downloads /tmp/subcontrataley_debug

# Job por defecto: Libro de Asistencia (ingreso usa --args en Cloud Build)
CMD ["python", "libro_asistencia_cloudrun.py"]
