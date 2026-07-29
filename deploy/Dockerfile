# The ONE catsim image: every fleet role (chip, scheduler, provisioner,
# dashboard) runs this same image — the role comes from CATSIM_ROLE at run
# time, never from the build. Build from the repo root:
#   docker build -f deploy/Dockerfile -t catsim:latest .
#
# Two stages because stim/pymatching ship no linux/aarch64 wheels: the full
# image compiles them once (cached layer), the slim image ships the result.
FROM python:3.12 AS builder
WORKDIR /app
# Dependency wheels first, from pyproject alone: source edits then reuse this
# (expensive: stim compiles from source) layer instead of rebuilding it.
COPY pyproject.toml ./
RUN python - <<'PY' > /tmp/requirements.txt
import tomllib
project = tomllib.load(open("pyproject.toml", "rb"))["project"]
print("\n".join(project["dependencies"] + project["optional-dependencies"]["docker"]))
PY
RUN pip wheel --no-cache-dir -w /wheels -r /tmp/requirements.txt
COPY README.md ./
COPY catsim ./catsim
RUN pip wheel --no-cache-dir --no-deps -w /wheels .

FROM python:3.12-slim
WORKDIR /app
RUN --mount=from=builder,source=/wheels,target=/wheels \
    pip install --no-cache-dir --no-index --find-links=/wheels "catsim[docker]"

# Configs ship in the image: a chip needs only the bus address to boot, and
# resolves noise/machine names against these shipped YAMLs.
COPY configs ./configs

ENV CATSIM_ROLE=chip
ENTRYPOINT ["catsim", "node"]
