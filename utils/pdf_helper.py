import re
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing, Line

def convert_markdown_to_pdf(md_text: str) -> BytesIO:
    """Converts tailored markdown resume into a beautifully styled PDF matching the user's styling instructions."""
    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=letter,
        leftMargin=54,  # 0.75 in margin
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )
    
    styles = getSampleStyleSheet()
    
    # Custom elegant styles matching user requests (compact formatting)
    title_style = ParagraphStyle(
        'ResumeTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1F3864'),  # Navy #1F3864
        spaceAfter=3,
        alignment=1  # Centered
    )
    
    contact_style = ParagraphStyle(
        'ResumeContact',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor('#595959'),  # Medium Gray #595959
        spaceAfter=10,
        alignment=1  # Centered
    )
    
    section_style = ParagraphStyle(
        'ResumeSection',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=11.5,
        leading=15,
        textColor=colors.HexColor('#1F3864'),  # Navy #1F3864
        spaceBefore=10,
        spaceAfter=2,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'ResumeBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=12.5,
        textColor=colors.HexColor('#333333'),  # Dark Gray #333333
        spaceAfter=2
    )
    
    bullet_style = ParagraphStyle(
        'ResumeBullet',
        parent=body_style,
        fontSize=9.5,
        leading=12.5,
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=1
    )
    
    job_left_style = ParagraphStyle(
        'JobLeft',
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#333333')
    )
    
    job_right_style = ParagraphStyle(
        'JobRight',
        fontName='Helvetica-Bold',
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor('#595959'),
        alignment=2  # Right-aligned
    )

    story = []
    lines = md_text.split('\n')
    
    after_title = False
    
    def clean_markdown(text):
        # Convert markdown bold/italics to HTML tags for Paragraph
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
        text = re.sub(r'_(.*?)_', r'<i>\1</i>', text)
        return text

    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # 1. Header (# RAMAN DEEP KUMAR)
        if line.startswith('# '):
            text = line[2:].strip().upper()
            story.append(Paragraph(clean_markdown(text), title_style))
            after_title = True
            continue
            
        # 2. Contact Info Line (follows Header)
        if after_title:
            story.append(Paragraph(clean_markdown(line), contact_style))
            after_title = False
            continue
            
        # 3. Section Headings (## Heading, ### Heading, or typical uppercase section names)
        is_heading = False
        heading_text = ""
        
        if line.startswith('## ') or line.startswith('### '):
            is_heading = True
            heading_text = re.sub(r'^#+\s*', '', line).strip()
        else:
            clean_line = line.strip('*').strip('_').strip('#').strip()
            upper_clean = clean_line.upper()
            sections_list = [
                "PROFESSIONAL SUMMARY", "SUMMARY", "PROFESSIONAL EXPERIENCE", "EXPERIENCE", 
                "WORK EXPERIENCE", "EDUCATION", "CERTIFICATIONS", "TECHNICAL SKILLS", 
                "SKILLS", "CORE COMPETENCIES", "SUMMARY OF QUALIFICATIONS", "QUALIFICATIONS",
                "ADDITIONAL INFORMATION", "PROJECTS", "LANGUAGES", "CORE SKILLS"
            ]
            if upper_clean in sections_list:
                is_heading = True
                heading_text = clean_line
                
        if is_heading:
            text = heading_text.upper()
            story.append(Paragraph(clean_markdown(text), section_style))
            # Thin navy bottom rule/border
            story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#1F3864'), spaceBefore=2, spaceAfter=8))
            continue
            
        # 4. Job Title / Experience Header lines
        # Check if this line looks like an experience heading containing dates
        date_match = re.search(r'[\s|]*[\*\(_]+(19\d{2}|20\d{2})[\s\–\-—]+(Present|19\d{2}|20\d{2})[\*\)_]*\s*$', line)
        if not date_match:
            date_match = re.search(r'[\s|]*[\*\(_]+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}|19\d{2}|20\d{2})[\s\–\-—]+(Present|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}|19\d{2}|20\d{2})[\*\)_]*\s*$', line, re.IGNORECASE)
            
        if date_match:
            date_str = date_match.group(0).strip()
            clean_date = date_str.strip('|').strip().strip('*').strip('_').strip('(').strip(')')
            left_content = line[:date_match.start()].strip().rstrip('|').strip()
            
            # Create a 2-column table: Left for Job & Company, Right for Date
            left_p = Paragraph(clean_markdown(left_content), job_left_style)
            right_p = Paragraph(clean_markdown(clean_date), job_right_style)
            
            t = Table([[left_p, right_p]], colWidths=[380, 124])
            t.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 1),
                ('TOPPADDING', (0,0), (-1,-1), 2),
            ]))
            story.append(t)
            continue
            
        # 5. Bullet items
        if line.startswith('- ') or line.startswith('* '):
            text = line[2:].strip()
            bullet_text = f"&bull; {clean_markdown(text)}"
            story.append(Paragraph(bullet_text, bullet_style))
            continue
            
        # 6. Body lines
        story.append(Paragraph(clean_markdown(line), body_style))
        
    doc.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer
