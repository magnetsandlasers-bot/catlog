"""Render catlog albums, several at a time.

One worker per album, capped by MAX_PARALLEL. Four is the default because
llamabear has 4 physical cores and libmp3lame is single threaded, so 4
encoders is one per core with the hyperthread siblings left for everything
else.

Each album carries its own stall watchdog. With several renders in flight a
wedged encode no longer shows up as the output tree failing to grow, so the
check has to be per album. A stall kills the whole process group, not just
the python parent, because killing the parent leaves ffmpeg running and
still writing.

STAGING. If STAGE_DIR is set, albums are encoded to that local directory and
published to the real out tree only after the render succeeds and the copy is
checked. This exists because ffmpeg writing straight to CIFS can wedge
partway with no error, and four concurrent write streams multiply that risk.
The copy is built in a .incoming directory beside its destination, verified
by file count and byte count, and only then swapped in, so a bad copy cannot
leave truncated files in the out tree looking like a finished album. The
staged copy is deleted after publishing, so staging does not double disk use.
THE DONE PING IS SENT ONLY AFTER PUBLISHING, so a completion notification
always means the album is sitting in the real out tree.

Environment:
  SLUGS           comma separated album slugs (required)
  STAGE_DIR       local staging root, unset to render straight to out
  MAX_PARALLEL    concurrent albums, default 4
  STALL_SECONDS   per album no-growth timeout, default 900
  NICE_LEVEL      niceness for renders, default 10, 0 disables
  HA_BASE         Home Assistant base URL
  CATLOG_OUT, CATLOG_MANIFESTS   as for catlog.py
"""
import json, operator as op, os, shutil, signal, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HA = os.environ.get("HA_BASE", "http://192.168.42.101:8123")
CATLOG = "/r/catlog/catlog.py"
OUT = Path(os.environ.get("CATLOG_OUT", "/r/catlog-data/out"))
MANS = Path(os.environ.get("CATLOG_MANIFESTS", "/r/catlog-data/manifests"))
STAGE = os.environ.get("STAGE_DIR", "")
STALL = int(os.environ.get("STALL_SECONDS", "900"))
JOBS = int(os.environ.get("MAX_PARALLEL", "4"))
NICE = int(os.environ.get("NICE_LEVEL", "10"))
POLL = 10

# Seam so the pool can be exercised against a stub renderer.
CATLOG_CMD = [sys.executable, CATLOG]


