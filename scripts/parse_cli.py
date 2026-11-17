"""Parse one or more syllabus PDFs from the command line and store them.

    python scripts/parse_cli.py docs/test_syllabi/*.pdf --year 2026

Handy for testing the parser without starting the web app. Prints the extracted JSON.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from syllabuddy import db  # noqa: E402
from syllabuddy.gemini_client import GeminiBackend, GeminiError, parse_syllabus  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--no-save", action="store_true", help="print only; don't write to the database")
    args = ap.parse_args()

    backend = GeminiBackend()
    conn = None if args.no_save else db.connect()
    failures = 0
    for i, pdf in enumerate(args.pdfs):
        if i:
            time.sleep(4)  # stay under free-tier rate limits
        try:
            ex = parse_syllabus(pdf.read_bytes(), backend=backend, semester_year=args.year)
        except (GeminiError, OSError) as e:
            print(f"FAILED {pdf.name}: {e}")
            failures += 1
            continue
        print(f"--- {pdf.name} ---")
        print(ex.model_dump_json(indent=2))
        if conn:
            print("saved as course id", db.save_extraction(conn, ex, source_file=pdf.name))
    sys.exit(1 if failures else 0)
