# Single-service image: FastAPI serves the API *and* the built React app.
#
# Deliberately does NOT bundle Chromium. The browser agent needs a real
# browser and 60-120s per application, which no free-tier instance can
# hold, so the deployed service covers parsing, discovery and ranking.
# /api/apply returns a clear "webcmd is not installed" error there, and
# applying is run locally instead. See "Limitations" in the README.
#
# To build an image that CAN apply, use the Playwright base instead:
#   FROM mcr.microsoft.com/playwright:v1.49.1-jammy
# then install python3 and `npm i -g @agentrhq/webcmd`. Needs ~2GB and
# a paid instance.

# ---- Stage 1: build the frontend ------------------------------------
FROM node:20-alpine AS frontend

WORKDIR /build

# Dependencies first so edits to src/ don't reinstall node_modules.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Empty VITE_API_URL => the app calls its own origin, which this serves.
RUN VITE_API_URL= npm run build


# ---- Stage 2: python runtime ----------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    API_HOST=0.0.0.0

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Application code
COPY backend/ backend/
COPY *.py ./

# Compiled UI from stage 1 — its presence is what makes the server
# mount the SPA at "/" instead of returning the JSON status payload.
COPY --from=frontend /build/dist frontend/dist

# Uploaded resumes land here; ephemeral on most PaaS hosts.
RUN mkdir -p uploads

EXPOSE 8010

CMD ["python", "run_server.py"]
