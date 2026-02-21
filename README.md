# BridgeSurfer - Urlaubsplaner (Docker)

BridgeSurfer ist eine Web-App zur Urlaubsplanung und Abwesenheitsverwaltung. Diese Version wurde für den Betrieb in einem Docker-Container (z.B. Mac mini mit Orbstack) optimiert und benötigt keine externe Datenbank (JSON-basiert).

## Features
* Urlaubsanträge stellen und verwalten
* PDF/Excel-Export der Daten
* Docker-Ready für einfache Installation
* Keine Datenbank-Konfiguration nötig

## Installation (Mac mini mit Orbstack)
1. Repository klonen oder ZIP-Datei entpacken.
2. Orbstack öffnen.
3. Terminal im Ordner öffnen und ausführen:
   ```bash
   docker-compose up -d --build
   ```
4. Die App ist nun unter `http://localhost:5000` erreichbar.

## Standard-Login
* **Benutzer:** `admin`
* **Passwort:** `Admin123`

## GitHub Setup
* Erstelle ein neues Repository auf GitHub.
* Stelle das Repository auf **Privat** (Private).
* Lade die Dateien hoch (die `.gitignore` verhindert das Hochladen sensibler oder temporärer Daten).

## Daten-Lagerung
Alle Daten werden in der Datei `data.json` im Hauptverzeichnis gespeichert. Diese Datei wird über ein Docker-Volume gemountet, damit die Daten beim Neustart des Containers erhalten bleiben.
