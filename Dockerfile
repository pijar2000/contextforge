FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models
WORKDIR /app

# Install CPU-only torch first so sentence-transformers does not pull the large CUDA build.
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu torch

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[dashboard]"

COPY config ./config
COPY datasets ./datasets
COPY dashboard ./dashboard
COPY scripts ./scripts

EXPOSE 8000 8501
CMD ["uvicorn", "contextforge.api.app:get_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
