FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY bridge ./bridge
COPY simulator ./simulator
RUN pip install --no-cache-dir . \
    # Utilisateur non root, membre de dialout pour acceder au port serie transmis par --device
    && useradd --create-home --uid 1000 --groups dialout bridge \
    && mkdir -p /data /config \
    && chown bridge:bridge /data

USER bridge
VOLUME ["/data"]
# 8085 : API REST pour Hopitalia ; 5100 : ecoute ASTM en mode transport = "tcp"
EXPOSE 8085 5100

# /docs ne demande pas de cle API : il suffit pour verifier que le service repond.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8085/docs', timeout=4)"

CMD ["architect-bridge", "--config", "/config/config.toml"]
