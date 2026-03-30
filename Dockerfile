FROM python:3.11.9-slim AS python-base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    VENV_PATH="/opt/.venv"

# Make venv the default python
ENV PATH="$VENV_PATH/bin:$PATH"


FROM python-base AS builder-base

WORKDIR /opt

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Create isolated Python env + install deps
RUN python -m venv $VENV_PATH \
    && python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

# ---------- Runtime ----------
FROM python-base AS runtime

# Copy the fully-built Python environment
COPY --from=builder-base $VENV_PATH $VENV_PATH

WORKDIR /app
COPY ./pcbot /app/pcbot
COPY ./docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "-m", "pcbot.__main__", "--config", "env/config.py", "--localconfig", "env/localconfig.py"]
