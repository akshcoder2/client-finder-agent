# Contributing

Thanks for helping improve Client Finder Agent.

## Getting set up

```bash
git clone <your-fork-url>
cd client-finder-agent
python3 -m pip install -r requirements.txt
python3 -m pip install -e .   # optional: editable install
python3 agent.py demo         # offline demo, no API keys, no network, no sending
python3 -m pytest -q
```

The test suite is fully offline: it uses a temporary SQLite database and fake
Gmail services. Never add tests that send real email or call Google APIs.

## Ground rules for changes

- **No login-based scraping.** Google Maps data must come from the official
  Places API; LinkedIn data must come from a user's own CSV export or an
  authorised API. PRs that automate scraping of logged-in pages will be declined.
- **Sending stays explicit.** `send` is a dry run unless `--live` is passed, and
  only approved drafts may be sent. Do not add silent auto-send behaviour.
- **Keep opt-outs working.** The suppression list, opt-out footer, and
  `check-replies` must keep functioning.
- **No secrets in the repo.** `.env`, `config.yaml`, `credentials.json`,
  `token.json`, `data/` and `output/` are gitignored. Use the `.example` files.
- Keep emails honest: no fabricated personalisation or misleading claims.

## Pull requests

1. Fork and create a feature branch.
2. Add or update tests for your change.
3. Run `python3 -m pytest -q`.
4. Open a PR describing what changed and why.

## Reporting bugs

Open an issue with the command you ran, the expected result, what happened, and
your Python version. Remove any real names, email addresses, or API keys from
logs before pasting them.
