"""
Resume Style Builder - Main Application

Upload a PDF template → extract a TemplateBlueprint → generate a new PDF
from structured user content that faithfully reproduces the template's
visual structure and per-element styling.
"""
from __future__ import annotations

import os
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
from werkzeug.utils import secure_filename
from parsers.docx_parser import DocxParser
from parsers.pdf_parser import PdfParser
from storage.template_storage import TemplateStorage

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['TEMPLATES_FOLDER'] = 'templates_store'
app.config['OUTPUT_FOLDER'] = 'output'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['TEMPLATES_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

template_storage = TemplateStorage(app.config['TEMPLATES_FOLDER'])
docx_parser = DocxParser()
pdf_parser = PdfParser()

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc'}


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _find_source_pdf(template_id: str) -> str | None:
    template_dir = os.path.join('templates_store', template_id)
    for ext in ['.pdf', '.PDF']:
        path = os.path.join(template_dir, f'source{ext}')
        if os.path.exists(path):
            return path
    return None


def _extract_blueprint_safe(source_path: str) -> dict | None:
    """Run blueprint extraction; return None on any failure."""
    try:
        from parsers.template_blueprint import extract_blueprint
        return extract_blueprint(source_path)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    templates = template_storage.list_templates()
    return render_template('index.html', templates=templates)


# ---------------------------------------------------------------------------
# Upload — extract blueprint immediately after saving
# ---------------------------------------------------------------------------

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: pdf, docx, doc'}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    try:
        file_ext = filename.rsplit('.', 1)[1].lower()

        if file_ext in ['docx', 'doc']:
            styles = docx_parser.extract_styles(filepath)
            blueprint = None
        elif file_ext == 'pdf':
            styles = pdf_parser.extract_styles(filepath)
            blueprint = _extract_blueprint_safe(filepath)
        else:
            return jsonify({'error': 'Unsupported file type'}), 400

        template_name = request.form.get('template_name', filename.rsplit('.', 1)[0])
        template_id = template_storage.save_template(
            template_name, styles, filepath, blueprint=blueprint
        )
        os.remove(filepath)

        return jsonify({
            'success': True,
            'template_id': template_id,
            'template_name': template_name,
            'has_blueprint': blueprint is not None,
            'message': f'Template "{template_name}" saved successfully',
        })

    except Exception as e:
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Template CRUD
# ---------------------------------------------------------------------------

@app.route('/templates')
def list_templates():
    return jsonify(template_storage.list_templates())


@app.route('/templates/<template_id>')
def get_template(template_id):
    template = template_storage.get_template(template_id)
    if not template:
        return jsonify({'error': 'Template not found'}), 404
    return jsonify(template)


@app.route('/templates/<template_id>', methods=['DELETE'])
def delete_template(template_id):
    success = template_storage.delete_template(template_id)
    if success:
        return jsonify({'success': True, 'message': 'Template deleted'})
    return jsonify({'error': 'Template not found'}), 404


# ---------------------------------------------------------------------------
# Blueprint endpoints
# ---------------------------------------------------------------------------

@app.route('/blueprint/<template_id>', methods=['GET'])
def get_blueprint(template_id):
    """Return the TemplateBlueprint JSON for review/editing."""
    if template_id not in template_storage.metadata:
        return jsonify({'error': 'Template not found'}), 404

    blueprint = template_storage.get_blueprint(template_id)
    if blueprint is None:
        # Try to extract on-demand if source PDF is available
        source_path = _find_source_pdf(template_id)
        if source_path:
            blueprint = _extract_blueprint_safe(source_path)
            if blueprint:
                template_storage.save_blueprint(template_id, blueprint)

    if blueprint is None:
        return jsonify({'error': 'No blueprint available for this template'}), 404

    return jsonify(blueprint)


@app.route('/blueprint/<template_id>', methods=['POST'])
def update_blueprint(template_id):
    """
    Accept user corrections to the blueprint and persist them.

    Body: the full or partial TemplateBlueprint JSON.
    If the body contains only 'element_styles' or 'section_map' keys,
    those are merged into the existing blueprint rather than replacing it.
    """
    if template_id not in template_storage.metadata:
        return jsonify({'error': 'Template not found'}), 404

    payload = request.get_json()
    if not payload or not isinstance(payload, dict):
        return jsonify({'error': 'Invalid JSON payload'}), 400

    existing = template_storage.get_blueprint(template_id) or {}

    # Merge: if only corrections keys are sent, merge them in
    correction_keys = {'element_styles', 'section_map', 'skill_format',
                       'job_entry_format', 'job_body_format',
                       'layout_type', 'columns'}
    if payload.keys() <= correction_keys:
        existing.update(payload)
        blueprint = existing
    else:
        blueprint = payload

    template_storage.save_blueprint(template_id, blueprint)
    return jsonify({'success': True, 'message': 'Blueprint updated'})


# ---------------------------------------------------------------------------
# Re-extract blueprint for an existing template
# ---------------------------------------------------------------------------

@app.route('/blueprint/<template_id>/extract', methods=['POST'])
def reextract_blueprint(template_id):
    """Force re-extraction of the blueprint from the stored source PDF."""
    if template_id not in template_storage.metadata:
        return jsonify({'error': 'Template not found'}), 404

    source_path = _find_source_pdf(template_id)
    if not source_path:
        return jsonify({'error': 'No source PDF available for this template'}), 400

    blueprint = _extract_blueprint_safe(source_path)
    if blueprint is None:
        return jsonify({'error': 'Blueprint extraction failed'}), 500

    template_storage.save_blueprint(template_id, blueprint)
    return jsonify({'success': True, 'blueprint': blueprint})


# ---------------------------------------------------------------------------
# Builder UI
# ---------------------------------------------------------------------------

@app.route('/build/<template_id>')
def build_resume(template_id):
    """Render the structured builder UI for a template."""
    template = template_storage.get_template(template_id)
    if not template:
        return redirect(url_for('index'))

    # Build a simple CSS preview from the blueprint (or legacy theme)
    blueprint = template_storage.get_blueprint(template_id)
    theme_css: dict = {}
    if blueprint:
        theme_css = _blueprint_to_css(blueprint)
    else:
        source_path = _find_source_pdf(template_id)
        if source_path:
            try:
                from parsers.template_analyzer import analyze, theme_to_css
                theme = analyze(source_path)
                theme_css = theme_to_css(theme)
            except Exception:
                pass

    return render_template(
        'builder.html',
        template=template,
        template_id=template_id,
        theme_css=theme_css,
        has_blueprint=blueprint is not None,
    )


def _blueprint_to_css(blueprint: dict) -> dict:
    """Convert a blueprint to basic CSS hints for builder.html preview."""
    es = blueprint.get("element_styles", {})
    css: dict = {}

    def _rgb_css(color: list | None) -> str:
        if not color or len(color) < 3:
            return "#000000"
        r, g, b = int(color[0] * 255), int(color[1] * 255), int(color[2] * 255)
        return f"#{r:02x}{g:02x}{b:02x}"

    # Name style
    name_es = es.get("name", {})
    if name_es:
        css["name_color"] = _rgb_css(name_es.get("color"))
        css["name_size"] = f"{name_es.get('size', 22)}px"

    # Section heading style
    hdg_es = es.get("section_heading", {})
    if hdg_es:
        bg = hdg_es.get("bg_color")
        css["heading_bg"] = _rgb_css(bg) if bg else "transparent"
        css["heading_color"] = _rgb_css(hdg_es.get("color"))
        css["heading_size"] = f"{hdg_es.get('size', 10)}px"

    # Body paragraph
    body_es = es.get("body_paragraph", {})
    if body_es:
        css["body_color"] = _rgb_css(body_es.get("color"))
        css["body_size"] = f"{body_es.get('size', 9.5)}px"

    # Background panels
    bg_regions = blueprint.get("background_regions", [])
    if bg_regions:
        # Use the largest region's color as the accent color
        biggest = max(bg_regions, key=lambda r: r.get("width", 0) * r.get("height", 0))
        css["accent_color"] = _rgb_css(biggest.get("color"))

    return css


# ---------------------------------------------------------------------------
# Source PDF preview
# ---------------------------------------------------------------------------

@app.route('/source-pdf/<template_id>')
def serve_source_pdf(template_id):
    """Serve the original uploaded PDF so the browser can display it."""
    source_path = _find_source_pdf(template_id)
    if not source_path:
        return jsonify({'error': 'Source PDF not found'}), 404
    return send_file(source_path, mimetype='application/pdf')


# ---------------------------------------------------------------------------
# Generate structured PDF — blueprint-driven
# ---------------------------------------------------------------------------

@app.route('/generate-structured/<template_id>', methods=['POST'])
def generate_structured(template_id):
    """
    Accept structured resume content, apply the template blueprint, and return
    a freshly generated PDF that faithfully reproduces the template's visual
    structure and styling.

    Expected body: the JSON content model from builder.html:
    {
        "name": str,
        "title": str,          // job title / professional title
        "subtitle": str,       // alias for title
        "summary": str,
        "contact": {"email", "phone", "location", "linkedin", "github"},
        "skills": [{"category": str, "items": str}],
        "experience": [
            {"company": str, "role": str, "dates": str, "location": str,
             "bullets": [str], "description": str}
        ],
        "education": [{"degree": str, "school": str, "dates": str}],
        "projects": [{"name": str, "role": str, "dates": str, "bullets": [str]}],
        // Optional label overrides (use template's heading text if absent):
        "experience_label": str,
        "skills_label": str,
        "education_label": str,
        "summary_label": str,
    }
    """
    template = template_storage.get_template(template_id)
    if not template:
        return jsonify({'error': 'Template not found'}), 404

    try:
        content = request.get_json()
        if not content or not isinstance(content, dict):
            return jsonify({'error': 'Invalid JSON payload'}), 400

        # ── Load blueprint ─────────────────────────────────────────────────
        blueprint = template_storage.get_blueprint(template_id)

        if blueprint is None:
            # Try to extract from source PDF on-demand
            source_path = _find_source_pdf(template_id)
            if source_path:
                blueprint = _extract_blueprint_safe(source_path)
                if blueprint:
                    template_storage.save_blueprint(template_id, blueprint)

        if blueprint is None:
            # Last resort: use legacy thin-theme extraction or built-in defaults
            source_path = _find_source_pdf(template_id)
            if source_path:
                try:
                    from parsers.template_analyzer import analyze
                    blueprint = analyze(source_path)
                except Exception:
                    pass

        if blueprint is None:
            blueprint = _default_blueprint()

        # ── Generate PDF ───────────────────────────────────────────────────
        from generator.pdf_builder import PdfBuilder

        safe_name = template['name'].replace(' ', '_')
        output_filename = f"resume_{safe_name}.pdf"
        output_path = os.path.join('output', output_filename)
        os.makedirs('output', exist_ok=True)

        builder = PdfBuilder()
        builder.build(blueprint, content, output_path)

        return send_file(
            output_path,
            as_attachment=True,
            download_name=output_filename,
            mimetype='application/pdf',
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _default_blueprint() -> dict:
    """Minimal single-column blueprint used as a last-resort fallback."""
    from generator.pdf_builder import _theme_to_blueprint
    return _theme_to_blueprint({
        'header_bg': [0.2, 0.24, 0.31],
        'section_bg': [0.25, 0.3, 0.38],
        'header_text_color': [1.0, 1.0, 1.0],
        'body_text_color': [0.1, 0.1, 0.1],
        'name_font_size': 22.0,
        'heading_font_size': 10.5,
        'body_font_size': 9.5,
        'left_margin': 36.0,
        'right_margin': 36.0,
        'top_margin': 0.0,
        'bottom_margin': 28.0,
        'page_width': 612.0,
        'page_height': 792.0,
        'layout_type': 'single_column',
        'sidebar_width': 0.0,
        'sidebar_color': [0.2, 0.2, 0.2],
        'sidebar_side': None,
        'header_height': 60.0,
        'header_full_width': True,
        'section_bar_height': 16.0,
        'line_spacing': 13.3,
        'section_spacing': 6.0,
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
