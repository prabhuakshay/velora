# Drafts are kept apart from Transactions

A Draft is stored as its own record, not as a Transaction with a draft status, and only becomes a Transaction when the user posts it. Every Balance, Net Worth and report query reads Transactions and Splits directly; a status flag would force each of them to filter drafts out, and one forgotten filter would silently show wrong numbers. Keeping Drafts apart means a Draft can never move a Balance, at the cost of a second, smaller shape that has to be validated again and copied into a Transaction at post time.
