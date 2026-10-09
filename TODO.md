# TODO

## When transactions land

- Deleting a Party that is in use must offer Merge into another Party instead. Force delete is not allowed for Parties.
- Deleting a Tag that is in use offers Merge into another Tag, or force delete, which removes the Tag from its transactions and keeps the transactions.
- Deleting an Account that is in use must offer Merge into another Account of the same kind. Force delete is not allowed for Accounts.
- Split direction rules: Income Accounts are only ever a source. Expense Accounts are a destination, or the source of a Refund to an Asset or Liability Account. A Split never goes from an Account to itself, or from Income to Expense.
