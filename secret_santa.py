import streamlit as st
import csv
import io
import random
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Dict, List, Tuple, Optional, Set

st.set_page_config(page_title="Secret Santa Matcher", page_icon="🎁", layout="centered")

# ---------- Helpers ----------
def read_participants(file) -> List[Dict[str, str]]:
    content = file.read().decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))
    # normalize header names so we can access row["name"] reliably regardless of case/spacing
    if reader.fieldnames:
        reader.fieldnames = [(f or "").strip().lower() for f in reader.fieldnames]
    required = {"name", "email"}
    if not required.issubset({(f or "").strip().lower() for f in reader.fieldnames or []}):
        raise ValueError("Participants CSV must have headers: name,email")
    participants = []
    seen_emails = set()
    for row in reader:
        # row keys are normalized to lower-case above
        name = (row.get("name") or "").strip()
        email = (row.get("email") or "").strip().lower()
        if not name or not email:
            continue
        if email in seen_emails:
            raise ValueError(f"Duplicate email in participants: {email}")
        seen_emails.add(email)
        participants.append({"name": name, "email": email})
    if len(participants) < 2:
        raise ValueError("Need at least 2 participants.")
    return participants

def read_previous_matches(file) -> Dict[str, str]:
    content = file.read().decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames:
        reader.fieldnames = [(f or "").strip().lower() for f in reader.fieldnames]
    required = {"giver_email", "receiver_email"}
    if not required.issubset({(f or "").strip().lower() for f in reader.fieldnames or []}):
        raise ValueError("Previous matches CSV must have headers: giver_email,receiver_email")
    mapping = {}
    for row in reader:
        giver = (row.get("giver_email") or "").strip().lower()
        recv = (row.get("receiver_email") or "").strip().lower()
        if giver and recv:
            mapping[giver] = recv
    return mapping

def read_forbidden_pairs(file) -> Dict[str, Set[str]]:
    content = file.read().decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames:
        reader.fieldnames = [(f or "").strip().lower() for f in reader.fieldnames]
    required = {"giver_email", "receiver_email"}
    if not required.issubset({(f or "").strip().lower() for f in reader.fieldnames or []}):
        raise ValueError("Forbidden pairs CSV must have headers: giver_email,receiver_email")
    mapping: Dict[str, Set[str]] = {}
    for row in reader:
        giver = (row.get("giver_email") or "").strip().lower()
        recv = (row.get("receiver_email") or "").strip().lower()
        if giver and recv:
            mapping.setdefault(giver, set()).add(recv)
    return mapping

def symmetrize_forbidden(forbidden: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    # Add reciprocal constraints (giver->receiver implies receiver->giver)
    for giver, recvs in list(forbidden.items()):
        for recv in list(recvs):
            forbidden.setdefault(recv, set()).add(giver)
    return forbidden

def backtracking_match(
    emails: List[str],
    prev_map: Dict[str, str],
    forbidden_map: Dict[str, Set[str]]
) -> Optional[Dict[str, str]]:
    """Return a mapping giver_email -> receiver_email that:
        - is a permutation
        - has no self assignments
        - avoids repeating last year's pairs in prev_map
        - avoids pairs in forbidden_map (giver -> set(receivers))
    Uses simple randomized backtracking (works well for typical group sizes)."""
    n = len(emails)
    givers = emails[:]
    random.shuffle(givers)
    receivers = emails[:]

    assignment: Dict[str, str] = {}
    used: Set[str] = set()

    def helper(i: int) -> bool:
        if i == n:
            return True
        g = givers[i]
        forbidden_for_g = forbidden_map.get(g, set())
        # Candidates: not used, not self, not previous match, not forbidden pair
        candidates = [r for r in receivers
                        if r not in used and r != g and prev_map.get(g) != r and r not in forbidden_for_g]
        random.shuffle(candidates)
        for r in candidates:
            assignment[g] = r
            used.add(r)
            if helper(i + 1):
                return True
            used.remove(r)
            del assignment[g]
        return False

    ok = helper(0)
    return assignment if ok else None

def make_matches(participants: List[Dict[str, str]], prev_map: Dict[str, str], forbidden_map: Dict[str, Set[str]]) -> Dict[str, str]:
    emails = [p["email"] for p in participants]
    # Ensure constraints only reference current participants
    prev_map = {g: r for g, r in prev_map.items() if g in emails and r in emails}
    forbidden_map = {g: {r for r in recvs if r in emails} for g, recvs in forbidden_map.items() if g in emails}
    # Try a few times in case of unlucky randomization
    for _ in range(30):
        result = backtracking_match(emails, prev_map, forbidden_map)
        if result:
            return result
    raise RuntimeError("No valid matching found with the given constraints. "
                        "Consider relaxing forbidden pairs or previous matches, or adding more participants.")

def build_message(subject_tmpl: str, body_tmpl: str, giver, receiver, organizer_email: str) -> EmailMessage:
    msg = EmailMessage()
    subject = _safe_format(subject_tmpl,
        giver_name=giver["name"], giver_email=giver["email"],
        receiver_name=receiver["name"], receiver_email=receiver["email"]
    )
    body = _safe_format(body_tmpl,
        giver_name=giver["name"], giver_email=giver["email"],
        receiver_name=receiver["name"], receiver_email=receiver["email"]
    )

    # sanitize headers to avoid CR/LF injection
    subject = _sanitize_header(subject)[:998]  # keep subject reasonable length
    from_addr = _sanitize_header(organizer_email)
    to_addr = _sanitize_header(giver["email"])

    if not _is_valid_email(from_addr):
        raise ValueError("Invalid From email address")
    if not _is_valid_email(to_addr):
        raise ValueError(f"Invalid recipient email: {to_addr}")

    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)
    return msg

