"""Makes the test files in samples/: the same small deck as .pdf, .pptx and .docx.

    python scripts\\make_samples.py
"""
from pathlib import Path

import pymupdf
from docx import Document
from pptx import Presentation
from pptx.util import Inches, Pt

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

SLIDES = [
    ("Beta Blockers", ["Pharmacology study group", "Cardiovascular drugs, week 4"]),
    (
        "Mechanism of action",
        [
            "Block beta-adrenergic receptors, competing with adrenaline and noradrenaline",
            "Beta-1 blockade in the heart lowers heart rate and contractility",
            "Reduce renin release from the kidney, which lowers blood pressure",
            "Slow conduction through the AV node",
        ],
    ),
    (
        "Classification",
        [
            "Non-selective (beta-1 and beta-2): propranolol, timolol",
            "Cardioselective (beta-1): atenolol, metoprolol, bisoprolol",
            "With alpha-blocking activity: carvedilol, labetalol",
            "Cardioselectivity is lost at high doses",
        ],
    ),
    (
        "Clinical uses",
        [
            "Angina, and after myocardial infarction to reduce mortality",
            "Stable heart failure: bisoprolol, carvedilol, metoprolol succinate",
            "Rate control in atrial fibrillation",
            "Propranolol for migraine prophylaxis, essential tremor and thyrotoxicosis",
            "Timolol eye drops for glaucoma",
        ],
    ),
    (
        "Adverse effects and contraindications",
        [
            "Bradycardia, hypotension, fatigue and cold extremities",
            "Bronchospasm: non-selective agents are contraindicated in asthma",
            "Can mask the warning signs of hypoglycaemia in diabetics",
            "Never stop abruptly: risk of rebound tachycardia and angina",
            "Avoid in second or third degree heart block",
        ],
    ),
]


# Extra material only the .pptx has: a table, speaker notes, and a picture-style slide.
DOSE_TABLE = [
    ("Drug", "Selectivity", "Usual daily dose"),
    ("Propranolol", "Non-selective", "80-320 mg"),
    ("Atenolol", "Beta-1 selective", "25-100 mg"),
    ("Bisoprolol", "Beta-1 selective", "2.5-10 mg"),
]
NOTES = {
    "Mechanism of action": "Start with the receptor, then the heart, then the kidney. Stress that renin is why blood pressure falls.",
    "Clinical uses": "Mention that the heart failure evidence is only for three drugs.",
}
OVERDOSE_NOTES = (
    "Beta blocker overdose causes severe bradycardia and hypotension. "
    "Glucagon is the specific antidote. "
    "Atropine and intravenous fluids are given first."
)


def make_pdf():
    doc = pymupdf.open()
    for number, (title, bullets) in enumerate(SLIDES, start=1):
        page = doc.new_page(width=960, height=540)  # 16:9 like a slide
        page.insert_text((60, 90), title, fontsize=34)
        y = 160
        for bullet in bullets:
            page.insert_text((80, y), "- " + bullet, fontsize=18)
            y += 48
        # A footer and page number, so we can test that they get removed.
        page.insert_text((60, 515), "Pharmacology II - Sample deck", fontsize=10)
        page.insert_text((890, 515), str(number), fontsize=10)
    doc.save(SAMPLES / "beta_blockers.pdf")


def make_pptx():
    deck = Presentation()
    title_layout, bullet_layout, title_only = deck.slide_layouts[0], deck.slide_layouts[1], deck.slide_layouts[5]

    for number, (title, bullets) in enumerate(SLIDES):
        slide = deck.slides.add_slide(title_layout if number == 0 else bullet_layout)
        slide.shapes.title.text = title
        frame = slide.placeholders[1].text_frame
        frame.text = bullets[0]
        for bullet in bullets[1:]:
            frame.add_paragraph().text = bullet
        if title in NOTES:
            slide.notes_slide.notes_text_frame.text = NOTES[title]

    # A slide whose content is a table.
    slide = deck.slides.add_slide(title_only)
    slide.shapes.title.text = "Common drugs and doses"
    shape = slide.shapes.add_table(len(DOSE_TABLE), 3, Inches(0.8), Inches(1.8), Inches(8.4), Inches(2.4))
    for r, row in enumerate(DOSE_TABLE):
        for c, value in enumerate(row):
            cell = shape.table.cell(r, c)
            cell.text = value
            cell.text_frame.paragraphs[0].runs[0].font.size = Pt(16)

    # A slide with only a title (imagine a picture): its content is in the notes.
    slide = deck.slides.add_slide(title_only)
    slide.shapes.title.text = "Overdose"
    slide.notes_slide.notes_text_frame.text = OVERDOSE_NOTES

    deck.save(SAMPLES / "beta_blockers.pptx")


def make_docx():
    doc = Document()
    doc.add_heading(SLIDES[0][0], level=0)  # "Title" style
    doc.add_paragraph("Notes for the pharmacology study group, week 4.")
    for title, bullets in SLIDES[1:3]:
        doc.add_heading(title, level=1)
        for bullet in bullets:
            doc.add_paragraph(bullet, style="List Bullet")
    doc.add_heading("Using beta blockers", level=1)  # a chapter heading with nothing under it
    for title, bullets in SLIDES[3:]:
        doc.add_heading(title, level=2)
        # One long paragraph, to test splitting into sentences.
        doc.add_paragraph(". ".join(bullets) + ".")
    doc.add_heading("Common drugs and doses", level=2)
    table = doc.add_table(rows=len(DOSE_TABLE), cols=3)
    for r, row in enumerate(DOSE_TABLE):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    doc.save(SAMPLES / "beta_blockers.docx")


def main():
    SAMPLES.mkdir(exist_ok=True)
    make_pdf()
    make_pptx()
    make_docx()
    print(f"Wrote beta_blockers.pdf, .pptx and .docx to {SAMPLES}")


if __name__ == "__main__":
    main()
