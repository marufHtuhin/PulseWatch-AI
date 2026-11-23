"""Regenerate docs/AI_Prompts.docx from docs/AI_Prompts.md.

Simple converter: headings (#/##/###), bullet lists (- ), paragraphs
(hard-wrapped lines joined). Run from the project root.
"""
import re
import sys

from docx import Document

MD = "docs/AI_Prompts.md"
DOCX = "docs/AI_Prompts.docx"


def clean(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)  # inline code -> plain
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links -> text
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)  # bold -> plain
    return text.strip()


def main() -> None:
    with open(MD, encoding="utf-8") as f:
        lines = f.read().splitlines()

    doc = Document()
    buf: list[str] = []

    def flush_paragraph(style: str | None = None) -> None:
        if not buf:
            return
        text = clean(" ".join(buf))
        buf.clear()
        if text:
            doc.add_paragraph(text, style=style)

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_paragraph()
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            flush_paragraph()
            doc.add_heading(clean(m.group(2)), level=len(m.group(1)))
            continue
        if line.startswith("- "):
            flush_paragraph()
            doc.add_paragraph(clean(line[2:]), style="List Bullet")
            continue
        if re.match(r"^\d+\.\s+", line):
            flush_paragraph()
            doc.add_paragraph(clean(re.sub(r"^\d+\.\s+", "", line)), style="List Number")
            continue
        buf.append(line.strip())
    flush_paragraph()

    doc.save(DOCX)
    # Verify by re-reading.
    check = Document(DOCX)
    paras = [p.text for p in check.paragraphs if p.text.strip()]
    headings = [p.text for p in check.paragraphs if p.style.name.startswith("Heading")]
    print(f"wrote {DOCX}: {len(paras)} paragraphs, {len(headings)} headings")
    print("headings:", headings)
    assert "NETWORK_ERROR" in " ".join(paras), "NETWORK_ERROR note missing"
    assert "209 tests" in " ".join(paras), "209 count missing"
    print("verification OK")


if __name__ == "__main__":
    sys.exit(main())
