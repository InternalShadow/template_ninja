# Resume Style Builder

Extract visual styles from existing resume PDFs and generate new resumes that match those styles pixel-for-pixel.

## Architecture

```
resume-style-builder/
  backend/     # FastAPI – extraction, blueprint storage, PDF generation
  frontend/    # Next.js – template browser, blueprint editor, live preview
  data/        # Persisted data (templates, sample resumes, generated output)
```

## Quick Start

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs on `http://localhost:3000` and the API on `http://localhost:8000`.

## Data Directory

| Path | Contents |
|------|----------|
| `data/templates_store/` | Uploaded template PDFs, extracted blueprints, style metadata |
| `data/Test_with_user_data/` | Sample resume JSON for testing generation |
| `data/output/` | Previously generated reference PDFs |
