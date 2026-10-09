# Single user, no data ownership

Velora serves one person, so budget data (categories, expense accounts, and later transactions) has no owner and names are unique across the whole app. Login still guards the app because it is internet-facing, and change history still records who changed what and when. Adding multiple users later means backfilling an owner onto every row and scoping every query, which we accept in exchange for simpler models, forms and views now.
