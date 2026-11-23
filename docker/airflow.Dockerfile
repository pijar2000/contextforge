FROM apache/airflow:2.10.5-python3.12

# ContextForge needs SQLAlchemy 2.x; Airflow 2.10 pins 1.4. Keep them apart: Airflow schedules,
# and every task runs inside this separate virtualenv.
USER root
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md /src/contextforge/
COPY src /src/contextforge/src
RUN chown -R airflow /src /opt

USER airflow
RUN python -m venv /opt/contextforge-venv \
    && /opt/contextforge-venv/bin/pip install --no-cache-dir \
       --extra-index-url https://download.pytorch.org/whl/cpu torch \
    && /opt/contextforge-venv/bin/pip install --no-cache-dir /src/contextforge
ENV CONTEXTFORGE_PYTHON=/opt/contextforge-venv/bin/python
