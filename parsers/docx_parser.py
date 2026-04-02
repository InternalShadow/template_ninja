"""
DOCX Parser - Extracts styles from Microsoft Word documents
"""

import docx
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE

class DocxParser:
    """Parser for extracting styles from DOCX files"""
    
    def __init__(self):
        self.styles = {
            'document': {},
            'paragraphs': [],
            'sections': [],
            'fonts': {},
            'colors': {},
            'spacing': {}
        }
    
    def extract_styles(self, filepath):
        """Extract all styles from a DOCX file"""
        doc = docx.Document(filepath)
        
        # Extract document-level styles
        self._extract_document_styles(doc)
        
        # Extract section styles
        self._extract_section_styles(doc)
        
        # Extract paragraph styles
        self._extract_paragraph_styles(doc)
        
        # Extract character styles
        self._extract_character_styles(doc)
        
        # Extract default styles
        self._extract_default_styles(doc)
        
        return self.styles
    
    def _extract_document_styles(self, doc):
        """Extract document-level properties"""
        try:
            core_props = doc.core_properties
            self.styles['document'] = {
                'title': core_props.title or '',
                'author': core_props.author or '',
                'subject': core_props.subject or '',
                'created': str(core_props.created) if core_props.created else '',
                'modified': str(core_props.modified) if core_props.modified else ''
            }
        except:
            self.styles['document'] = {}
    
    def _extract_section_styles(self, doc):
        """Extract section/page layout styles"""
        for i, section in enumerate(doc.sections):
            section_style = {
                'index': i,
                'page_width': float(section.page_width.inches) if section.page_width else 8.5,
                'page_height': float(section.page_height.inches) if section.page_height else 11.0,
                'top_margin': float(section.top_margin.inches) if section.top_margin else 1.0,
                'bottom_margin': float(section.bottom_margin.inches) if section.bottom_margin else 1.0,
                'left_margin': float(section.left_margin.inches) if section.left_margin else 1.0,
                'right_margin': float(section.right_margin.inches) if section.right_margin else 1.0,
                'orientation': section.orientation
            }
            self.styles['sections'].append(section_style)
    
    def _extract_paragraph_styles(self, doc):
        """Extract paragraph-level styles"""
        for i, para in enumerate(doc.paragraphs):
            if not para.text.strip():
                continue
            
            para_style = {
                'index': i,
                'text': para.text[:100] + '...' if len(para.text) > 100 else para.text,
                'style_name': para.style.name if para.style else 'Normal',
                'alignment': self._get_alignment(para.alignment),
                'runs': []
            }
            
            # Extract run-level formatting
            for run in para.runs:
                run_style = self._extract_run_style(run)
                para_style['runs'].append(run_style)
            
            # Extract paragraph formatting
            if para.paragraph_format:
                pf = para.paragraph_format
                para_style['formatting'] = {
                    'space_before': float(pf.space_before.pt) if pf.space_before else 0,
                    'space_after': float(pf.space_after.pt) if pf.space_after else 0,
                    'line_spacing': float(pf.line_spacing) if pf.line_spacing else 1.0,
                    'first_line_indent': float(pf.first_line_indent.inches) if pf.first_line_indent else 0,
                    'left_indent': float(pf.left_indent.inches) if pf.left_indent else 0,
                    'right_indent': float(pf.right_indent.inches) if pf.right_indent else 0
                }
            
            self.styles['paragraphs'].append(para_style)
    
    def _extract_run_style(self, run):
        """Extract character-level formatting from a run"""
        style = {
            'text': run.text[:50] + '...' if len(run.text) > 50 else run.text,
            'font_name': run.font.name if run.font.name else None,
            'font_size': float(run.font.size.pt) if run.font.size else None,
            'bold': run.font.bold if run.font.bold is not None else False,
            'italic': run.font.italic if run.font.italic is not None else False,
            'underline': run.font.underline if run.font.underline is not None else False,
            'color': self._get_color(run.font.color),
            'highlight_color': str(run.font.highlight_color) if run.font.highlight_color else None
        }
        
        # Track unique fonts and colors
        if style['font_name']:
            self.styles['fonts'][style['font_name']] = True
        if style['color']:
            self.styles['colors'][style['color']] = True
        
        return style
    
    def _extract_character_styles(self, doc):
        """Extract character styles from the document"""
        try:
            for style in doc.styles:
                if style.type == WD_STYLE_TYPE.CHARACTER:
                    style_info = {
                        'name': style.name,
                        'font_name': style.font.name if style.font.name else None,
                        'font_size': float(style.font.size.pt) if style.font.size else None,
                        'bold': style.font.bold if style.font.bold is not None else False,
                        'italic': style.font.italic if style.font.italic is not None else False,
                        'color': self._get_color(style.font.color)
                    }
                    if 'character_styles' not in self.styles:
                        self.styles['character_styles'] = []
                    self.styles['character_styles'].append(style_info)
        except:
            pass
    
    def _extract_default_styles(self, doc):
        """Extract default font and style settings"""
        try:
            default_style = doc.styles['Normal']
            self.styles['default'] = {
                'font_name': default_style.font.name if default_style.font.name else 'Calibri',
                'font_size': float(default_style.font.size.pt) if default_style.font.size else 11.0,
                'color': self._get_color(default_style.font.color)
            }
        except:
            self.styles['default'] = {
                'font_name': 'Calibri',
                'font_size': 11.0,
                'color': '#000000'
            }
    
    def _get_alignment(self, alignment):
        """Convert alignment enum to string"""
        alignment_map = {
            WD_ALIGN_PARAGRAPH.LEFT: 'left',
            WD_ALIGN_PARAGRAPH.CENTER: 'center',
            WD_ALIGN_PARAGRAPH.RIGHT: 'right',
            WD_ALIGN_PARAGRAPH.JUSTIFY: 'justify'
        }
        return alignment_map.get(alignment, 'left')
    
    def _get_color(self, color):
        """Extract color value from color object"""
        if not color or not color.rgb:
            return None
        try:
            rgb = color.rgb
            return f'#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}'
        except:
            return None
