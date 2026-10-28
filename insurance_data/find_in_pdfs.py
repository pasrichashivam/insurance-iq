"""Search the sample policy PDFs offline (no API key, no vector store) to verify a RAG answer against the original text.

    python insurance_data/find_in_pdfs.py "decision" "60"          # lines containing ALL the words
    python insurance_data/find_in_pdfs.py "reserv" --file siu      # only PDFs whose name contains 'siu'
"""
import sys
from pathlib import Path

from pypdf import PdfReader

DOCS = Path(__file__).resolve().parent.parent / "sample_docs"


def main() -> None:
    args = sys.argv[1:]
    only = None
    if "--file" in args:
        i = args.index("--file")
        only = args[i + 1].lower()
        args = args[:i] + args[i + 2:]
    if not args:
        sys.exit(__doc__)
    words = [a.lower() for a in args]
    hits = 0
    for pdf in sorted(DOCS.glob("*.pdf")):
        if only and only not in pdf.name.lower():
            continue
        for page_no, page in enumerate(PdfReader(pdf).pages, 1):
            for line in (page.extract_text() or "").splitlines():
                if all(w in line.lower() for w in words):
                    hits += 1
                    print(f"{pdf.name}  p.{page_no}: {line.strip()}")
    print(f"\n{hits} matching line(s).")


if __name__ == "__main__":
    main()
