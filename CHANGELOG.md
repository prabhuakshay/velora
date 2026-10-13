# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-13

### Added

**Reconciliation**
- Check an Asset or Liability Account against your bank: enter the date and the balance the bank showed. A match is saved as a Reconciliation and the Account shows "Reconciled through" that date. A mismatch shows the difference and the Transactions since the last Reconciliation, so you can find what is missing. (#145)
- The Account page warns when a Reconciliation no longer matches because a Transaction was edited later, and says how far off it is. Undoing the edit makes it match again. (#146)
- See the latest Reconciliations and Statements on the Account page, with a full history page for each. A Reconciliation can be deleted after a confirmation. (#147)
- Upcoming and the daily digest remind you to reconcile an Account that has had activity in the last 30 days without a Reconciliation, or whose latest Reconciliation no longer matches. (#149)
- Reconciling is blocked in Privacy Mode, since a match would reveal the hidden balance.

**Credit cards**
- Pay a card Statement in several parts. A Statement counts as paid once its linked payments add up to its amount, and its payment Draft proposes only what is still owed. (#136)
- Link a payment to a Statement by hand, or unlink a wrong one, including an automatic match. (#125)
- Overpaying a Statement, or a period where refunds beat spending, now lowers the next Statements and the Forecast's card bills instead of being lost. (#143)

**Quick Add**
- A floating Quick Add button on app pages records a money event without leaving the page you are on. (#151)

### Changed

- A Liability is always shown as what is owed: a card payment lowers its balance, and a card in credit reads "in credit" instead of a red negative. (#132)
- Removing an Attachment now happens when you save the Transaction, so you can undo it and unsaved edits are kept. (#131)
- Home and the Transactions list load faster, and Home stays fast however much history you have. (#133, #135)

### Fixed

- Card Statement estimates and their payment Drafts now update whenever a card Transaction is recorded, edited, deleted or merged. (#124)
- A Statement of zero or a credit shows "Nothing to pay" instead of an overdue warning. (#126)
- "Post all ready" no longer posts Drafts dated in the future or card payments whose bill is still an estimate. (#122)
- Scheduled payments no longer auto-post again after you delete the Transaction that covered them, or post every missed date after an outage. (#121)
- After pausing and resuming a Schedule, the skipped due dates no longer show up as overdue in the Forecast. (#123)
- Deleting Attachments, Transactions or Accounts now always removes the stored files, even if storage is briefly down. (#130)

### Security

- Wrong current passwords on Change password now count toward the login lockout and are rate limited. (#127)
- In Privacy Mode, the Transactions list hides the amount filters and export, so totals can no longer be guessed through them. (#128)
- CI actions are pinned to exact versions, and dependency updates now cover Python, npm and GitHub Actions. (#129)

## [0.1.1] - 2026-10-12

### Added

- The release image now runs on arm64 hosts (Graviton, Ampere, Raspberry Pi) as well as amd64. (#118)

### Fixed

- The production stack now runs the published release image instead of building from a local checkout, so a host can deploy without one. Pin a version with `DOCKER_IMAGE_TAG`. (#113)
- `latest` now only moves to the highest stable release, so a hotfix on an older version no longer rolls hosts back. (#115)
- A release image is published only after all checks pass, and only for version tags on `main`. Malformed version tags are rejected right away. (#114, #116, #117)

## [0.1.0] - 2026-10-12

First release of Velora, a personal finance app.

### Added

**Accounts and net worth**
- Track asset, liability, income and expense accounts, with balances, and hide, merge or delete them.
- See net worth on the home page, as of any date, with a history chart. Individual accounts can be left out of it. (#28, #31)
- Get a 30-day balance forecast for each account, with a timeline and chart, and set a low-balance threshold that triggers a warning.

**Transactions**
- Record transactions split across several categories, with parties and tags. (#26)
- Search, filter and export transactions to CSV, with the list and details side by side.
- Attach receipts and documents to a transaction, up to 10 MB each, stored in private cloud storage. (#42, #43, #44, #45, #46)
- See attachment totals and storage usage on a Storage page.

**Categories, parties and tags**
- Organise spending into category groups and categories, with icons and colours, and hide what you no longer use.
- See each category's or party's activity, and merge duplicate parties and tags. (#8, #12)

**Quick Add and Drafts**
- Type a transaction in plain words with Quick Add, and AI turns it into a draft you can review, edit, post or reject. Failed attempts can be retried or discarded. (#51, #53)
- Review every pending draft in one inbox, start drafts by hand, and save one without an amount until you know it.

**Schedules, subscriptions and cards**
- Set up repeating payments that propose a draft on each due date, can post automatically, and flag missed payments.
- Velora spots steady repeated payments and suggests them as schedules for you to confirm or dismiss.
- Mark schedules as subscriptions to see their total cost and price history.
- Credit cards get proposed statements and payment drafts, and card EMIs can be created, tracked and foreclosed. (#63 to #74)

**Budgets**
- Set a monthly budget per category and an overall one, edit them inline, and see spent and expected spending as progress bars.
- Step back through past months, and see unbudgeted spending.

**Home and daily digest**
- A home dashboard with net worth, budgets and an Upcoming panel of what is due.
- A styled morning email digest of what is coming up, low balances, and budgets that are close to or over their limit.

**Privacy and security**
- Privacy Mode masks every amount and blocks edits until you turn it off with your password.
- Choose how amounts are grouped with a number format setting. (#32)
- Login lockout after repeated failed attempts, password reset, and custom error pages.

**Install and deploy**
- Install Velora on your phone or desktop as an app.
- A production Docker image is published to GitHub Container Registry for each release.


[Unreleased]: https://github.com/prabhuakshay/velora/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/prabhuakshay/velora/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/prabhuakshay/velora/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/prabhuakshay/velora/releases/tag/v0.1.0
