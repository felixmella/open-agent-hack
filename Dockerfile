# FactSync Chile in a container: the API by default, or the CLI and the tests.
#
#   docker build -t factsync .
#   docker run --rm -p 8000:8000 --env-file .env \
#       -e ZETARIS_REST_URL=http://host.docker.internal:8888/api/v1.0 \
#       -e METERLESS_BASE_URL=http://host.docker.internal:8088/v1 factsync
#   docker run --rm --network none -e SAMPLE_MODE=true factsync python run.py input_examples/example_2.json
#   docker run --rm factsync pytest
#
# Zetaris and Nightshift run on the host, so the container reaches them at host.docker.internal. No secrets are baked
# in: settings come from the environment (--env-file .env).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTEST_ADDOPTS="-p no:cacheprovider"
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY data data
COPY input_examples input_examples
COPY scripts scripts
COPY tests tests
COPY zetaris zetaris
COPY run.py pytest.ini .env.example metadata.json LICENSE NOTICE ./

RUN useradd --uid 1000 --create-home factsync \
    && mkdir -p output logs state \
    && chown -R factsync:factsync output logs state
USER factsync

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
