FROM python:3.12-slim

# Hugging Face Spaces ejecuta el contenedor como el usuario 1000; Render/local da igual.
RUN useradd -m -u 1000 user
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=user . .
USER user

# La base de casos vive en /tmp (disco efímero en Spaces; el registro en vivo está en memoria).
ENV ANGRYROBOT_DB=/tmp/angryrobot_cases.db PYTHONUNBUFFERED=1
# HF Spaces: 7860. Render inyecta PORT.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
