# Client Finder + Outreach Agent

A small, schedulable Python agent that:

1. **Finds** local businesses via the official **Google Places API (New)** and imports **LinkedIn / Sales Navigator CSV exports**.
2. **Enriches** them by finding real contact emails on their websites and scoring the best leads.
3. **Drafts** short, personal emails (free built-in templates, or optional LLM).
4. **Sends** only approved emails through **your Gmail** — with a hard daily cap, business-hours window, spacing, and a suppression list.
5. **Reports** everything to `output/leads.csv`, a reviewable HTML page, and optionally Google Drive / Sheets.

Nothing is sent unless you explicitly approve it and run `send --live`.

---

## Quick start

```bash
cd client-finder-agent
python3 -m pip install -r requirements.txt
python3 agent.py init          # creates config.yaml + .env
python3 agent.py demo          # offline sample run — no API keys, no network, no sending
```

Open `output/outreach-preview.html` to see the drafted emails, and `output/leads.csv` for the lead sheet.

> The demo uses invented businesses and addresses. It never contacts anyone.

---

## Real setup (one time)

### 1. Google Cloud

In [Google Cloud Console](https://console.cloud.google.com/):

- **Enable APIs:** *Places API (New)*, *Gmail API*, *Google Drive API*.
- **Places key:** Credentials → Create API key → restrict it to Places API (New) → put it in `.env` as `GOOGLE_MAPS_API_KEY`.
- **OAuth client:** Credentials → Create OAuth client ID → *Desktop app* → download JSON and save it in this folder as **`credentials.json`**.
- If your app is in *Testing* mode, add your own Google account as a **test user**.
- First real send/upload opens a browser to sign in. The resulting `token.json` is stored locally with `0600` permissions.

### 2. LinkedIn

LinkedIn's terms do **not** allow automated scraping of logged-in search results, so this agent doesn't do that. Instead:

- Search in LinkedIn or Sales Navigator, then **Export the results to CSV** from the UI.
- Save it as `input/linkedin.csv` and list it in `config.yaml` under `targets`.
- Common column names are auto-detected (`First Name`, `Last Name`, `Company`, `Email Address`, `Profile URL`, `Title`, `Location`). If an email column is present, it is used directly at `high` confidence.

### 3. Edit `config.yaml`

Set your name, company, offer, signature, physical address, target searches (niche + city), daily cap, and send window. Set `llm.enabled: true` only if you want LLM-written emails and have set `LLM_API_KEY` in `.env`.

---

## Daily commands

| Command | What it does |
| --- | --- |
| `python3 agent.py run` | Full discovery pipeline: find/import → enrich → draft → export. **Never sends.** |
| `python3 agent.py review` | Print all drafts to check them. |
| `python3 agent.py approve --high-confidence` | Approve only leads whose email was found on their website. |
| `python3 agent.py approve --id 3` | Approve one draft by ID. |
| `python3 agent.py send` | Dry run: shows the queue and remaining daily cap. |
| `python3 agent.py send --live` | Actually send approved emails through Gmail. |
| `python3 agent.py check-replies` | Scan replies for "no thanks"/"unsubscribe" and auto-suppress those addresses. |
| `python3 agent.py suppress --email someone@example.com` | Manually add to the do-not-contact list. |
| `python3 agent.py report --drive --sheet` | Export CSV/HTML and upload the CSV to Drive as a Google Sheet. |
| `python3 agent.py stats` | Show counts (leads, drafts, sends today, suppressed). |

Useful flags: `find --query "dentist" --location "Indore, India" --limit 20`, `import --file input/linkedin.csv`, `send --limit 10`, `send --live --ignore-window`.

---

## Scheduling (background automation)

Example crontab — discovery in the morning, sending only during business hours:

```cron
0 7 * * *  cd /home/user/client-finder-agent && python3 agent.py run >> logs/run.log 2>&1
0 10 * * 1-5 cd /home/user/client-finder-agent && python3 agent.py approve --high-confidence >> logs/send.log 2>&1
15 10 * * 1-5 cd /home/user/client-finder-agent && python3 agent.py send --live >> logs/send.log 2>&1
30 18 * * * cd /home/user/client-finder-agent && python3 agent.py check-replies >> logs/replies.log 2>&1
```

Keep `send --live` on a weekday schedule and leave `min_delay_seconds` at 90–180. The daily cap is enforced from the local SQLite history, even if the cron job is retried.

---

## Safety and compliance

- **Manual review is the default.** Only `--live` sends, and only approved drafts.
- Email addresses scraped from websites are `high`/`medium` confidence. Pattern-guessed addresses are labelled `guessed` and can never be auto-approved.
- Every email includes a plain-English opt-out line and a `List-Unsubscribe` header; `check-replies` adds opt-outs to a permanent suppression list.
- CAN-SPAM requires a valid physical address and honest subject lines; GDPR applies to contacts in the EU/UK. Adjust the footer and targeting to your jurisdiction.
- Respect platform terms: this tool uses Google's paid/public Places API and **manual** LinkedIn CSV exports — no logged-in scraping, no fake accounts, no bulk connection requests.
- Consumer Gmail allows roughly 500 sends/day and Workspace around 2,000. For cold outreach, stay well below that, warm up the mailbox, and prefer a dedicated sending domain/address. Deliverability is not guaranteed.
- Send one short, relevant email. No fake personalisation, no misleading claims.

---

## Project layout

```
agent.py                 CLI entry point
config.yaml              your settings (created by init)
.env                     API keys / OAuth paths (created by init)
input/linkedin.csv       your manual LinkedIn export
cfagent/
  config.py              config loading
  db.py                  SQLite: leads, emails, sends, suppression
  sources.py             Places API search + LinkedIn CSV import
  enrich.py              website email discovery + lead scoring
  drafting.py            templates + optional LLM drafts
  google_client.py       Gmail send, reply scan, Drive upload
  reports.py             CSV + HTML preview
  cli.py                 all commands
tests/                   offline unit tests (pytest -q)
output/                  generated reports
```

Run tests with `python3 -m pytest -q`. They use fake data and never touch the network.

---

## Contributing and licence

Open source under the [MIT licence](LICENSE). Contributions are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md) for setup and the project's ground rules
(no logged-in scraping, no silent auto-send, no secrets in commits). Security
issues should be reported privately as described in [SECURITY.md](SECURITY.md).

> This project is a tool, not a permission slip. You are responsible for
> following the law and the terms of the platforms you use in your jurisdiction.
