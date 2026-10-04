"""Slides PDF -> text per slide, plus a vocabulary string for Whisper."""
import re
from collections import Counter

import pymupdf

NO_TEXT_MESSAGE = (
    "This PDF has no selectable text (it may be scanned images). "
    "Export your slides to PDF from PowerPoint/Google Slides instead."
)


class SlidesError(Exception):
    """Raised with a friendly message the UI can show as-is."""


# Bullet symbols at the start of a line ("• ", "- ", "o ", ...).
BULLET_RE = re.compile(r"^\s*(?:[•◦▪■□●○‣⁃∙·*»➢✓]+|[-–—>]+(?=\s)|o(?=\s))\s*")
# "12", "12 / 40", "Slide 12", "Page 3 of 20"
PAGE_NUMBER_RE = re.compile(r"^(?:(?:slide|page)\s*)?\d{1,3}(?:\s*(?:/|of)\s*\d{1,3})?$", re.I)
# Symbol-font bullets show up as "private use" characters; they carry no meaning.
PRIVATE_USE_RE = re.compile(r"[-]")
WORD_RE = re.compile(r"[^\W_](?:[\w\-/%.]*[\w%])?")

# Common words that are never useful as key terms.
STOPWORDS = set(
    "the and for are but not you all can has have had was were with this that these those "
    "from they their them then than there here what when where which while who why how "
    "will would should could may might must also into onto over under about after before "
    "between because during each other such some more most less many much very only both "
    "your its our out off per via use used using uses include includes including e.g i.e "
    "slide slides page".split()
)


def _read_lines(page) -> list[dict]:
    """All text lines on a page, top to bottom: {text, size, block, bulleted}."""
    lines = []
    blocks = page.get_text("dict", sort=True)["blocks"]
    for block_number, block in enumerate(blocks):
        if block["type"] != 0:  # 0 = text, 1 = image
            continue
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            raw = PRIVATE_USE_RE.sub("", "".join(s["text"] for s in line["spans"]))
            text = BULLET_RE.sub("", raw)
            text = re.sub(r"\s+", " ", text).strip()
            if not text or PAGE_NUMBER_RE.match(text):
                continue
            lines.append(
                {
                    "text": text,
                    "size": max(s["size"] for s in spans),  # font size
                    "block": block_number,
                    "bulleted": text != raw.strip(),
                }
            )
    return lines


def _normalise(text: str) -> str:
    """So "Page 3 of 20" and "Page 4 of 20" count as the same footer."""
    return re.sub(r"\d+", "#", text.lower())


def _build_slide(number: int, lines: list[dict]) -> dict:
    # Title = the line with the biggest font (the first one, if several tie).
    t = max(range(len(lines)), key=lambda i: (lines[i]["size"], -i))
    title = lines[t]["text"]
    end = t + 1
    # A long title wraps onto a second line with the same font size.
    while (
        end < len(lines)
        and lines[end]["block"] == lines[t]["block"]
        and abs(lines[end]["size"] - lines[t]["size"]) < 0.5
        and not lines[end]["bulleted"]
        and end - t < 3
    ):
        title += " " + lines[end]["text"]
        end += 1

    body = []
    previous = None
    for line in lines[:t] + lines[end:]:
        # A wrapped bullet continues on the next line, starting in lower case.
        wrapped = (
            previous is not None
            and line["block"] == previous["block"]
            and not line["bulleted"]
            and line["text"][0].islower()
        )
        if wrapped:
            body[-1] += " " + line["text"]
        else:
            body.append(line["text"])
        previous = line

    # PDFs carry no speaker notes; .pptx files do (see office.py).
    return {"index": number, "title": title, "text": "\n".join([title] + body), "notes": ""}


