"""Build the resume PDF from content JSON (resume/master.json shape) and keep only a layout that passes QA.

Usage: build_resume.py content.json out.pdf
Tries font sizes and spacing until the PDF has exactly config.resume_pages pages, the last page is filled to the
bottom (no half-empty page, no spill onto an extra page), the first page has no large gap, and the text layer
reads cleanly (no ligatures, no single-word orphan lines, must-have strings present). Exit 1 when nothing passes:
a resume that fails QA is never submitted.
"""
import json, re, sys, html, subprocess, pathlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import core
sys.path.insert(0, str(HERE))
import pdf_check

CFG = core.CONFIG
PAGES = int(CFG.get("resume_pages", 2))
QA = {"p_last_min": 0.90, "p_last_max": 0.985, "p_first_min": 0.86}
ACCENT = CFG.get("resume_accent", "#2F5496")
BODY_FONT = CFG.get("resume_font_body", "'ResumeBody', 'Aptos', 'Calibri', 'Inter', 'Helvetica Neue', Arial, sans-serif")
HEAD_FONT = CFG.get("resume_font_heading", "'Gill Sans', 'Gill Sans MT', 'Century Gothic', 'Avenir Next', 'Helvetica Neue', Arial, sans-serif")
MUST, LAST = [], None


def md(s):
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(s))


def skill_items(v):
    return ", ".join('<span class="nw">' + html.escape(x.strip()) + "</span>" for x in v.split(","))


def link(item):
    if "|" in item:
        t, u = item.split("|", 1)
        return f'<a href="{html.escape(u)}">{html.escape(t)}</a>'
    return html.escape(item)


def build_html(c, fs, lh, gap, bgap):
    css = f"""
@font-face {{ font-family: 'ResumeBody'; src: local('Aptos Light'), local('Aptos-Light'), local('Aptos'), local('Calibri Light'), local('Calibri'); }}
@font-face {{ font-family: 'ResumeBody'; font-weight: 700; src: local('Aptos SemiBold'), local('Aptos-SemiBold'), local('Aptos Bold'), local('Calibri Bold'); }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-variant-ligatures: none; font-feature-settings: 'liga' 0, 'clig' 0; font-family: {BODY_FONT}; font-size: {fs}pt; line-height: {lh}; color: #000; }}
b {{ font-weight: 700; }}
a {{ color: {ACCENT}; }}
.head {{ font-family: {HEAD_FONT}; color: {ACCENT}; }}
.name {{ font-size: {fs*2.45:.1f}pt; letter-spacing: 1.5px; text-transform: uppercase; line-height: 1.05; }}
.name small {{ font-size: {fs*1.08:.1f}pt; letter-spacing: 2.5px; margin-left: 10px; }}
.contact {{ font-size: {fs*0.82:.1f}pt; word-spacing: 1px; margin-top: 3px; }}
h2 {{ font-family: {HEAD_FONT}; font-weight: 400; color: {ACCENT}; font-size: {fs*1.1:.1f}pt; letter-spacing: 2.2px;
      text-transform: uppercase; margin-top: {gap*1.25:.1f}pt; margin-bottom: 1pt; break-after: avoid; }}
.job {{ margin-top: {gap:.1f}pt; }}
.job:first-of-type {{ margin-top: 1pt; }}
.keep, .block {{ break-inside: avoid; }}
li {{ break-inside: avoid; text-wrap: pretty; position: relative; padding-left: 24px; margin-top: {bgap:.1f}pt; }}
li::before {{ content: '•'; position: absolute; left: 6px; }}
.summary {{ text-wrap: pretty; }}
.row {{ display: flex; justify-content: space-between; align-items: baseline; }}
.row .r {{ font-style: italic; color: #7F7F7F; white-space: nowrap; padding-left: 12px; }}
.jt, .co {{ font-weight: 700; }}
ul {{ margin: {bgap:.1f}pt 0 0 0; padding-left: 0; list-style: none; }}
ul.cont {{ margin-top: 0; }}
table.skills {{ border-collapse: collapse; width: 100%; margin-top: 3pt; }}
table.skills td {{ padding: {bgap+2.5:.1f}pt 6pt {bgap+2.5:.1f}pt 0; vertical-align: top; }}
table.skills tr:nth-child(even) td {{ background: #F0F0F0; }}
table.skills td.k {{ font-weight: 700; white-space: nowrap; width: 1%; padding-right: 18px; }}
span.nw {{ white-space: nowrap; }}
.edu .r {{ font-style: italic; color: #7F7F7F; }}
"""
    p = [f'<div class="head name">{html.escape(c["name"])}&#32;<small>{html.escape(c.get("title", ""))}</small></div>',
         '<div class="contact">' + " &nbsp;|&nbsp; ".join(link(x) for x in c["contact"]) + "</div>",
         f'<div class="block"><h2>{html.escape(c.get("headline", "Summary"))}</h2><div class="summary">{md(c["summary"])}</div></div>',
         "<h2>Professional Experience</h2>"]
    for j in c["experience"]:
        bl = [f"<li>{md(b)}</li>" for b in j["bullets"]]
        p.append('<div class="job"><div class="keep">'
                 f'<div class="row"><span class="jt">{html.escape(j["title"])}</span><span class="r">{html.escape(j["dates"])}</span></div>'
                 f'<div class="row"><span class="co">{html.escape(j["company"])}</span><span class="r">{html.escape(j.get("location", ""))}</span></div>'
                 "<ul>" + "".join(bl[:2]) + "</ul></div>" + ("<ul class='cont'>" + "".join(bl[2:]) + "</ul>" if bl[2:] else "") + "</div>")
    if c.get("skills"):
        p.append('<div class="block"><h2>Skills</h2><table class="skills">' + "".join(
            f'<tr><td class="k">{html.escape(k)}:</td><td>{skill_items(v)}</td></tr>' for k, v in c["skills"]) + "</table></div>")
    if c.get("education"):
        p.append('<div class="block edu"><h2>Education</h2>' + "".join(
            f'<div><b>{html.escape(s)}</b></div><div>{html.escape(d)} | <span class="r">{html.escape(y)}</span></div>'
            for s, d, y in c["education"]) + "</div>")
    if c.get("certifications"):
        p.append('<div class="block"><h2>Certifications</h2>' + "".join(
            f"<div>{html.escape(n)} | {html.escape(o)}</div>" for n, o in c["certifications"]) + "</div>")
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{''.join(p)}</body></html>"


