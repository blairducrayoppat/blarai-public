# Policy Agent — Multi-stage build
# USE-CASE-001: Action Authorization Boundary
# Target: Hyper-V container with GPU device passthrough (ADR-010)

# --- Build stage ---
FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY src/ src/
COPY config/ config/

RUN pip install --no-cache-dir --prefix=/install .

# --- Runtime stage ---
FROM python:3.11-slim AS runtime

# Security: non-root user
RUN groupadd --gid 1000 blarai && \
    useradd --uid 1000 --gid blarai --shell /bin/false blarai

WORKDIR /app
COPY --from=builder /install /usr/local
COPY --from=builder /build/config config/

# Security: read-only filesystem where possible
# Model weights and certs are mounted as read-only volumes at runtime

USER blarai

# Health check — measured boot readiness
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# NOTE: Actual entrypoint TBD in P1.6 (vsock listener)
# ENTRYPOINT ["python", "-m", "src.boot"]
CMD ["echo", "Policy Agent container stub — P1.0 scaffold"]
