"""One entry point for every kind of slide file: PDF, PowerPoint, Word."""
import io
import zipfile

from . import office, pdf
from .pdf import SlidesError

OLD_FORMAT_MESSAGE = "Please open this in PowerPoint/Word and Save As .pptx/.docx."
UNSUPPORTED_MESSAGE = "Nkuzi reads .pdf, .pptx and .docx files. Export your slides to one of those and try again."


def extract(filename: str, data: bytes) -> tuple[list[dict], str]:
    """File -> (slides, unit). unit is "Slide", or "Section" for Word files.

    We look at the first bytes of the file, not only its name, so a
    wrongly named file still gets the right message.
    """
    name = (filename or "").lower()

    if data[:5] == b"%PDF-":
        return pdf.extract_slides(data), "Slide"

    # Old .ppt / .doc files are "OLE" containers and start with these bytes.
    if data[:8] == bytes.fromhex("D0CF11E0A1B11AE1") or name.endswith((".ppt", ".doc")):
        raise SlidesError(OLD_FORMAT_MESSAGE)

    # .pptx and .docx are zip files; the folder inside tells us which one.
    if data[:2] == b"PK":
        try:
            inside = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            raise SlidesError("That file looks damaged. Save it again and retry.")
        if "ppt/presentation.xml" in inside:
            return office.extract_pptx(data), "Slide"
        if "word/document.xml" in inside:
            return office.extract_docx(data), "Section"

    raise SlidesError(UNSUPPORTED_MESSAGE)
