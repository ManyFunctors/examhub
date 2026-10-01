#!/usr/bin/env python3
"""Check an ExamHub schema idea against real data.

Two commands:

  grep    count documents matching named regex patterns, with examples
  census  count the keys and values an ExamHub front-matter field holds

Sources for `grep`:
  notices  official notice texts (work/corpus/text.json; short or empty ones skipped)
  examhub  ExamHub exam records (site/content/exams/*.md), chosen fields as text
  titles   harvested notice titles (data/harvest/notices.jsonl)

Examples:
  scan.py grep -p 'rank cutoff=top \\d[\\d,]*' -p 'valid score=valid GATE' -s notices,examhub
  scan.py grep -p 'extended=extend' -s titles --examples 5
  scan.py grep -p 'backlog=backlog' -s examhub --fields eligibility,summary --list
  scan.py census fee                 # keys inside ExamHub's fee rows, and how often
  scan.py census fee --key note      # the values of one key, most common first
  scan.py census .                   # top-level keys across all records
"""

import argparse
import collections
import glob
import json
import os
import re
import sys
import tomllib

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
CORPUS = os.path.join(REPO, 'work', 'corpus', 'text.json')
URLS = os.path.join(REPO, 'work', 'corpus', 'urls.txt')
TITLES = os.path.join(REPO, 'data', 'harvest', 'notices.jsonl')
EXAMHUB = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'site', 'content', 'exams')
MIN_TEXT = 2000   # shorter texts are failed extractions (scans, image PDFs)


def load_notices():
    if not os.path.exists(CORPUS):
        sys.exit(f'no notice corpus at {CORPUS}; see SKILL.md, "The data"')
    texts = json.load(open(CORPUS))
    urls = {}
    if os.path.exists(URLS):
        for line in open(URLS):
            key, _, url = line.rstrip('\n').partition('\t')
            urls[key] = url
    out = {}
    for name, text in texts.items():
        if len(text) > MIN_TEXT:
            out[urls.get(name.removesuffix('.pdf'), name)] = text
    return out


def load_records():
    records = {}
    for path in sorted(glob.glob(os.path.join(EXAMHUB, '*.md'))):
        try:
            records[os.path.basename(path)] = tomllib.loads(open(path).read().split('+++')[1])
        except Exception:
            pass   # a record that does not parse is not evidence either way
    return records


def load_examhub(fields):
    out = {}
    for name, rec in load_records().items():
        keys = fields or list(rec)
        out[name] = '\n'.join(str(rec[k]) for k in keys if k in rec)
    return out


def load_titles():
    if not os.path.exists(TITLES):
        sys.exit(f'no harvest at {TITLES}')
    out = {}
    for line in open(TITLES):
        r = json.loads(line)
        out[r.get('id', len(out))] = r.get('title', '')
    return out


def grep(args):
    patterns = []
    for spec in args.pattern:
        name, sep, rx = spec.partition('=')
        if not sep:
            name, rx = spec, spec
        patterns.append((name.strip(), re.compile(rx, 0 if args.case else re.I)))
    fields = [f for f in (args.fields or '').split(',') if f]
    loaders = {'notices': load_notices, 'examhub': lambda: load_examhub(fields), 'titles': load_titles}
    width = max(len(n) for n, _ in patterns)
    for source in args.sources.split(','):
        docs = loaders[source]()
        print(f'\n## {source} ({len(docs)} documents)\n')
        print(f'| {"pattern".ljust(width)} | docs | examples |')
        print(f'|{"-" * (width + 2)}|------|----------|')
        for name, rx in patterns:
            hits, examples = [], []
            for doc, text in docs.items():
                found = list(rx.finditer(text))
                if not found:
                    continue
                hits.append(doc)
                for m in found:
                    a, b = max(0, m.start() - args.context), min(len(text), m.end() + args.context)
                    snippet = re.sub(r'\s+', ' ', text[a:b]).strip().replace('|', '/')
                    if snippet not in examples:
                        examples.append(snippet)
                    if len(examples) >= args.examples:
                        break
            shown = ' // '.join(e[:args.width] for e in examples[:args.examples])
            print(f'| {name.ljust(width)} | {len(hits):4} | {shown} |')
            if args.list:
                for doc in hits[:args.list_max]:
                    print(f'|   {doc}')
    print()


def census(args):
    records = load_records()
    keys, values = collections.Counter(), collections.Counter()
    holders = 0
    for rec in records.values():
        node = rec if args.field == '.' else rec.get(args.field)
        if node is None:
            continue
        holders += 1
        rows = node if isinstance(node, list) else [node]
        for row in rows:
            if isinstance(row, dict):
                keys.update(row.keys())
                if args.key and args.key in row:
                    values[str(row[args.key])[:args.width]] += 1
            elif not args.key:
                values[str(row)[:args.width]] += 1
    print(f'\n## census of `{args.field}` ({holders} of {len(records)} records have it)\n')
    if keys and not args.key:
        print('| key | count |\n|-----|-------|')
        for k, n in keys.most_common(args.top):
            print(f'| {k} | {n} |')
    if values:
        label = args.key or 'value'
        print(f'\n| {label} | count |\n|-----|-------|')
        for v, n in values.most_common(args.top):
            print(f'| {v.replace("|", "/")} | {n} |')
        print(f'\n{len(values)} distinct values')
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    g = sub.add_parser('grep', help='count documents matching named patterns')
    g.add_argument('-p', '--pattern', action='append', required=True, help="'name=regex' (repeatable)")
    g.add_argument('-s', '--sources', default='notices,examhub', help='notices,examhub,titles')
    g.add_argument('--fields', help='ExamHub fields to search (default: all), e.g. eligibility,summary')
    g.add_argument('--examples', type=int, default=3)
    g.add_argument('--context', type=int, default=60, help='characters around each match')
    g.add_argument('--width', type=int, default=120, help='max characters per example')
    g.add_argument('--case', action='store_true', help='case-sensitive')
    g.add_argument('--list', action='store_true', help='also list matching documents')
    g.add_argument('--list-max', type=int, default=20)
    c = sub.add_parser('census', help='keys and values of an ExamHub field')
    c.add_argument('field', help="front-matter field, or '.' for top-level keys")
    c.add_argument('--key', help='show the values of this key inside the field')
    c.add_argument('--top', type=int, default=25)
    c.add_argument('--width', type=int, default=80)
    args = ap.parse_args()
    grep(args) if args.cmd == 'grep' else census(args)


if __name__ == '__main__':
    main()
