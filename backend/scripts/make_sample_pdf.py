"""Makes samples/beta_blockers.pdf: a small slide deck for testing.

    python scripts\\make_sample_pdf.py
"""
from pathlib import Path

import pymupdf

OUT = Path(__file__).resolve().parent.parent / "samples" / "beta_blockers.pdf"

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


def main():
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
    OUT.parent.mkdir(exist_ok=True)
    doc.save(OUT)
    print(f"Wrote {OUT} ({len(SLIDES)} slides)")


if __name__ == "__main__":
    main()
