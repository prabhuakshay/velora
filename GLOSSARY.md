# Velora

A self-hosted personal finance manager for one person, who records the money they earn, spend and move between accounts, and uses that record to budget and see where their money goes.

## Language

**Party**:
Someone outside the user who money is paid to or received from, such as a shop, employer, landlord or friend. The same Party can be on both incoming and outgoing money.
_Avoid_: Payee, payer, counterparty, merchant, vendor

**Tag**:
A free-form label the user attaches to Splits to group them across Parties and Accounts, such as a trip or "reimbursable". It plays no part in budgeting.
_Avoid_: Label, category

**Account**:
Anything money moves from or to. Every Account is exactly one of Asset, Liability, Income or Expense, and never changes kind. Never used for the user's login.
_Avoid_: Ledger, head, wallet

**Asset Account**:
An Account for something the user owns or is owed, such as a bank account, cash in hand or money lent to a friend.
_Avoid_: Wallet, bank

**Liability Account**:
An Account for money the user owes, such as a credit card or a loan.
_Avoid_: Debt, credit account

**Expense Account**:
An Account that spent money is budgeted and reported under, such as Groceries or Rent.
_Avoid_: Category, envelope

**Income Account**:
An Account that earned money is reported under, such as Salary or Interest.
_Avoid_: Category, income source

**Opening Balance**:
What an Asset or Liability Account held on the day the user started recording it in Velora.
_Avoid_: Initial balance, starting amount

**Balance**:
What an Asset or Liability Account holds now: its Opening Balance moved by every Split into or out of it. For a Liability Account it is what the user owes.
_Avoid_: Total, net

**Net Worth**:
What the user owns minus what they owe on a given day: the Balances of Asset Accounts minus the Balances of Liability Accounts, leaving out any Account the user has excluded from it, such as a car.
_Avoid_: Wealth, total balance, equity

**Transaction**:
One real-world money event, such as paying a bill or receiving salary, with a date and optionally a Party. It is made of one or more Splits, which all come from the same Account or all go to the same Account.
_Avoid_: Entry, journal, payment

**Split**:
One part of a Transaction that moves an amount from one Account to another, and can carry Tags.
_Avoid_: Line, leg, posting

**Attachment**:
A file the user keeps with a Transaction as evidence or reference, such as a receipt, invoice or warranty card. It belongs to the whole Transaction, not to any one Split.
_Avoid_: Receipt, document, file

**Quick Add**:
A short line of free text the user writes about a money event, such as "lunch at Toit 850 on hdfc card", which an AI reads to propose a Draft. Every Quick Add is Processing, Draft (its Draft awaits the user), Failed, Posted or Rejected.
_Avoid_: Prompt, quick entry, note

**Draft**:
A Transaction the AI proposed from a Quick Add that the user has not yet posted. It touches no Balance until the user posts it; the user can also edit or reject it.
_Avoid_: Pending transaction, suggestion, draft entry

**Processing**:
A Quick Add the AI is still working on, which has no Draft yet.
_Avoid_: Pending, queued, in progress

**Failed**:
A Quick Add the AI could not turn into a valid Draft. The user can retry it, resubmit it with edited text, or discard it.
_Avoid_: Errored, invalid, broken

**Posted**:
A Quick Add whose Draft the user recorded as a Transaction, with or without edits.
_Avoid_: Accepted, approved, confirmed

**Rejected**:
A Quick Add the user dropped, by rejecting its Draft or discarding it after it failed. It is kept, but no longer waits for the user.
_Avoid_: Deleted, cancelled, dismissed

**Discard**:
Dropping a Failed Quick Add, which marks it Rejected.
_Avoid_: Delete, dismiss, reject

**AI call**:
One request Velora makes to the AI for a Quick Add, kept with what it cost whether or not it produced a Draft.
_Avoid_: Completion, API call, request

**Transfer**:
A Transaction whose Splits only move money between Asset and Liability Accounts, such as withdrawing cash or paying a credit card bill.
_Avoid_: Move, internal transaction

**Refund**:
A Split from an Expense Account back to an Asset or Liability Account, which reduces what was spent under that Expense Account.
_Avoid_: Return, reversal, income

**Merge**:
Folding one Party into another, one Tag into another, or one Account into another of the same kind. The source disappears and everything that pointed at it points at the target.
_Avoid_: Transfer, combine, consolidate

**Number Format**:
How the user chooses to see amounts grouped: Indian, in lakhs and crores (₹12,34,567.89), or International, in thousands and millions (₹1,234,567.89). It changes only how amounts look, never their value.
_Avoid_: Locale, currency format

**Privacy Mode**:
A setting that masks every amount Velora shows, so someone who sees the screen can't learn what the user has, owes or spends. It changes only what is shown, never any value.
_Avoid_: Hide amounts, stealth mode, incognito
