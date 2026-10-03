"""Every prompt we send to Gemma lives in this file.

They are deliberately short: a small model (gemma3:1b) on a slow CPU does
best with one simple instruction and one simple JSON shape.
"""

OUTLINE_SYSTEM = (
    "You turn lecture slides into a short checklist of the key points a student "
    "must explain. Use only information in the slides."
)

# One slide per call. The reply is {"points": ["...", "..."]} (see outline.py).
OUTLINE_PROMPT = """Slide title: {title}
Slide text:
{body}

Choose the {count} most important lines of this slide.
Shorten each one to at most 15 words, using only words from that line."""

# Added under the slide text when the slide has speaker notes (.pptx only).
OUTLINE_NOTES = """
Speaker notes (extra context only):
{notes}"""
