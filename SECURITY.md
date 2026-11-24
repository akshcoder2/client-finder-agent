# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for a security problem. Email the
maintainers privately (or use GitHub's private vulnerability reporting if
enabled) with a description, reproduction steps, and the affected version.
You should receive an acknowledgement within a week.

## Handling credentials

This tool touches Gmail, Google Drive and a billable Google Maps API key.

- Never commit `.env`, `config.yaml`, `credentials.json` or `token.json`.
- Restrict the Places API key to the Places API (New) and, if possible, to your
  server's IP address.
- If a key or OAuth token leaks, revoke it in Google Cloud immediately and
  rotate it. Delete `token.json` and re-authenticate.
- The local SQLite database in `data/` contains prospect contact details.
  Treat it as personal data: store it securely and delete it when no longer
  needed.

## Scope

Vulnerabilities in the agent's own code, dependency injection through config
files, and accidental disclosure of contact data are in scope. Abuse of Google
or LinkedIn APIs, or mass unsolicited mailing, is not a supported use of this
project.
