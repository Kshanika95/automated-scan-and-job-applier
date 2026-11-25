"""Measure a resume PDF and check its text layer the way an applicant-tracking system reads it (pypdf):
page count, how far each page is filled, missing must-have strings, ligature glyphs, single-word orphan lines."""
import sys, json, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import core  # noqa: F401  (adds the vendored pylib to sys.path)
import pypdf


def measure(pdf, must_contain=()):
    r = pypdf.PdfReader(pdf)
    pages, texts = [], []
    for pg in r.pages:
        H = float(pg.mediabox.height)
        ys = []

        def v(text, cm, tm, fd, fs):
            if text.strip():
                ys.append(tm[5] * cm[3] + cm[5] if cm else tm[5])
        texts.append(pg.extract_text(visitor_text=v))
        lo, hi = (min(ys), max(ys)) if ys else (H, 0)
        pages.append({"filled_to": round((H - lo) / H, 3), "top_at": round((H - hi) / H, 3)})
    full = "\n".join(texts)
    flat = re.sub(r"\s+", " ", full).lower()
    problems = []
    if re.search(r"[ﬀ-ﬆ]", full):
        problems.append("ligature characters in text layer")
    for s in must_contain:
        if s and s.lower() not in flat:
            problems.append(f"missing in text layer: {s}")
    lines = [l.strip() for l in full.splitlines()]
    for i, l in enumerate(lines[1:], 1):
        if l and len(l.split()) == 1 and len(l) <= 14 and l[-1] in ".,;)" and not lines[i - 1].endswith(":"):
            problems.append(f"orphan word line: {l!r}")
    for ch in "→←✓★":
        if ch in full:
            problems.append(f"non-ATS-safe character {ch!r}")
    return {"pages": pages, "ats_problems": problems, "chars": len(full)}


if __name__ == "__main__":
    print(json.dumps(measure(sys.argv[1], sys.argv[2:]), indent=1))
