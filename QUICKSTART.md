# Quick Start Guide

## Installation

1. Install Python dependencies:

```bash
pip install -r requirements.txt
```

The project now uses:

- **PyMuPDF (fitz)** - Advanced PDF layout extraction
- **pdfplumber** - Text extraction
- **python-docx** - DOCX handling
- **reportlab** - PDF generation

## Running the Web Application

1. Start the Flask server:

```bash
python app.py
```

1. Open your browser and navigate to:

```text
http://localhost:5000
```

## Using the Web Interface

### Upload a Template

1. Drag and drop a resume file (PDF, DOCX, or DOC) onto the upload area
1. Or click to browse and select a file
1. Optionally enter a template name
1. Click "Extract Styles"

### Build a Resume

1. Click "Build" on any stored template
1. Fill in your information in the structured builder panel
1. Use the preview and styling hints for guidance
1. Generate the PDF when ready

### Download Your Resume

1. Click "Download Resume"
1. Your formatted resume will be downloaded

## File Structure

```text
resume-style-builder/
├── app.py                      # Web application
├── requirements.txt            # Python dependencies
├── parsers/                    # Style extraction modules
│   ├── pdf_parser.py          # PDF style extraction
│   └── docx_parser.py         # DOCX style extraction
├── generator/                  # Resume generation modules
├── storage/                    # Template storage modules
├── templates/                  # Web interface templates
├── resume-styles-to-copy-tests/ # Reference PDFs for accuracy checks
├── templates_store/            # Stored templates (tracked)
├── uploads/                    # Upload storage (auto-created)
└── output/                     # Generated resumes (tracked)
```

## Workflow

### 1. Extract Template Styles

Upload a resume PDF/DOCX to extract its styling (fonts, colors, layout, margins).

### 2. Build Content

Use the structured builder to enter your resume content and adjust labels.

### 3. Generate Output

Generate a blueprint-driven PDF from the structured content.

### 4. Compare Results

Compare the generated PDF against the reference templates and prior outputs.

## Troubleshooting

### Import Errors

If you see import errors, ensure all dependencies are installed:

```bash
pip install -r requirements.txt
```

### Port Already in Use

If port 5000 is already in use, modify the port in `app.py`:

```python
app.run(debug=True, host='0.0.0.0', port=8080)  # Change to desired port
```

### File Upload Issues

- Maximum file size: 16MB
- Supported formats: PDF, DOCX, DOC
- Ensure files are not corrupted
