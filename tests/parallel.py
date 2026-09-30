"""Run the unittest suite across processes: most test time is waiting on git, so cores sit idle when it runs serially.

    python3 tests/parallel.py [-j N]

Each test already works in its own temporary repository and config directory, so shards share nothing.
"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_ids(item)
        else:
            yield item.id()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", type=int, default=min(os.cpu_count() or 1, 8))
    jobs = parser.parse_args().j
    tests = os.path.join(ROOT, "tests")
    sys.path[:0] = [tests, ROOT]  # Same import roots as `python3 -m unittest discover -s tests`.
    ids = list(test_ids(unittest.defaultTestLoader.discover(tests)))
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([tests, ROOT, os.environ.get("PYTHONPATH", "")]))
    for broken in (i for i in ids if i.startswith("unittest.loader._FailedTest")):
        sys.exit(f"Cannot import {broken}")
    shards = [ids[i::jobs * 3] for i in range(jobs * 3)]  # Small shards even out slow tests between workers.

    def run(shard):
        return subprocess.run([sys.executable, "-m", "unittest", *shard], cwd=ROOT, env=env, capture_output=True, text=True)

    with ThreadPoolExecutor(jobs) as pool:
        results = list(pool.map(run, [shard for shard in shards if shard]))
    ran = sum(int(m.group(1)) for r in results for m in [re.search(r"^Ran (\d+) test", r.stderr, re.M)] if m)
    failed = [r for r in results if r.returncode]
    for result in failed:
        print(result.stdout + result.stderr, file=sys.stderr)
    print(f"Ran {ran} of {len(ids)} tests in {len(results)} shards: " + ("FAILED" if failed or ran != len(ids) else "OK"))
    sys.exit(1 if failed or ran != len(ids) else 0)


if __name__ == "__main__":
    main()
