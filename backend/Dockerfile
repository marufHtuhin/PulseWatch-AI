# PulseWatch AI — backend image (FastAPI + SQLAlchemy + Alembic).
#
# Built by docker-compose.yml at the project root (`build: ./backend`).
# The compose file overrides the command with the same migration + server
# startup; the CMD below is the standalone default so `docker run` alone
# also works (with DATABASE_URL pointed at a reachable MySQL).
#
# Build:  docker build -t pulsewatch-backend ./backend
# Run:    docker run -p 8000:8000 -e DATABASE_URL=mysql+pymysql://user:pass@host:3306/pulsewatch pulsewatch-backend
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so the layer is cached across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code + Alembic migrations.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

EXPOSE 8000

# Apply migrations, then serve. (Must match docker-compose.yml's command,
# except the port: Render injects $PORT at runtime and the service must
# listen on it; locally it defaults to 8000.)
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
