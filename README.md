# Codex Map Collector

Independent local web app for collecting company data from map providers, enriching it, checking websites, and generating landing-page materials. Built with Codex.

## What it does

- Universal parser with provider selection:
  - 2GIS API
  - Yandex Maps Search API
  - Google Places API
  - OpenStreetMap / Nominatim
- Unified CSV output for all providers.
- Table editor, website enrichment, social/contact extraction, 152-FZ website audit, screenshots, and landing generation.
- Local-first workflow: uploaded files, outputs, and API keys stay on the machine.
- Public build exposes Codex only for AI-assisted generation. Other local agents are intentionally not wired into the app.

## Privacy and public safety

This repository does not include local settings, uploaded files, parser output, API keys, virtual environments, or private handoff notes. Runtime data is ignored by Git through `.gitignore`.

The app stores optional provider keys only in `data/settings.json` when the user explicitly chooses to remember them. That file is not committed.

## Run locally

```bash
python3 start.py
```

The launcher creates `.venv`, installs dependencies, starts FastAPI, and opens the browser.

Manual run:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 7860
```

Open http://127.0.0.1:7860.

## API keys

Commercial map providers require your own official API keys. Enter them in the parser panel or set them through local environment variables. If you choose “Remember locally” in the app, keys are stored in `data/settings.json`, which is ignored by Git.

Supported local environment variables:

- `DGIS_API_KEY`
- `DGIS_REVIEWS_API_KEY`
- `YANDEX_MAPS_API_KEY`
- `GOOGLE_PLACES_API_KEY`

## Output

Runtime files are written to:

- `output/` for generated CSV, XLSX, JSON, screenshots, and landing files
- `uploads/` for user-uploaded tables
- `data/settings.json` for local settings and keys

These folders are ignored for GitHub publishing.

## GitHub publishing checklist

1. Verify the app starts with `python3 start.py`.
2. Do not commit `.venv/`, `venv/`, `output/`, `uploads/`, `.env`, or `data/settings.json`.
3. Add screenshots and examples without private client data.
4. Create a GitHub repository and push the cleaned project.

## Notes

OpenStreetMap/Nominatim is useful for lightweight worldwide discovery but often has fewer business contacts than commercial map APIs. For production-scale collection, use official paid API keys and follow each provider’s terms.
