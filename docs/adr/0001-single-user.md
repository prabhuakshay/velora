# Single user, no data ownership

Velora serves one person, so budget data (Accounts, Parties, Tags, and later Transactions) has no owner and names are unique across the whole app (Account names are unique within their kind, so an Expense and an Income Account can share a name). Login still guards the app because it is internet-facing, and change history still records who changed what and when. Adding multiple users later means backfilling an owner onto every row and scoping every query, which we accept in exchange for simpler models, forms and views now.