def notify(hook, detail):
    body = json.dumps({"detail": detail}).encode()
    req = urllib.request.Request(HA + "/api/webhook/" + hook, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
        return True
    except Exception as exc:
        print("NOTIFY FAILED " + hook + " " + str(exc), flush=True)
        return False


def folders(slug):
    m = json.loads((MANS / slug / "manifest.json").read_text(encoding="utf-8"))
    a = m["album"]
    return a["artist_folder"], a["album_folder"]


def album_dir(slug, root):
    artist, album = folders(slug)
    return Path(root) / artist / album


def render_root():
    return STAGE if STAGE else str(OUT)


def tree_stats(p):
    if not p.exists():
        return (0, 0)
    n = 0
    total = 0
    for f in p.rglob("*"):
        if f.is_file():
            n += 1
            total += f.stat().st_size
    return (n, total)


def preflight(slugs):
    bad = []
    for slug in slugs:
        p = MANS / slug / "manifest.json"
        if not p.is_file():
            bad.append(slug + " (no manifest, run plan first)")
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            bad.append(slug + " (manifest unreadable: " + str(exc) + ")")
            continue
        if m.get("errors"):
            bad.append(slug + " (manifest has errors)")
        elif not m.get("approved"):
            bad.append(slug + " (NOT APPROVED)")
        else:
            print("ready " + slug + " " + str(len(m.get("discs", []))) + " disc(s)", flush=True)
    return bad


def kill_group(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=60)
    except Exception:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()


def publish(slug):
    """Copy a staged album into the real out tree, atomically.

    The album is built in a .incoming directory beside its destination and
    checked BEFORE it is swapped in. Copying straight onto the destination
    would mean a bad copy leaves truncated files in the out tree looking
    like a finished album, which is worse than a clean failure.
    """
    src = album_dir(slug, render_root())
    dst = album_dir(slug, OUT)
    want = tree_stats(src)
    if op.eq(want[0], 0):
        return (False, "stage is empty, nothing to publish")
    dst.parent.mkdir(parents=True, exist_ok=True)
    incoming = dst.parent / (".incoming-" + slug)
    shutil.rmtree(incoming, ignore_errors=True)
    incoming.mkdir(parents=True)
    for f in sorted(src.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(src)
        target = incoming / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    got = tree_stats(incoming)
    if not op.eq(got[0], want[0]):
        shutil.rmtree(incoming, ignore_errors=True)
        return (False, "copy landed " + str(got[0]) + " of " + str(want[0]) + " files")
    if not op.eq(got[1], want[1]):
        shutil.rmtree(incoming, ignore_errors=True)
        return (False, "copy landed " + str(got[1]) + " of " + str(want[1]) + " bytes")
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    try:
        os.rename(incoming, dst)
    except Exception:
        shutil.move(str(incoming), str(dst))
    shutil.rmtree(src, ignore_errors=True)
    return (True, "published " + str(got[0]) + " files " + str(round(got[1] / 1048576.0, 1)) + " MB")


def render_slug(slug):
    root = render_root()
    dest = album_dir(slug, root)
    if STAGE:
        shutil.rmtree(dest, ignore_errors=True)
    env = dict(os.environ)
    env["CATLOG_OUT"] = root
    cmd = CATLOG_CMD + ["render", slug]
    if NICE:
        cmd = ["nice", "-n", str(NICE)] + cmd
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, start_new_session=True)
    last = tree_stats(dest)[1]
    last_change = time.time()
    stalled = False
    while proc.poll() is None:
        time.sleep(POLL)
        cur = tree_stats(dest)[1]
        if not (cur == last):
            last = cur
            last_change = time.time()
        elif op.ge(time.time() - last_change, STALL):
            stalled = True
            kill_group(proc)
            break
    out = proc.communicate()[0] or ""
    res = {"slug": slug, "stalled": stalled, "rc": proc.returncode, "out": out, "note": ""}
    res["mins"] = round((time.time() - t0) / 60.0, 1)
    if stalled or not (proc.returncode == 0):
        res["rc"] = proc.returncode if not stalled else -1
        if STAGE:
            shutil.rmtree(dest, ignore_errors=True)
        return res
    if STAGE:
        good, note = publish(slug)
        res["note"] = note
        if not good:
            res["rc"] = -2
    return res


def run_pool(slugs, jobs):
    ok = []
    failed = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(render_slug, s): s for s in slugs}
        for f in as_completed(futs):
            r = f.result()
            if r["stalled"]:
                failed.append(r["slug"])
                print("STALLED " + r["slug"], flush=True)
                notify("catlog_fail", r["slug"] + " STALLED after " + str(r["mins"]) + " min with no new bytes. Nothing was published.")
            elif op.eq(r["rc"], -2):
                failed.append(r["slug"])
                print("COPY FAILED " + r["slug"] + " " + r["note"], flush=True)
                notify("catlog_fail", r["slug"] + " rendered but publishing failed: " + r["note"] + " Out tree was not modified.")
            elif not op.eq(r["rc"], 0):
                failed.append(r["slug"])
                tail = r["out"].strip().splitlines()[-4:]
                print("FAILED " + r["slug"], flush=True)
                notify("catlog_fail", r["slug"] + " failed after " + str(r["mins"]) + " min. " + " / ".join(tail))
            else:
                ok.append(r["slug"])
                print("OK " + r["slug"] + " " + str(r["mins"]) + " min " + r["note"], flush=True)
    return ok, failed, round((time.time() - t0) / 60.0, 1)


def main():
    raw = [s.strip() for s in os.environ.get("SLUGS", "").split(",") if s.strip()]
    slugs = list(dict.fromkeys(raw))
    if not slugs:
        print("no SLUGS set")
        return 2
    bad = preflight(slugs)
    if bad:
        msg = "Batch aborted before rendering. Not ready: " + ", ".join(bad)
        print(msg)
        notify("catlog_fail", msg)
        return 3
    jobs = max(1, min(JOBS, len(slugs)))
    where = "staged on local disk" if STAGE else "straight to out"
    notify("catlog_start", "Rendering " + str(len(slugs)) + " albums, " + str(jobs) + " at a time, " + where + ".")
    print("rendering " + str(len(slugs)) + " albums, " + str(jobs) + " at a time, " + where, flush=True)
    ok, failed, wall = run_pool(slugs, jobs)
    msg = str(len(ok)) + " ok, " + str(len(failed)) + " failed. Wall " + str(wall) + " min."
    if failed:
        msg = msg + " Failed: " + ", ".join(failed)
    notify("catlog_done", msg)
    print(msg, flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
