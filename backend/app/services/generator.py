"""Stub PDF generator: produces a basic single-page ReportLab PDF from ResumeContent."""

import io

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.models.content import ResumeContent


def generate_pdf(content: ResumeContent) -> bytes:
    """Build a simple single-page PDF that lays out all ResumeContent fields as text.

    This is a stub implementation — the real hybrid generator (Phase 4.a) will
    overlay text on a template background image.  For now this is enough to
    prove the endpoint contract works and produces a valid PDF.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.5 * inch)

    styles = getSampleStyleSheet()
    name_style = ParagraphStyle(
        "Name", parent=styles["Title"], fontSize=20, spaceAfter=4, leading=24
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["Normal"], fontSize=12, spaceAfter=2, leading=14, textColor="#555555"
    )
    heading_style = ParagraphStyle(
        "SectionHeading", parent=styles["Heading2"], fontSize=13, spaceBefore=12, spaceAfter=4
    )
    body_style = styles["Normal"]
    bullet_style = ParagraphStyle("Bullet", parent=body_style, leftIndent=18, bulletIndent=6)

    story: list[object] = []

    story.append(Paragraph(_esc(content.name), name_style))
    if content.title:
        story.append(Paragraph(_esc(content.title), subtitle_style))

    contact_parts: list[str] = []
    if content.contact.email:
        contact_parts.append(content.contact.email)
    if content.contact.phone:
        contact_parts.append(content.contact.phone)
    if content.contact.location:
        contact_parts.append(content.contact.location)
    if content.contact.linkedin:
        contact_parts.append(content.contact.linkedin)
    if content.contact.github:
        contact_parts.append(content.contact.github)
    if content.contact.website:
        contact_parts.append(content.contact.website)
    if contact_parts:
        story.append(Paragraph(_esc(" | ".join(contact_parts)), body_style))
        story.append(Spacer(1, 6))

    if content.summary:
        story.append(Paragraph("<b>Summary</b>", heading_style))
        story.append(Paragraph(_esc(content.summary), body_style))

    if content.experience:
        story.append(Paragraph("<b>Experience</b>", heading_style))
        for exp in content.experience:
            story.append(
                Paragraph(f"<b>{_esc(exp.title)}</b> — {_esc(exp.company)}  ({_esc(exp.dates)})", body_style)
            )
            for bullet in exp.bullets:
                story.append(Paragraph(f"• {_esc(bullet)}", bullet_style))
            story.append(Spacer(1, 4))

    if content.education:
        story.append(Paragraph("<b>Education</b>", heading_style))
        for edu in content.education:
            line = f"<b>{_esc(edu.degree)}</b> — {_esc(edu.school)}  ({_esc(edu.dates)})"
            if edu.gpa:
                line += f"  GPA: {_esc(edu.gpa)}"
            story.append(Paragraph(line, body_style))
            for bullet in edu.bullets:
                story.append(Paragraph(f"• {_esc(bullet)}", bullet_style))
            story.append(Spacer(1, 4))

    if content.skills:
        story.append(Paragraph("<b>Skills</b>", heading_style))
        for skill in content.skills:
            story.append(
                Paragraph(f"<b>{_esc(skill.category)}:</b> {_esc(', '.join(skill.items))}", body_style)
            )

    if content.projects:
        story.append(Paragraph("<b>Projects</b>", heading_style))
        for proj in content.projects:
            header = f"<b>{_esc(proj.name)}</b>"
            if proj.dates:
                header += f"  ({_esc(proj.dates)})"
            story.append(Paragraph(header, body_style))
            for bullet in proj.bullets:
                story.append(Paragraph(f"• {_esc(bullet)}", bullet_style))
            story.append(Spacer(1, 4))

    doc.build(story)
    return buf.getvalue()


def _esc(text: str) -> str:
    """Escape XML-special characters for ReportLab Paragraph markup."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