def send_emails(
    matches: Dict[str, str],
    participants: List[Dict[str, str]],
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    use_ssl: bool,
    subject_tmpl: str,
    body_tmpl: str,
    organizer_email: str
) -> Tuple[int, List[Tuple[str, str]]]:
    by_email = {p["email"]: p for p in participants}
    sent = 0
    failures = []

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
        if smtp_user:
            server.login(smtp_user, smtp_password)
    except Exception as e:
        raise RuntimeError(f"Failed to connect/login to SMTP: {e}")

    try:
        for giver_email, receiver_email in matches.items():
            giver = by_email[giver_email]
            receiver = by_email[receiver_email]
            msg = build_message(subject_tmpl, body_tmpl, giver, receiver, organizer_email)
            try:
                server.send_message(msg)
                sent += 1
            except Exception as e:
                failures.append((giver_email, str(e)))
    finally:
        try:
            server.quit()
        except Exception:
            pass

    return sent, failures

def to_csv_bytes(rows: List[Dict[str, str]]) -> bytes:
    if not rows:
        return b""
    # sanitize/escape formula cells
    sanitized_rows = []
    keys = list(rows[0].keys())
    for r in rows:
        sanitized_rows.append({k: _escape_csv_cell(str(r.get(k, "") or "")) for k in keys})
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=keys)
    writer.writeheader()
    writer.writerows(sanitized_rows)
    return buf.getvalue().encode("utf-8")

def _sanitize_header(value: str) -> str:
    if value is None:
        return ""
    # Remove CR/LF to prevent header injection
    return value.replace("\r", " ").replace("\n", " ").strip()

def _is_valid_email(addr: str) -> bool:
    # basic validation: parsed address has a local@domain form
    name, email = parseaddr(addr or "")
    return "@" in email and "." in email

class _SafeDict(dict):
    def __missing__(self, key):
        # leave unknown placeholders unchanged to avoid KeyError
        return "{" + key + "}"

def _safe_format(tmpl: str, **kwargs) -> str:
    try:
        return tmpl.format_map(_SafeDict(**{k: (v or "") for k, v in kwargs.items()}))
    except Exception:
        # fallback: return tmpl with placeholders unchanged
        return tmpl

def _escape_csv_cell(s: str) -> str:
    if not s:
        return s or ""
    if s[0] in ("=", "+", "-", "@"):
        return "'" + s
    return s

# ---------- UI ----------
st.title("Secret Santa Matcher 🎁")

st.write("Upload participants (CSV with headers: name,email). Optionally upload last year's matches (CSV headers: giver_email,receiver_email).")
st.write("You can also upload Forbidden pairs (CSV headers: giver_email,receiver_email) to prevent specific matches.")

sample_participants = "name,email\nAlice,alice@example.com\nBob,bob@example.com\nCarol,carol@example.com\nDave,dave@example.com\n"
sample_prev = "giver_email,receiver_email\nalice@example.com,bob@example.com\nbob@example.com,carol@example.com\ncarol@example.com,dave@example.com\ndave@example.com,alice@example.com\n"
sample_forbidden = "giver_email,receiver_email\nalice@example.com,carol@example.com\nbob@example.com,alice@example.com\n"