_SRV = None


def _render(h, pdf):
    global _SRV
    for _ in range(2):
        if _SRV is None or _SRV.poll() is not None:
            _SRV = subprocess.Popen([core.node(), str(HERE / "render_server.mjs")], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        try:
            _SRV.stdin.write(f"{h}\t{pdf}\n"); _SRV.stdin.flush()
            if _SRV.stdout.readline().strip() == "ok":
                return
        except Exception:
            pass
        try:
            _SRV.kill()
        except Exception:
            pass
        _SRV = None
    subprocess.run([core.node(), str(HERE / "render.mjs"), str(h), str(pdf)], check=True, capture_output=True)


def render_and_measure(htmltext, pdf):
    h = pdf.with_suffix(".html")
    h.write_text(htmltext)
    _render(h, pdf)
    return pdf_check.measure(str(pdf), MUST)


def passes(m):
    pg = m["pages"]
    if m.get("ats_problems"):
        return False, "; ".join(m["ats_problems"])
    if len(pg) != PAGES:
        return False, f"{len(pg)} pages"
    if PAGES > 1 and pg[0]["filled_to"] < QA["p_first_min"]:
        return False, f"page 1 only filled to {pg[0]['filled_to']:.2f}"
    if not (QA["p_last_min"] <= pg[-1]["filled_to"] <= QA["p_last_max"]):
        return False, f"last page filled to {pg[-1]['filled_to']:.2f}"
    return True, "ok"


def build(content_path, out_pdf):
    global MUST, LAST
    c = json.loads(pathlib.Path(content_path).read_text())
    contact_text = [x.split("|")[0] for x in c.get("contact", [])]
    MUST = [c["name"]] + [x for x in contact_text if "@" in x or re.search(r"\d{3}.*\d{4}", x)] + \
           [j["title"] for j in c["experience"]] + [j["company"].split(" · ")[0] for j in c["experience"]]
    out = pathlib.Path(out_pdf).resolve()
    tmp = out.with_name(out.stem + ".try.pdf")
    best, tried = None, []

    def attempt(fs, k):
        lh, gap, bgap = round(1.12 + 0.20 * k, 3), round(6 + 8 * k, 2), round(1 + 2.5 * k, 2)
        m = render_and_measure(build_html(c, fs, lh, gap, bgap), tmp)
        ok, why = passes(m)
        tried.append((fs, round(k, 3), why))
        return m, ok

    for fs in [12, 11.75, 11.5, 11.25, 11, 10.75, 10.5]:
        m0, _ = attempt(fs, 0.0)
        if len(m0["pages"]) > PAGES:
            continue                       # too long even at the tightest spacing: try a smaller font
        lo, hi = 0.0, 1.6                  # largest spacing that still fits the page count
        for _ in range(7):
            mid = (lo + hi) / 2
            m, _ = attempt(fs, mid)
            lo, hi = (mid, hi) if len(m["pages"]) <= PAGES else (lo, mid)
        m, ok = attempt(fs, lo)
        if ok:
            best = (fs, lo, m)
            tmp.replace(out)
            out.with_suffix(".html").write_text(tmp.with_suffix(".html").read_text())
            break
    for f in (tmp, tmp.with_suffix(".html")):
        if f.exists():
            f.unlink()
    if not best:
        small = [t for t in tried if t[0] == 10.5]
        reason = "overflow" if small and all(re.match(r"\d+ pages", t[2]) for t in small) else "underfill"
        txt = next((t[2] for t in tried if re.search(r"missing|orphan|ligature|character", t[2])), None)
        if txt and reason != "overflow":
            reason = "text-check: " + txt
        LAST = {"ok": False, "reason": reason, "tried": tried[-6:]}
        print(json.dumps(LAST))
        return 1
    LAST = {"ok": True, "font_pt": best[0], "spacing": round(best[1], 3), "pages": best[2]["pages"], "pdf": str(out)}
    print(json.dumps(LAST, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(build(sys.argv[1], sys.argv[2]))
