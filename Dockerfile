FROM python:3.11.9-slim AS python-base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    VENV_PATH="/opt/.venv"

ENV PATH="$VENV_PATH/bin:$PATH"

FROM python-base AS builder-base

WORKDIR /opt

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    curl \
    build-essential \
    git

COPY ./pyproject.toml ./requirements.txt ./

FROM builder-base AS pipinstall

RUN mkdir $VENV_PATH \
    && python -m venv $VENV_PATH \
    && . $VENV_PATH/bin/activate \
    && pip install --upgrade pip \
    && pip install -r requirements.txt

FROM python-base AS runtime

COPY --from=pipinstall $VENV_PATH $VENV_PATH

COPY ./docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

COPY ./pcbot /app/pcbot
RUN mkdir /app/logs
COPY ./config.p* /app/config.py
COPY ./localconfig.p* /app/localconfig.py
COPY ./.env /app/.env

WORKDIR /app

ENTRYPOINT /docker-entrypoint.sh $0 $@
CMD [ "python3", "-m", "pcbot.__main__"]
