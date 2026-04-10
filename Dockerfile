FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        bluez \
        dbus \
        libdbus-1-3 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY bt_proxy/ bt_proxy/

RUN pip install --no-cache-dir .

EXPOSE 6053

ENTRYPOINT ["bt-proxy"]
