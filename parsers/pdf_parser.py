"""
PDF Parser - Extracts styles from PDF documents
"""

import pdfplumber
import PyPDF2
import io
import re
from collections import defaultdict

class PdfParser:
    """Parser for extracting styles from PDF files"""
    
    def __init__(self):
        self.styles = {
            'document': {},
            'pages': [],
            'fonts': {},
            'colors': {},
            'spacing': {},
            'paragraphs': [],
            'sections': [],
            'default': {}
        }
    
    def extract_styles(self, filepath):
        """Extract all styles from a PDF file"""
        # Use pdfplumber for detailed text extraction
        with pdfplumber.open(filepath) as pdf:
            self._extract_document_info(pdf)
            self._extract_page_styles(pdf)
            self._extract_text_styles(pdf)
            self._extract_layout_info(pdf)
        
        # Use PyPDF2 for metadata
        self._extract_metadata(filepath)
        
        # Set default styles based on extracted information
        self._set_default_styles()
        
        return self.styles
    
    def _extract_document_info(self, pdf):
        """Extract document-level information"""
        self.styles['document'] = {
            'page_count': len(pdf.pages),
            'metadata': pdf.metadata or {}
        }
    
    def _extract_metadata(self, filepath):
        """Extract PDF metadata using PyPDF2"""
        try:
            with open(filepath, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                metadata = reader.metadata
                if metadata:
                    self.styles['document']['title'] = metadata.get('/Title', '')
                    self.styles['document']['author'] = metadata.get('/Author', '')
                    self.styles['document']['subject'] = metadata.get('/Subject', '')
                    self.styles['document']['creator'] = metadata.get('/Creator', '')
                    self.styles['document']['producer'] = metadata.get('/Producer', '')
        except:
            pass
    
    def _extract_page_styles(self, pdf):
        """Extract page layout styles"""
        for i, page in enumerate(pdf.pages):
            page_style = {
                'index': i,
                'width': float(page.width) if page.width else 612.0,
                'height': float(page.height) if page.height else 792.0,
                'rotation': page.rotation if page.rotation else 0
            }
            
            # Extract margins by analyzing content bounds
            try:
                words = page.extract_words()
                if words:
                    # Find content bounds
                    min_x = min(word['x0'] for word in words)
                    max_x = max(word['x1'] for word in words)
                    min_y = min(word['top'] for word in words)
                    max_y = max(word['bottom'] for word in words)
                    
                    # Calculate margins
                    page_style['margins'] = {
                        'top': min_y,
                        'bottom': page.height - max_y if page.height else 792.0 - max_y,
                        'left': min_x,
                        'right': page.width - max_x if page.width else 612.0 - max_x
                    }
            except:
                # Fallback to default margins
                page_style['margins'] = {
                    'top': 72.0,
                    'bottom': 72.0,
                    'left': 72.0,
                    'right': 72.0
                }
            
            self.styles['pages'].append(page_style)
    
    def _extract_text_styles(self, pdf):
        """Extract text and font styles from PDF"""
        font_sizes = []
        font_names = []
        colors = []
        
        for page in pdf.pages:
            # Extract text with formatting information
            text = page.extract_text()
            if text:
                # Analyze text for common patterns
                lines = text.split('\n')
                for line in lines:
                    if line.strip():
                        # Detect potential headings (all caps, short lines)
                        if line.isupper() and len(line) < 50:
                            self._add_text_style('heading', line)
                        # Detect potential bullet points
                        elif line.strip().startswith(('•', '-', '*', '○')):
                            self._add_text_style('bullet', line)
                        # Detect potential contact info
                        elif any(keyword in line.lower() for keyword in ['email', 'phone', 'address', 'linkedin']):
                            self._add_text_style('contact', line)
            
            # Try to extract detailed font information from page objects
            try:
                if hasattr(page, 'page_object'):
                    page_obj = page.page_object
                    if '/Font' in page_obj:
                        fonts = page_obj['/Font']
                        for font_name, font_obj in fonts.items():
                            font_names.append(font_name)
                            
                            # Try to get font details
                            if hasattr(font_obj, 'get_object'):
                                font_dict = font_obj.get_object()
                                if '/BaseFont' in font_dict:
                                    base_font = font_dict['/BaseFont']
                                    if base_font:
                                        self.styles['fonts'][font_name] = {
                                            'name': str(base_font),
                                            'type': str(font_dict.get('/Subtype', ''))
                                        }
            except:
                pass
            
            # Extract text with detailed formatting using pdfplumber's advanced features
            try:
                # Get text with character-level details
                chars = page.chars
                if chars:
                    for char in chars:
                        # Extract font information
                        if 'fontname' in char:
                            font_names.append(char['fontname'])
                        if 'size' in char:
                            font_sizes.append(char['size'])
                        if 'non_stroking_color' in char:
                            color = char['non_stroking_color']
                            if color:
                                colors.append(color)
            except:
                pass
        
        # Store detected font information
        if font_names:
            # Normalize font names: remove PostScript prefix (e.g., "AAAAAA+ClearSans" -> "ClearSans")
            normalized_fonts = []
            for font in font_names:
                if '+' in font:
                    # Extract the actual font name after the plus sign
                    normalized = font.split('+')[-1]
                    normalized_fonts.append(normalized)
                else:
                    normalized_fonts.append(font)
            
            unique_fonts = list(set(normalized_fonts))
            self.styles['fonts']['detected'] = unique_fonts
            # Store original font names too
            self.styles['fonts']['original'] = list(set(font_names))
            
            # Try to identify primary font
            if unique_fonts:
                # Use the most common font as default
                font_counts = defaultdict(int)
                for font in normalized_fonts:
                    font_counts[font] += 1
                primary_font = max(font_counts.items(), key=lambda x: x[1])[0]
                self.styles['fonts']['primary'] = primary_font
        
        # Store detected font sizes
        if font_sizes:
            unique_sizes = sorted(list(set(font_sizes)))
            self.styles['fonts']['sizes'] = unique_sizes
            
            # Estimate font size categories
            if len(unique_sizes) >= 3:
                self.styles['fonts']['estimated_sizes'] = {
                    'heading': unique_sizes[-1],  # Largest
                    'subheading': unique_sizes[-2] if len(unique_sizes) > 1 else unique_sizes[-1],
                    'body': unique_sizes[len(unique_sizes)//2],  # Middle
                    'small': unique_sizes[0]  # Smallest
                }
            else:
                self.styles['fonts']['estimated_sizes'] = {
                    'heading': 16,
                    'subheading': 14,
                    'body': 11,
                    'small': 9
                }
        
        # Store detected colors
        if colors:
            unique_colors = list(set(str(c) for c in colors))
            self.styles['colors']['detected'] = unique_colors
            
            # Try to identify primary color
            if colors:
                color_counts = defaultdict(int)
                for color in colors:
                    color_counts[str(color)] += 1
                primary_color = max(color_counts.items(), key=lambda x: x[1])[0]
                self.styles['colors']['primary'] = primary_color
    
    def _extract_layout_info(self, pdf):
        """Extract detailed layout information from PDF"""
        layout = {
            'columns': 1,
            'sections': [],
            'spacing': {},
            'alignment': 'left',
            'borders': {
                'style': 'none',
                'color': '#000000',
                'width': 0
            }
        }
        
        for page in pdf.pages:
            # Detect column layout by analyzing text blocks
            text_blocks = page.extract_words()
            if text_blocks:
                # Group text blocks by x-position to detect columns
                x_positions = defaultdict(list)
                for block in text_blocks:
                    x = round(block['x0'] / 10) * 10  # Round to nearest 10
                    x_positions[x].append(block)
                
                # If multiple distinct x-positions with content, likely multi-column
                if len(x_positions) > 2:
                    layout['columns'] = max(layout['columns'], len(x_positions) // 2)
                
                # Detect text alignment
                left_margins = [block['x0'] for block in text_blocks]
                if left_margins:
                    avg_left = sum(left_margins) / len(left_margins)
                    if avg_left < 100:
                        layout['alignment'] = 'left'
                    elif avg_left > 200:
                        layout['alignment'] = 'right'
                    else:
                        layout['alignment'] = 'center'
            
            # Detect sections by analyzing vertical spacing
            words = page.extract_words()
            if words:
                # Sort by vertical position
                words.sort(key=lambda w: w['top'])
                
                # Find gaps that indicate section breaks
                prev_bottom = 0
                section_gaps = []
                for word in words:
                    gap = word['top'] - prev_bottom
                    if gap > 30:  # Significant gap
                        layout['sections'].append({
                            'y_position': word['top'],
                            'gap': gap
                        })
                        section_gaps.append(gap)
                    prev_bottom = word['bottom']
                
                # Calculate average spacing
                if section_gaps:
                    layout['spacing']['section'] = sum(section_gaps) / len(section_gaps)
                else:
                    layout['spacing']['section'] = 20  # Default
                
                # Calculate line spacing from text blocks
                if text_blocks:
                    line_heights = []
                    for block in text_blocks:
                        if 'height' in block:
                            line_heights.append(block['height'])
                    if line_heights:
                        layout['spacing']['line'] = sum(line_heights) / len(line_heights)
                    else:
                        layout['spacing']['line'] = 12  # Default
            
            # Extract line drawings and rectangles (for borders)
            try:
                lines = page.lines
                if lines:
                    layout['lines'] = len(lines)
                    # Detect border style from lines
                    if len(lines) > 0:
                        # Check if lines form a rectangle
                        x_coords = []
                        y_coords = []
                        for line in lines:
                            if 'x0' in line and 'x1' in line:
                                x_coords.extend([line['x0'], line['x1']])
                            if 'y0' in line and 'y1' in line:
                                y_coords.extend([line['y0'], line['y1']])
                        
                        # If we have lines that form a rectangle, it's likely a border
                        if len(set(x_coords)) <= 2 and len(set(y_coords)) <= 2:
                            layout['borders']['style'] = 'solid'
                            layout['borders']['width'] = 1
                
                rects = page.rects
                if rects:
                    layout['rectangles'] = len(rects)
                    # Use rectangles to determine border style
                    if len(rects) > 0:
                        layout['borders']['style'] = 'solid'
                        # Try to get border width from first rectangle
                        if rects and 'linewidth' in rects[0]:
                            layout['borders']['width'] = rects[0]['linewidth']
            except:
                pass
        
        self.styles['layout'] = layout
        
        # Create sections based on detected gaps
        if layout['sections']:
            for i, section in enumerate(layout['sections']):
                self.styles['sections'].append({
                    'index': i,
                    'top_margin': section['y_position'],
                    'spacing': section['gap']
                })
        
        # Store spacing information
        self.styles['spacing'] = layout['spacing']
        
        # Store border information
        self.styles['borders'] = layout['borders']
    
    def _add_text_style(self, style_type, text):
        """Add a detected text style to the styles dictionary"""
        if 'text_styles' not in self.styles:
            self.styles['text_styles'] = {}
        
        if style_type not in self.styles['text_styles']:
            self.styles['text_styles'][style_type] = []
        
        self.styles['text_styles'][style_type].append(text[:100])
    
    def _set_default_styles(self):
        """Set default styles based on extracted information"""
        # Set default font - use normalized primary font
        if 'primary' in self.styles['fonts']:
            # The primary font is already normalized from _extract_text_styles
            font_name = self.styles['fonts']['primary']
            # Map custom fonts to standard available fonts
            self.styles['default']['font_name'] = self._map_font_to_available(font_name)
        elif 'detected' in self.styles['fonts'] and self.styles['fonts']['detected']:
            font_name = self.styles['fonts']['detected'][0]
            self.styles['default']['font_name'] = self._map_font_to_available(font_name)
        else:
            self.styles['default']['font_name'] = 'Helvetica'
        
        # Set default font size
        if 'estimated_sizes' in self.styles['fonts']:
            self.styles['default']['font_size'] = self.styles['fonts']['estimated_sizes'].get('body', 11)
        else:
            self.styles['default']['font_size'] = 11.0
        
        # Set default color - normalize RGB tuple to hex
        if 'primary' in self.styles['colors']:
            color = self.styles['colors']['primary']
            self.styles['default']['color'] = self._normalize_color(color)
        else:
            self.styles['default']['color'] = '#000000'
        
        # Set default margins from first page
        if self.styles['pages'] and 'margins' in self.styles['pages'][0]:
            margins = self.styles['pages'][0]['margins']
            self.styles['default']['margins'] = {
                'top': margins.get('top', 72.0) / 72.0,  # Convert to inches
                'bottom': margins.get('bottom', 72.0) / 72.0,
                'left': margins.get('left', 72.0) / 72.0,
                'right': margins.get('right', 72.0) / 72.0
            }
        else:
            self.styles['default']['margins'] = {
                'top': 1.0,
                'bottom': 1.0,
                'left': 1.0,
                'right': 1.0
            }
    
    def _map_font_to_available(self, font_name):
        """Map a custom font name to an available standard font"""
        # Common font mappings for PDF embedded fonts (ReportLab-compatible)
        font_mappings = {
            'ClearSans': 'Helvetica',
            'ClearSans-Bold': 'Helvetica-Bold',
            'ClearSans-Medium': 'Helvetica',
            'TrebuchetMS': 'Helvetica',
            'Helvetica': 'Helvetica',
            'Times': 'Times-Roman',
            'Courier': 'Courier',
            'Georgia': 'Helvetica',  # ReportLab doesn't have Georgia
            'Verdana': 'Helvetica',  # ReportLab doesn't have Verdana
            'Tahoma': 'Helvetica',   # ReportLab doesn't have Tahoma
            'Trebuchet': 'Helvetica',
            'Calibri': 'Helvetica',  # ReportLab doesn't have Calibri
            'Cambria': 'Helvetica',  # ReportLab doesn't have Cambria
            'Roboto': 'Helvetica',
            'OpenSans': 'Helvetica',
            'Lato': 'Helvetica',
            'Montserrat': 'Helvetica',
            'SourceSans': 'Helvetica',
            'FiraSans': 'Helvetica',
            'Ubuntu': 'Helvetica',
            'Arial': 'Helvetica',    # Use Helvetica as fallback
        }
        
        # Check if font_name contains any known font
        for known_font, mapped_font in font_mappings.items():
            if known_font.lower() in font_name.lower():
                return mapped_font
        
        # Default to Helvetica if no mapping found
        return 'Helvetica'
    
    def _normalize_color(self, color):
        """Normalize color to hex format"""
        if not color:
            return '#000000'
        
        # If already a hex color
        if isinstance(color, str) and color.startswith('#'):
            return color
        
        # If it's an RGB tuple string like "(0, 0, 0)"
        if isinstance(color, str) and color.startswith('('):
            try:
                rgb = eval(color)  # Convert string tuple to actual tuple
                r, g, b = rgb
                return f'#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'
            except:
                return '#000000'
        
        # If it's a tuple or list
        if isinstance(color, (tuple, list)):
            if len(color) == 3:
                # Assume RGB values are 0-1 range
                if all(0 <= c <= 1 for c in color):
                    r, g, b = color
                    return f'#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'
                # Assume RGB values are 0-255
                return f'#{color[0]:02x}{color[1]:02x}{color[2]:02x}'
        
        return '#000000'
