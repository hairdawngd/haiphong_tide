ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    VIETLOTT_HOME=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src /app/src

CMD ["python", "-m", "vietlott.service"]
