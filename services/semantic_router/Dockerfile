# Semantic Router — Lightweight build
# USE-CASE-004: CPU-Based Intent Classification
# No NPU passthrough required — CPU-only ONNX Runtime.

# --- Build stage ---
FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY src/ src/
COPY config/ config/

RUN pip install --no-cache-dir --prefix=/install .

# --- Runtime stage ---
FROM python:3.11-slim AS runtime

RUN groupadd --gid 1000 blarai && \
    useradd --uid 1000 --gid blarai --shell /bin/false blarai

WORKDIR /app
COPY --from=builder /install /usr/local
COPY --from=builder /build/config config/

USER blarai

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# NOTE: Actual entrypoint TBD in P1.7 (classification endpoint)
CMD ["echo", "Semantic Router container stub — P1.0 scaffold"]