def extract_slides(pdf_bytes: bytes) -> list[dict]:
    """PDF bytes -> [{index (1-based page number), title, text, notes}], skipping empty slides."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        raise SlidesError("That file couldn't be opened as a PDF. Export your slides to PDF and try again.")
    if doc.needs_pass:
        raise SlidesError("This PDF is password-protected. Remove the password and try again.")

    pages = [(page.number + 1, _read_lines(page)) for page in doc]
    doc.close()

    with_text = sum(1 for _, lines in pages if lines)
    if with_text == 0:
        raise SlidesError(NO_TEXT_MESSAGE)

    # Footers / headers: the same line on more than half of the slides.
    repeated = set()
    if with_text >= 4:
        counts = Counter()
        for _, lines in pages:
            counts.update({_normalise(line["text"]) for line in lines})
        repeated = {text for text, count in counts.items() if count > with_text / 2}

    slides = []
    for number, lines in pages:
        lines = [line for line in lines if _normalise(line["text"]) not in repeated]
        if lines:  # image-only slides are skipped
            slides.append(_build_slide(number, lines))
    if not slides:
        raise SlidesError(NO_TEXT_MESSAGE)
    return slides


def is_distinctive(word: str, first_in_line: bool = False) -> bool:
    """Is this the kind of term Whisper might misspell (drug names, acronyms, doses)?"""
    if word.lower() in STOPWORDS:
        return False
    if len(word) >= 8:
        return True
    if any(c.isdigit() for c in word) and any(c.isalpha() for c in word):
        return True  # "β1", "5-HT3", "20mg"
    if len(word) >= 2 and word.isupper():
        return True  # acronyms: "AV", "COPD"
    # Capitalised mid-sentence is probably a name. (Every line starts with a capital.)
    return word[0].isupper() and len(word) >= 4 and not first_in_line


# Long words that appear in any lecture. Whisper already knows how to spell
# them, so they would only waste space in the hint.
GENERIC_WORDS = set(
    "introduction features clinical management medicine disease diseases patients patient "
    "characterized associated affected advanced exposure limitation abnormal common commonly "
    "treatment increased increases decrease decreased following including important "
    "different differential diagnosis presentation complications investigation investigations "
    "definition definitions classification epidemiology pathology pathogenesis pathophysiology "
    "prognosis conclusion references objectives overview outline factors usually presents "
    "development developed function functional structure structural response progressive "
    "symptoms syndrome condition conditions therapy examples especially generally commonest "
    "persistent significant particles physical history general especially estimated reported "
    "prevalence likely distinct represents severe chronic acute".split()
)
VOCAB_TERMS = 30  # how many terms the Whisper hint holds


def build_vocab(slides: list[dict], max_terms: int = VOCAB_TERMS) -> str:
    """The deck's ~30 most distinctive terms, as one comma-separated string.

    This is given to Whisper as a hint so it spells medical terms the way the
    slides do. It is kept short on purpose: a long list of words in the prompt
    takes attention away from the audio, and generic words ("features",
    "patients") add nothing.
    """
    counts = Counter()
    spelling = {}  # lower-case term -> the spelling first seen on the slides
    for slide in slides:
        # Speaker notes count too: the explainer is likely to say those words.
        for line in (slide["text"] + "\n" + slide.get("notes", "")).split("\n"):
            for i, word in enumerate(WORD_RE.findall(line)):
                key = word.lower()
                if key in GENERIC_WORDS or not is_distinctive(word, first_in_line=(i == 0)):
                    continue
                counts[key] += 1
                spelling.setdefault(key, word)

    # Most distinctive first: long or unusual-looking terms that the deck keeps using.
    def score(key: str) -> float:
        word = spelling[key]
        unusual = len(key) >= 10 or word.isupper() or any(c.isdigit() for c in word) or not key.isascii()
        return counts[key] + (2 if unusual else 0)

    ranked = sorted(counts, key=lambda key: -score(key))  # ties keep slide order
    return ", ".join(spelling[key] for key in ranked[:max_terms])


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences (simple rule: ., ! or ? then a capital)."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", " ".join(text.split()))
    return [part for part in parts if part]
