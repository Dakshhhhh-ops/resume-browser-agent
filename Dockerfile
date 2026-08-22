# Single-service image: FastAPI serves the API *and* the built React app.
#
# Based on the Playwright image because the WebCMD browser agent drives a
# real Chromium (webcmd depends on playwright-core, which ships no browser
# of its own). This base already has Chromium plus every system library it
# needs, which is the fiddly part to get right on a bare Python image.
FROM mcr.microsoft.com/playwright:v1.49.1-jammy

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    API_HOST=0.0.0.0

# ---- Python runtime -------------------------------------------------
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- Backend dependencies (own layer, changes rarely) ---------------
COPY backend/requirements.txt backend/requirements.txt
RUN pip3 install --no-cache-dir -r backend/requirements.txt

# ---- WebCMD CLI -----------------------------------------------------
RUN npm install -g @agentrhq/webcmd@0.7.4

# ---- Frontend build -------------------------------------------------
# Dependencies first so edits to src/ don't reinstall node_modules.
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci

COPY frontend/ frontend/
# Empty VITE_API_URL => the app calls its own origin, which this server serves.
RUN cd frontend && VITE_API_URL= npm run build

# ---- Application code -----------------------------------------------
COPY backend/ backend/
COPY *.py ./

# Uploaded resumes live here; ephemeral on most PaaS hosts.
RUN mkdir -p uploads

EXPOSE 8010

CMD ["python3", "run_server.py"]
