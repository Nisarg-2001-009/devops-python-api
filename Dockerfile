# ── Base image ────────────────────────────────────────────────────────────────
# python:3.11-slim is a Debian-based minimal image (~45 MB vs ~900 MB for full).
# Pinning the minor version prevents surprise breakage from upstream updates.
FROM python:3.11-slim

# ── Build-time metadata ───────────────────────────────────────────────────────
LABEL maintainer="nisarg" \
      description="FastAPI finance API"

# ── Python runtime flags ──────────────────────────────────────────────────────
# PYTHONDONTWRITEBYTECODE: skip .pyc files — unnecessary inside a container.
# PYTHONUNBUFFERED: flush stdout/stderr immediately so logs appear in real time.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ── Working directory ─────────────────────────────────────────────────────────
# All subsequent COPY / RUN / CMD instructions operate relative to /app.
WORKDIR /app

# ── Dependency layer (cached separately from source code) ─────────────────────
# Copying requirements.txt BEFORE the rest of the source ensures Docker reuses
# this layer on rebuilds as long as requirements.txt hasn't changed — even if
# the application code changed.
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Application source ────────────────────────────────────────────────────────
# Copied after deps so code edits don't invalidate the expensive pip layer.
COPY . .

# ── Non-root user ─────────────────────────────────────────────────────────────
# Running as root inside a container is a security risk; create a dedicated
# system user with no login shell and no home directory.
RUN adduser --system --no-create-home appuser && \
    chown -R appuser /app
USER appuser

# ── Network ───────────────────────────────────────────────────────────────────
# Document that the container listens on 8000; actual port mapping is in
# docker-compose.yml (or -p flag). EXPOSE is metadata only, not a firewall rule.
EXPOSE 8000

# ── Entrypoint ────────────────────────────────────────────────────────────────
# --host 0.0.0.0   : listen on all interfaces (required inside Docker NAT).
# --port 8000      : match the exposed port above.
# --reload is intentionally omitted here; use an override in docker-compose for dev.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
