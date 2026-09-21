# Profile collector image: stdlib Python + git. Built from the repo root by
# collector/cloudbuild.yaml; runs scripts/collect_mirrors.py as a Cloud Run Job.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY scripts/ scripts/

# /tmp is memory-backed on Cloud Run; mirrors live there for the run and are
# persisted to the Cloud Storage state mount between runs.
ENV PYTHONUNBUFFERED=1 \
    TZ=America/Los_Angeles \
    STATE_DIR=/mnt/state \
    WORK_DIR=/tmp/collector

ENTRYPOINT ["python3", "scripts/collect_mirrors.py"]
