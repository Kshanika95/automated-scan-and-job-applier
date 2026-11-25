"""Send email through the person's own mailbox (SMTP over SSL; Gmail app password by default)."""
import smtplib, ssl, pathlib
from email.message import EmailMessage
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # python3 -I ignores the script folder
import core


def send(subject, html_body, attachments=(), to=None):
    cfg = core.CONFIG
    me = cfg["email"]
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, me, to or cfg.get("report_to") or me
    msg.set_content("This message is HTML. Open it in an email client that shows HTML.")
    msg.add_alternative(html_body, subtype="html")
    for f in attachments:
        f, fname = (f if isinstance(f, (tuple, list)) else (f, pathlib.Path(f).name))
        msg.add_attachment(pathlib.Path(f).read_bytes(), maintype="application", subtype="pdf", filename=fname)
    with smtplib.SMTP_SSL(cfg.get("smtp_host", "smtp.gmail.com"), cfg.get("smtp_port", 465),
                          context=ssl.create_default_context(), timeout=60) as s:
        s.login(me, core.secret())
        s.send_message(msg)


if __name__ == "__main__":
    send("Job applier: test email", "<p>Your job applier can send email. 👍</p>")
    print("sent")
