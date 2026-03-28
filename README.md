# LLM Research Report MVP

This is a local MVP that generates an equity research-style report for a JP stock code using GPT, SERP, EDINET, and J-Quants APIs. The output is HTML and (optionally) PDF via Playwright.

## Quick Start

1. Create a local `.env` based on `.env.example` and add your API keys.
2. Install dependencies.
3. Run the app.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000` in your browser.

## Notes

- PDF rendering requires Playwright and a browser install (`playwright install`).
- If PDF rendering fails, the HTML report is still generated in `output/`.
- Adjust SERP and J-Quants endpoints in `.env` if your provider uses different routes.

## Structure

- `app/main.py`: FastAPI app
- `app/services/`: API adapters + report generator
- `app/templates/`: HTML templates
- `app/static/`: CSS
- `output/`: generated reports

## Front-end Renovation Notes (2026-02)

- Visual redesign with premium fintech styling, light/dark theme toggle, sticky nav, and ticker chips for quick entry.
- Live report writer: simulates AI typing when a job finishes, with pause/resume, skip animation, copy-per-section, TOC highlighting, and optional auto-scroll.
- Skeleton loaders, animated progress, and refreshed loading overlay; no backend changes or new endpoints.
- Metrics header auto-populates from the generated report HTML; streaming uses only existing backend outputs.
- Run: `uvicorn app.main:app --host 127.0.0.1 --port 8000` from the repo root, then open `http://127.0.0.1:8000`.
