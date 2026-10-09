# Velora

A self-hosted personal finance manager for one person, who records the money they earn, spend and move between accounts, and uses that record to budget and see where their money goes.

## Language

**Party**:
Someone outside the user who money is paid to or received from, such as a shop, employer, landlord or friend. The same Party can be on both incoming and outgoing money.
_Avoid_: Payee, payer, counterparty, merchant, vendor

**Tag**:
A free-form label the user attaches to money movements to group them across Parties and accounts, such as a trip or "reimbursable". It plays no part in budgeting.
_Avoid_: Label, category

**Expense Account**:
A bucket that spent money is budgeted and reported under, such as Groceries or Rent.
_Avoid_: Category, envelope

**Income Account**:
A bucket that earned money is reported under, such as Salary or Interest.
_Avoid_: Category, income source

**Merge**:
Folding one Party into another, or one Tag into another. The source disappears and everything that pointed at it points at the target.
_Avoid_: Transfer, combine, consolidate
