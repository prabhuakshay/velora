- Checks: `uv run prek run --all-files`, then `uv run pytest`. Hooks reject the commit on failure.
- GitHub identity is `prabhuakshay`; set git credentials locally (`gh auth setup-git`), never globally.
- Client IP: `get_client_ip` with the axes trusted-proxy setting in `config/settings.py`.

## Agent skills

### Issue tracker

GitHub Issues (`prabhuakshay/velora`) via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
