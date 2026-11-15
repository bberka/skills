#!/usr/bin/env python3
"""Pick the test files for one shard, balanced by recorded run time.

  <list test files> | split_by_time.py --shard 2 --of 4 --timings 'reports/**/*.xml'

Reads test file paths from stdin, one per line. Timings come from JUnit XML
reports (the `file` attribute, or the classname when it is a path) or from a
JSON object of {"path": seconds}. A file with no recorded time gets the median.
With no timings at all, files are dealt out evenly by count. Every shard must
receive the same file list and the same timings, or shards will overlap.
"""

import argparse
import glob
import json
import statistics
import sys
import xml.etree.ElementTree as ET


def load_timings(patterns):
    seconds = {}
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):
            if path.endswith(".json"):
                with open(path) as handle:
                    for name, value in json.load(handle).items():
                        seconds[name] = seconds.get(name, 0.0) + float(value)
                continue
            try:
                root = ET.parse(path).getroot()
            except ET.ParseError:
                continue
            for case in root.iter("testcase"):
                name = case.get("file") or case.get("classname") or ""
                seconds[name] = seconds.get(name, 0.0) + float(case.get("time") or 0)
            for suite in root.iter("testsuite"):
                # Some runners time the file on the suite and leave test cases without a file.
                name = suite.get("file") or suite.get("name") or ""
                if name not in seconds:
                    seconds[name] = float(suite.get("time") or 0)
    return seconds


def lookup(file, seconds):
    if file in seconds:
        return seconds[file]
    normal = file.replace("\\", "/").lstrip("./")
    for name, value in seconds.items():
        other = name.replace("\\", "/").lstrip("./")
        if other and (other.endswith(normal) or normal.endswith(other)):
            return value
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shard", type=int, required=True, help="this shard, counted from 1")
    parser.add_argument("--of", type=int, required=True, help="number of shards")
    parser.add_argument("--timings", action="append", default=[], help="glob of JUnit XML or JSON timing files")
    parser.add_argument("--show", action="store_true", help="print each shard's expected time to stderr")
    args = parser.parse_args()
    if not 1 <= args.shard <= args.of:
        sys.exit("split_by_time: --shard must be between 1 and --of")

    files = sorted({line.strip() for line in sys.stdin if line.strip()})
    seconds = load_timings(args.timings)
    known = {f: t for f in files if (t := lookup(f, seconds)) is not None}
    default = statistics.median(known.values()) if known else 1.0
    weights = {f: known.get(f, default) for f in files}

    # Longest first into the emptiest shard. Ties break on the path, so every shard computes the same split.
    shards = [[] for _ in range(args.of)]
    totals = [0.0] * args.of
    for file in sorted(files, key=lambda f: (-weights[f], f)):
        index = min(range(args.of), key=lambda i: (totals[i], i))
        shards[index].append(file)
        totals[index] += weights[file]

    if args.show:
        for index, total in enumerate(totals, 1):
            print(f"shard {index}: {len(shards[index - 1])} files, {total:.1f}s expected", file=sys.stderr)
        print(f"{len(known)}/{len(files)} files had a recorded time", file=sys.stderr)
    print("\n".join(sorted(shards[args.shard - 1])))


if __name__ == "__main__":
    main()
