"""Tests for the batch driver.

Exercises the worker pool, the staging and publish path, and the two failure
modes that matter, against a stub renderer. No real manifests, no real audio
and no Home Assistant webhooks are involved: batch.notify is replaced.

Run it on llamabear, from the repo root:

    docker run --rm -v /mnt/recorder_pipeline:/r
        --entrypoint python3 ghcr.io/open-webui/open-webui:main
        /r/catlog/tests/test_batch.py

Exits 0 if every check passes, 1 otherwise.
"""
import shutil, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import batch

STUB_SRC = (
    "import os, sys, time\n"
    "from pathlib import Path\n"
    "slug = sys.argv[-1]\n"
    "root = Path(os.environ['CATLOG_OUT']) / 'Artist' / ('Album ' + slug)\n"
    "root.mkdir(parents=True, exist_ok=True)\n"
    "if 'stall' in slug:\n"
    "    (root / 'partial.mp3').write_bytes(b'p' * 5000)\n"
    "    time.sleep(3600)\n"
    "for i in range(3):\n"
    "    (root / ('t%02d.mp3' % i)).write_bytes(b'y' * 100000)\n"
    "    time.sleep(0.2)\n"
    "(root / 'cover.jpg').write_bytes(b'z' * 2000)\n"
)

failures = []


def check(name, cond):
    if cond:
        print("PASS " + name)
    else:
        print("FAIL " + name)
        failures.append(name)


def harness(tmp):
    tmp = Path(tmp)
    stage = tmp / "stage"
    out = tmp / "out"
    stage.mkdir(parents=True)
    out.mkdir(parents=True)
    stub = tmp / "stub.py"
    stub.write_text(STUB_SRC, encoding="utf-8")
    batch.CATLOG_CMD = [sys.executable, str(stub)]
    batch.folders = lambda slug: ("Artist", "Album " + slug)
    batch.STAGE = str(stage)
    batch.OUT = out
    batch.NICE = 0
    batch.STALL = 8
    batch.POLL = 1
    batch.notify = lambda hook, detail: None
    return stage, out


def test_publish(tmp):
    stage, out = harness(tmp)
    ok, failed, wall = batch.run_pool(["u1", "u2", "u3"], 3)
    check("three albums published", sorted(ok) == ["u1", "u2", "u3"])
    check("no failures", failed == [])
    check("album landed in out", (out / "Artist" / "Album u1" / "cover.jpg").is_file())
    check("four files landed", len(list((out / "Artist" / "Album u1").glob("*"))) == 4)
    check("stage emptied", len([p for p in stage.rglob("*") if p.is_file()]) == 0)
    check("no incoming left behind", len(list((out / "Artist").glob(".incoming-*"))) == 0)


def test_stall(tmp):
    stage, out = harness(tmp)
    ok, failed, wall = batch.run_pool(["stall-me"], 1)
    check("stalled album fails", failed == ["stall-me"] and ok == [])
    check("nothing published on stall", not (out / "Artist" / "Album stall-me").exists())


def test_bad_copy(tmp):
    stage, out = harness(tmp)
    real = batch.shutil.copy2
    batch.shutil.copy2 = lambda src, dst: Path(dst).write_bytes(b"short")
    try:
        ok, failed, wall = batch.run_pool(["c1"], 1)
    finally:
        batch.shutil.copy2 = real
    check("bad copy fails", failed == ["c1"] and ok == [])
    check("out untouched by bad copy", not (out / "Artist" / "Album c1").exists())
    check("no incoming left after bad copy", len(list((out / "Artist").glob(".incoming-*"))) == 0)
    check("stage kept for retry", (stage / "Artist" / "Album c1" / "cover.jpg").is_file())


def main():
    for fn in (test_publish, test_stall, test_bad_copy):
        tmp = tempfile.mkdtemp(prefix=fn.__name__)
        print("--- " + fn.__name__)
        try:
            fn(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("")
    if failures:
        print(str(len(failures)) + " failed: " + ", ".join(failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
