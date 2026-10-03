"""PowerPoint (.pptx) and Word (.docx) -> the same slide list that pdf.py makes.

Each "slide" is {index, title, text, notes}:
  - text  = title on the first line, then one body line per bullet / table row
  - notes = speaker notes (PowerPoint only), kept apart from the slide text
"""
import io
import re

from docx import Document
from docx.table import Table
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER

from .pdf import SlidesError, split_sentences

# Placeholders that repeat on every slide and say nothing about the topic.
SKIP_PLACEHOLDERS = {PP_PLACEHOLDER.SLIDE_NUMBER, PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.DATE}
LONG_PARAGRAPH_WORDS = 25  # Word paragraphs longer than this are split into sentences
CHUNK_LINES = 8  # a Word file with no headings is cut into sections of this many lines


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# ---------- PowerPoint ----------

def _shape_lines(shape) -> list[str]:
    """All text in one shape: paragraphs, table rows, and shapes inside groups."""
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        return [line for inner in shape.shapes for line in _shape_lines(inner)]
    if getattr(shape, "has_table", False) and shape.has_table:
        rows = []
        for row in shape.table.rows:
            cells = [_clean(cell.text) for cell in row.cells]
            rows.append(" | ".join(cell for cell in cells if cell))
        return [row for row in rows if row]
    if shape.has_text_frame:
        lines = []
        for paragraph in shape.text_frame.paragraphs:
            # "\v" is a manual line break inside one paragraph.
            lines += [_clean(part) for part in re.split(r"[\v\n]", paragraph.text)]
        return [line for line in lines if line]
    return []


def extract_pptx(data: bytes) -> list[dict]:
    try:
        presentation = Presentation(io.BytesIO(data))
    except Exception:
        raise SlidesError("That PowerPoint file couldn't be opened. Open it in PowerPoint, save it again as .pptx, and retry.")

    slides = []
    for number, slide in enumerate(presentation.slides, start=1):
        title_shape = slide.shapes.title
        title = _clean(title_shape.text) if title_shape is not None and title_shape.has_text_frame else ""

        # Read the other shapes top to bottom, left to right.
        shapes = [s for s in slide.shapes if title_shape is None or s.shape_id != title_shape.shape_id]
        shapes.sort(key=lambda s: (s.top or 0, s.left or 0))
        body = []
        for shape in shapes:
            if shape.is_placeholder and shape.placeholder_format.type in SKIP_PLACEHOLDERS:
                continue
            body += _shape_lines(shape)

        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = _clean(slide.notes_slide.notes_text_frame.text)

        if not title and body:
            title = body.pop(0)  # no title box: the first line stands in
        if not title and not notes:
            continue  # picture-only slide
        title = title or f"Slide {number}"
        slides.append({"index": number, "title": title, "text": "\n".join([title] + body), "notes": notes})

    if not slides:
        raise SlidesError("This presentation has no text in it (the slides may be pictures). Nkuzi needs slides with real text.")
    return slides


# ---------- Word ----------

def _heading_level(paragraph) -> int | None:
    """1 or 2 for "Heading 1" / "Heading 2" (or a style based on them); 0 for "Title"."""
    style = paragraph.style
    while style is not None:
        name = (style.name or "").lower()
        if name == "title":
            return 0
        match = re.fullmatch(r"heading\s*(\d)", name)
        if match:
            return int(match.group(1))
        style = style.base_style
    return None


def extract_docx(data: bytes) -> list[dict]:
    try:
        document = Document(io.BytesIO(data))
    except Exception:
        raise SlidesError("That Word file couldn't be opened. Open it in Word, save it again as .docx, and retry.")

    # Walk the document in order. Each Heading 1 / Heading 2 starts a new section.
    sections = []  # [{"title": str or None, "lines": [...]}]
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            lines = []
            for row in block.rows:
                cells = [_clean(cell.text) for cell in row.cells]
                # Merged cells repeat their text; keep each value once.
                cells = [c for i, c in enumerate(cells) if c and c not in cells[:i]]
                if cells:
                    lines.append(" | ".join(cells))
        else:
            text = _clean(block.text)
            if not text:
                continue
            if _heading_level(block) in (0, 1, 2):
                sections.append({"title": text, "lines": []})
                continue
            lines = split_sentences(text) if len(text.split()) > LONG_PARAGRAPH_WORDS else [text]
        if not sections:
            sections.append({"title": None, "lines": []})  # text before the first heading
        sections[-1]["lines"] += lines

    if not any(section["title"] for section in sections):
        # No headings anywhere: cut the text into equal sections instead.
        lines = [line for section in sections for line in section["lines"]]
        sections = [{"title": None, "lines": lines[i : i + CHUNK_LINES]} for i in range(0, len(lines), CHUNK_LINES)]

    # A heading with nothing under it (e.g. a chapter title) isn't a section to explain.
    if any(section["lines"] for section in sections):
        sections = [section for section in sections if section["lines"]]
    if not sections:
        raise SlidesError("This Word file has no text in it.")

    slides = []
    for number, section in enumerate(sections, start=1):
        lines = section["lines"]
        title = section["title"] or " ".join(lines.pop(0).split()[:10])
        slides.append({"index": number, "title": title, "text": "\n".join([title] + lines), "notes": ""})
    return slides
