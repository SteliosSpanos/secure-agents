FROM python:3.11-slim as builder

ENV PYTHONUSERBASE=/build/user_base
WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.11-slim

WORKDIR /app

RUN groupadd -r appuser && useradd -m -r -g appuser appuser

USER appuser
WORKDIR /home/appuser

COPY --from=builder --chown=appuser:appuser /root/.local .local

COPY --chown=appuser:appuser . .

ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "75"]
