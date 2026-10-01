import argparse
import logging

parser = argparse.ArgumentParser(prog="python -m examhub_pipeline.convert")
parser.add_argument("step", choices=["text", "extract", "score"])
parser.add_argument("--only", default="", help="comma-separated record slugs")
parser.add_argument("--force", action="store_true")
parser.add_argument("--out", default="", help="extract: folder for the exam files (default site/content/exams)")
args = parser.parse_args()
logging.basicConfig(level=logging.INFO, format="%(message)s")
only = set(filter(None, args.only.split(","))) or None

if args.step == "text":
    from .text import run

    run(only, args.force)
elif args.step == "extract":
    from pathlib import Path

    from . import build

    if args.out:
        build.OUT = Path(args.out)
    build.run(only, args.force)
else:
    from .score import run

    run(only)
