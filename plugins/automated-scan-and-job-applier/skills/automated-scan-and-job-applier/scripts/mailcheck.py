"""The person's mailbox over IMAP (Gmail app password by default): verification codes and confirmations.

  python3 -I mailcheck.py code --since ISO --from greenhouse --pattern '[A-Za-z0-9]{8}' --timeout 180
  python3 -I mailcheck.py link --since ISO --from workday --timeout 180      (prints a verification URL)
  python3 -I mailcheck.py confirmations --since ISO                           (JSON list)
"""
import imaplib, email, re, time, sys, json, datetime, html
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # python3 -I ignores the script folder
import core
from email.header import decode_header
from email.utils import parsedate_to_datetime

ME = core.CONFIG.get("email", "")


def _pw():
    return core.secret()


def _hdr(v):
    out = ""
    for part, enc in decode_header(v or ""):
        out += part.decode(enc or "utf-8", "replace") if isinstance(part, bytes) else part
    return out


def _body(msg):
    texts = []
    for part in msg.walk():
        ct = part.get_content_type()
        if ct in ("text/plain", "text/html"):
            try:
                t = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
            except Exception:
                continue
            if ct == "text/html":
                t = re.sub(r"(?is)<(script|style).*?</\1>", " ", t)
                links = " ".join(re.findall(r'href="([^"]+)"', t))
                t = html.unescape(re.sub(r"<[^>]+>", " ", t)) + "\nLINKS: " + links
            texts.append(t)
    return "\n".join(texts)


def recent(since, from_hint="", folders=("INBOX", "[Gmail]/Spam")):
    """Messages received after `since` (aware datetime)."""
    M = imaplib.IMAP4_SSL(core.CONFIG.get("imap_host", "imap.gmail.com"), 993)
    M.login(ME, _pw())
    out = []
    for folder in folders:
        if M.select(f'"{folder}"', readonly=True)[0] != "OK":
            continue
        crit = ["SINCE", (since - datetime.timedelta(days=1)).strftime("%d-%b-%Y")]
        if from_hint:
            crit = ["SINCE", crit[1], "TEXT", from_hint]
        typ, data = M.search(None, *crit)
        ids = data[0].split()[-200:] if typ == "OK" else []
        for i in reversed(ids):
            typ, d = M.fetch(i, "(RFC822)")
            if typ != "OK":
                continue
            msg = email.message_from_bytes(d[0][1])
            try:
                when = parsedate_to_datetime(msg["Date"])
                if when.tzinfo is None:
                    when = when.replace(tzinfo=datetime.timezone.utc)
            except Exception:
                continue
            if when < since:
                continue
            out.append({"from": _hdr(msg["From"]), "subject": _hdr(msg["Subject"]), "date": when.isoformat(),
                        "body": _body(msg)})
    M.logout()
    return out


def extract_code(text, pattern=r"[A-Za-z0-9]{6,8}"):
    """A verification code: a standalone token of the given shape with at least 2 digits,
    preferring one that follows 'code' / 'application:' / 'passcode'."""
    body = text.split("LINKS:")[0]
    tok = re.compile(r"(?<![A-Za-z0-9])(" + pattern + r")(?![A-Za-z0-9])")
    def good(c):
        return sum(ch.isdigit() for ch in c) >= 2
    for m in re.finditer(r"(?i)(code|passcode|application)\s*(is|:)?[^A-Za-z0-9]{0,40}", body):
        nxt = tok.match(body, m.end())
        if nxt and good(nxt.group(1)):
            return nxt.group(1)
    for c in tok.findall(body):
        if good(c):
            return c
    return None


def find_code(since, from_hint, pattern, timeout, exclude=(), subject_hint=""):
    end = time.time() + timeout
    while time.time() < end:
        for m in recent(since, from_hint):
            if subject_hint and subject_hint.lower() not in (m["subject"] + " " + m["body"][:300]).lower():
                continue
            text = m["subject"] + "\n" + m["body"]
            if not re.search(r"(?i)code|verif|security", text):
                continue
            c = extract_code(m["body"], pattern) or extract_code(m["subject"], pattern)
            if c and c not in exclude:
                return c
        time.sleep(8)
    return None


def find_link(since, from_hint, timeout, must=r"verif|activate|confirm"):
    end = time.time() + timeout
    while time.time() < end:
        for m in recent(since, from_hint):
            links = re.findall(r"https?://[^\s\"'<>]+", m["body"])
            for l in links:
                if re.search(must, l, re.I) and "unsubscribe" not in l.lower():
                    return html.unescape(l)
        time.sleep(10)
    return None


CONFIRM_RX = re.compile(r"(?i)(thank you for (applying|your (application|interest))|application (was |has been )?(received|submitted)|we('ve| have) received your application|your application (to|for))")


def confirmations(since):
    return [{"from": m["from"], "subject": m["subject"], "date": m["date"]}
            for m in recent(since) if CONFIRM_RX.search(m["subject"] + " " + m["body"][:1500])
            and not re.search(r"(?i)security code|verification code|verify your|one-time|passcode", m["subject"] + " " + m["body"][:600])]


if __name__ == "__main__":
    a = sys.argv[1:]
    opt = lambda k, d="": a[a.index(k) + 1] if k in a else d
    since = datetime.datetime.fromisoformat(opt("--since").replace("Z", "+00:00")) if opt("--since") else \
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    if since.tzinfo is None:
        since = since.replace(tzinfo=datetime.timezone.utc)
    if a[0] == "code":
        c = find_code(since, opt("--from"), opt("--pattern", r"[A-Za-z0-9]{6,8}"), int(opt("--timeout", "180")),
                      exclude=tuple(x for x in opt("--exclude").split(",") if x), subject_hint=opt("--subject"))
        print(c or "")
    elif a[0] == "link":
        l = find_link(since, opt("--from"), int(opt("--timeout", "180")))
        print(l or "")
    elif a[0] == "confirmations":
        print(json.dumps(confirmations(since), indent=1))