colA, colB, colC = st.columns(3)
with colA:
    st.download_button("Sample participants.csv", sample_participants.encode("utf-8"), "participants_sample.csv", "text/csv")
with colB:
    st.download_button("Sample last_matches.csv", sample_prev.encode("utf-8"), "last_matches_sample.csv", "text/csv")
with colC:
    st.download_button("Sample forbidden_pairs.csv", sample_forbidden.encode("utf-8"), "forbidden_pairs_sample.csv", "text/csv")

participants_file = st.file_uploader("Participants CSV", type=["csv"])
prev_file = st.file_uploader("Last matches CSV (optional)", type=["csv"])
forbidden_file = st.file_uploader("Forbidden pairs CSV (optional)", type=["csv"])
forbid_symmetric = st.checkbox("Treat forbidden pairs as symmetric (block both directions)", value=True,
                                help="If checked, a row A->B also blocks B->A.")

debug_mode = st.checkbox("Debug mode (show matches on screen, do not send emails)", value=True)

st.markdown("---")
st.subheader("Email settings")

st.caption("In Debug mode these are ignored. For sending, provide a real SMTP server (e.g., Gmail, your provider, Mailgun/SendGrid SMTP). For Gmail, use an App Password.")
smtp_host = st.text_input("SMTP host", value="smtp.gmail.com")
smtp_port = st.number_input("SMTP port", value=465, step=1, min_value=1)
use_ssl = st.checkbox("Use SSL (disable for STARTTLS on 587)", value=True)
smtp_user = st.text_input("SMTP username (often your email)", value="", help="Leave blank if your server allows unauthenticated sending (not common).")
smtp_password = st.text_input("SMTP password / app password", value="", type="password")
organizer_email = st.text_input("From email (shown to recipients)", value=smtp_user or "")

st.markdown("---")
st.subheader("Message templates")

default_subject = "Your Secret Santa match!"
default_body = (
    "Hi {giver_name},\n\n"
    "You have been matched to give a gift to: {receiver_name}.\n"
    "Recipient email: {receiver_email}\n\n"
    "Happy gifting!\n"
    "- Secret Santa Organizer"
)
subject_tmpl = st.text_input("Email subject template", value=default_subject,
                            help="Placeholders: {giver_name}, {giver_email}, {receiver_name}, {receiver_email}")
body_tmpl = st.text_area("Email body template", value=default_body, height=180,
                        help="Placeholders: {giver_name}, {giver_email}, {receiver_name}, {receiver_email}")

run = st.button("Generate matches" if debug_mode else "Generate matches and send emails")

if run:
    try:
        if not participants_file:
            st.error("Please upload a participants CSV.")
            st.stop()
        participants = read_participants(participants_file)

        prev_map = {}
        if prev_file:
            prev_map = read_previous_matches(prev_file)

        forbidden_map: Dict[str, Set[str]] = {}
        if forbidden_file:
            forbidden_map = read_forbidden_pairs(forbidden_file)
            if forbid_symmetric:
                forbidden_map = symmetrize_forbidden(forbidden_map)

        matches = make_matches(participants, prev_map, forbidden_map)

        # Prepare display/download
        by_email = {p["email"]: p for p in participants}
        rows = []
        for giver_email, receiver_email in matches.items():
            rows.append({
                "giver_name": by_email[giver_email]["name"],
                "giver_email": giver_email,
                "receiver_name": by_email[receiver_email]["name"],
                "receiver_email": receiver_email
            })

        if debug_mode:
            st.success("Matches generated (DEBUG: no emails sent):")
            st.write(rows)
            st.download_button("Download matches CSV", to_csv_bytes(rows), "matches.csv", "text/csv")
        else:
            if not smtp_host or not organizer_email:
                st.error("Please fill SMTP host and From email.")
                st.stop()
            sent, failures = send_emails(
                matches, participants,
                smtp_host, int(smtp_port), smtp_user, smtp_password, use_ssl,
                subject_tmpl, body_tmpl, organizer_email
            )
            if sent:
                st.success(f"Emails sent: {sent}")
            if failures:
                st.error(f"Failed to send {len(failures)} emails")
                for addr, err in failures:
                    st.write(f"{addr}: {err}")

            # Offer a CSV to keep as "last matches" for next year
            st.download_button(
                "Download these matches to save for next time",
                to_csv_bytes([{"giver_email": r["giver_email"], "receiver_email": r["receiver_email"]} for r in rows]),
                "last_matches_for_next_year.csv",
                "text/csv"
            )

    except Exception as e:
        st.error(str(e))