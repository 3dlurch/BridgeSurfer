FROM python:3.11-slim

WORKDIR /app

# System-Abhängigkeiten (für Pandas Excel-Export)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Python-Abhängigkeiten
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App-Dateien kopieren
COPY . .

# Verzeichnisse für Daten und Backups sicherstellen
RUN mkdir -p backups static templates

# Port freigeben
EXPOSE 5000

# Startbefehl
CMD ["python", "app.py"]
