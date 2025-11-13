# Secret Santa Matcher 🎁

A simple Streamlit web app to generate Secret Santa matches with constraints and optionally notify participants by email.

## Features

- Upload participants (name, email)
- Avoid self-matches
- Avoid repeating last year’s pairs
- Block specific forbidden pairs (optionally symmetric)
- Debug mode to preview matches on screen (no emails sent)
- Customizable email subject/body templates
- Download matches as CSV (and save for next year)

## Prerequisites

- Python 3.9+ (for local runs), or
- Docker (optional, for containerized runs)

## Quick start (Python)

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the app:
   ```bash
   streamlit run secret_santa.py
   ```
3. Open http://localhost:8501 in your browser.

## Quick start (Docker)

Build and run:
```bash
docker build -t secret-santa:latest .
docker run --rm -p 8501:8501 secret-santa:latest
```

Dev-friendly hot-reload with Docker Compose:
```bash
docker compose up --build
```

## Using the app

1. Prepare a CSV of participants with headers `name,email`.
2. Optionally upload:
   - Last matches CSV: `giver_email,receiver_email`
   - Forbidden pairs CSV: `giver_email,receiver_email`
3. Keep “Debug mode” ON to verify matches without sending emails.
4. When ready to send emails:
   - Fill SMTP settings (see tips below)
   - Uncheck Debug mode
   - Click “Generate matches and send emails”

### Email sending tips

- Gmail:
  - Host: `smtp.gmail.com`
  - Port: `465` (SSL ON) or `587` (SSL OFF, uses STARTTLS)
  - Username: your Gmail address
  - Password: an App Password (requires 2FA)
- Mailtrap (sandbox testing):
  - Use their SMTP host/port/credentials; view messages in Mailtrap UI
- Don’t hard-code credentials; enter them in the UI at runtime

## CSV samples

Participants:
```csv
name,email
Alice,alice@example.com
Bob,bob@example.com
Carol,carol@example.com
Dave,dave@example.com
```

Last matches:
```csv
giver_email,receiver_email
alice@example.com,bob@example.com
bob@example.com,carol@example.com
carol@example.com,dave@example.com
dave@example.com,alice@example.com
```

Forbidden pairs:
```csv
giver_email,receiver_email
alice@example.com,carol@example.com
bob@example.com,alice@example.com
```

## Troubleshooting

- “No valid matching found”: constraints may be too strict for the group size. Relax forbidden pairs or last matches, or add more participants.
- CSV validation: headers must match exactly; duplicate emails are not allowed.
- SMTP errors:
  - For port 587, uncheck “Use SSL” (the app uses STARTTLS).
  - Firewalls/VPNs may block outbound SMTP ports; test with Mailtrap if needed.

## Security notes

- Use provider-specific App Passwords where possible (e.g., Gmail).

## License

GNU GPL 3.0 — see `LICENSE`.