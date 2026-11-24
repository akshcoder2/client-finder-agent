# Publish to GitHub (2 minutes)

The repository is already initialised, committed, tested and MIT-licensed.
Only the GitHub remote is missing. Follow these steps on your own computer or
in a terminal where you are logged in to GitHub.

## 1. Create the empty repo on GitHub

1. Open <https://github.com/new> while signed in.
2. **Repository name:** `client-finder-agent`
3. **Description:** `Find local clients, draft personal outreach and send approved emails through Gmail`
4. Choose **Public**.
5. **Do not** tick "Add a README", "Add .gitignore" or "Choose a license" — this project already has all three.
6. Click **Create repository**.

## 2. Copy the repository URL

GitHub shows a box labelled "Quick setup". Choose **HTTPS** and copy the URL. It looks like:

```
https://github.com/YOUR_USERNAME/client-finder-agent.git
```

## 3. Push the code

In a terminal, from the `client-finder-agent` folder:

```bash
bash scripts/publish.sh https://github.com/YOUR_USERNAME/client-finder-agent.git
```

If Git asks you to sign in, use your GitHub username and a **Personal Access Token**
as the password (GitHub no longer accepts account passwords for Git pushes).
Create one at <https://github.com/settings/tokens> with `repo` scope.

## Alternative: GitHub CLI

If you prefer `gh`:

```bash
gh auth login
gh repo create client-finder-agent --public --source=. --remote=origin --push
```

## After publishing

- Suggested topics: `lead-generation`, `outreach`, `gmail-api`, `google-places`, `python`, `automation`.
- The GitHub Actions workflow runs the 9 offline tests on every push and PR.
- Never commit `.env`, `config.yaml`, `credentials.json` or `token.json`.
