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

**Transfer**:
A Transaction whose Splits only move money between Asset and Liability Accounts, such as withdrawing cash or paying a credit card bill.
_Avoid_: Move, internal transaction

**Refund**:
A Split from an Expense Account back to an Asset or Liability Account, which reduces what was spent under that Expense Account.
_Avoid_: Return, reversal, income

**Merge**:
Folding one Party into another, one Tag into another, or one Account into another of the same kind. The source disappears and everything that pointed at it points at the target.
_Avoid_: Transfer, combine, consolidate
