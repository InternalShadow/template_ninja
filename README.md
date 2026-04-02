# Resume Style Builder

A web-only tool that extracts styles and a TemplateBlueprint from resume templates (PDF, DOCX, DOC) and generates a structured PDF that matches the template layout and visual system.

## Features

- **Style + blueprint extraction** from PDF/DOCX/DOC templates
- **Template storage** with per-template metadata
- **Structured builder UI** with blueprint-driven styling hints
- **PDF generation** via the blueprint-driven builder
- **Fallback analysis** when a blueprint is missing or fails to extract

## Installation

1. Clone or download this repository
2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### Starting the Web Application

```bash
python app.py
```

The application will start on `http://localhost:5000`

### Using the Application

1. **Upload a Template**
   - Drag and drop a resume file (PDF, DOCX, or DOC)
   - Optionally provide a template name

2. **Open the Builder**
   - Click the template's "Build" action from the main list

3. **Fill Structured Content**
   - Enter your resume data in the structured builder fields
   - Use the visual preview and styling hints to guide edits

4. **Download the PDF**
   - Generate a blueprint-driven PDF that mirrors the template layout

## Project Structure

```text
resume-style-builder/
├── app.py                      # Flask web application
├── requirements.txt            # Python dependencies
├── README.md                   # This file
├── parsers/
│   ├── __init__.py
│   ├── docx_parser.py         # DOCX style extraction
│   ├── pdf_parser.py          # PDF style extraction
│   ├── template_blueprint.py  # TemplateBlueprint extraction
│   └── template_analyzer.py   # Fallback analyzer
├── generator/
│   ├── __init__.py
│   └── pdf_builder.py         # Blueprint-driven PDF generator
├── storage/
│   ├── __init__.py
│   └── template_storage.py    # Template storage management
├── templates/
│   ├── index.html             # Main page template
│   └── builder.html           # Structured builder UI
├── resume-styles-to-copy-tests/ # Reference templates used for accuracy checks
├── templates_store/            # Stored template data (tracked)
├── uploads/                    # Temporary upload storage (auto-created)
└── output/                     # Generated resumes (tracked)
```

## API Endpoints

- `GET /` - Main page
- `POST /upload` - Upload and extract styles/blueprint from a resume
- `GET /templates` - List all stored templates
- `GET /templates/<id>` - Get template details
- `DELETE /templates/<id>` - Delete a template
- `GET /build/<id>` - Open the structured builder UI
- `GET /source-pdf/<id>` - Serve the original template PDF
- `GET /blueprint/<id>` - Fetch the template blueprint
- `POST /blueprint/<id>` - Update the template blueprint
- `POST /blueprint/<id>/extract` - Re-extract the blueprint from source PDF
- `POST /generate-structured/<id>` - Generate a PDF from structured content

## Fixtures and Reference Assets

These directories are intentionally tracked to support accuracy checks and visual comparisons:

- `resume-styles-to-copy-tests/` contains reference PDFs to match.
- `templates_store/` stores extracted template data and blueprints.
- `output/` contains generated PDFs used for regression/accuracy comparison.

## Customization

- Update extraction logic in `parsers/docx_parser.py` and `parsers/pdf_parser.py`.
- Blueprint extraction lives in `parsers/template_blueprint.py`.
- PDF generation logic lives in `generator/pdf_builder.py`.
- Builder UI and structured content model are in `templates/builder.html`.

## Troubleshooting

### Import Errors

If you see import errors, ensure all dependencies are installed:

```bash
pip install -r requirements.txt
```

### File Upload Issues

- Maximum file size: 16MB
- Supported formats: PDF, DOCX, DOC
- Ensure files are not corrupted

### Generation Errors

- Ensure template data is valid
- Check console output for detailed error messages

## Development

### Running in Debug Mode

The application runs in debug mode by default. For production:

```python
app.run(debug=False, host='0.0.0.0', port=5000)
```

## License

This project is open source and available for personal and commercial use.
