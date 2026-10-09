# Velora

A completely vibe-coded personal finance app for personal use.

## Attachment storage

Attachments need a private Cloudflare R2 bucket in dev and prod. Run
`./scripts/r2-setup.sh` to create the bucket and API token for one
environment; it writes the `R2_*` values to `.env.r2-dev` or
`.env.r2-prod` for you to paste into `.env`.
