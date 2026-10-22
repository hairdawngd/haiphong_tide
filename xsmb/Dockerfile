FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    XSMB_HOME=/data

WORKDIR /app
COPY requirements.txt .
RUN python -m pip install -r requirements.txt
COPY src /app/src

CMD ["python", "-m", "xsmb.service"]
