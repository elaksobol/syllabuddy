"""Send the weekly Syllabuddy email.

Run it on a schedule (Sunday morning), e.g. with cron:

    0 8 * * 0  cd /path/to/syllabuddy && python scripts/send_weekly.py

Use --dry-run to print the email instead of sending it.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from syllabuddy import db, emailer  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    conn = db.connect()
    print(emailer.send_weekly(conn, dry_run=args.dry_run))
