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
A Transaction not yet posted, which the AI proposed from a Quick Add, a Schedule proposed on its due date, a credit card's Statement proposed as its payment, or the user started by hand as a placeholder. Every Draft shows which of these it came from. It needs only a date until it is posted, so it can wait for an amount the user does not know yet. It touches no Balance until the user posts it. The user can edit it and save it still waiting, gaps and all, or save and post it in one go, which is refused while anything is missing; the user can also reject it. A Draft dated after today can be posted early, and is then recorded on today's date.
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

**Schedule**:
A Transaction the user expects to repeat, such as rent, salary or a phone bill, with how often it repeats and optionally when it stops. On each due date it proposes a Draft, or posts the Transaction itself if the user trusts it to. Its amount can be left open when it changes every time.
_Avoid_: Recurring transaction, standing order, bill

**Occurrence**:
One dated instance of a Schedule. Every Occurrence is Upcoming, Drafted, Paid, Skipped or Missed.
_Avoid_: Instance, installment, due

**Paid**:
An Occurrence whose Draft the user posted, or that a Transaction the user recorded themselves already covers.
_Avoid_: Done, settled, fulfilled

**Missed**:
An Occurrence with no Transaction covering it by the end of its Schedule's grace period after the due date, such as salary that has not arrived.
_Avoid_: Late, overdue, failed

**Subscription**:
A Schedule the user marks as paying for an ongoing service, such as a streaming plan or a domain, which can carry a trial end, a plan and a way to cancel.
_Avoid_: Membership, plan, recurring payment

**Suggested Schedule**:
A Schedule Velora proposes after noticing the user pays the same Party a similar amount at a steady interval. It does nothing until the user confirms it; a dismissed one is never suggested again.
_Avoid_: Detected subscription, candidate

**Forecast**:
The Balances Velora expects each Asset and Liability Account to have on each of the next 30 days, from upcoming Occurrences, unposted Drafts and credit card payments.
_Avoid_: Projection, cash flow, prediction

**Low-Balance Threshold**:
The point past which the user wants a warning when the Forecast expects an Account to cross it. For an Asset Account it is a floor: the warning comes when the Balance is expected to fall below it. For a Liability Account it is a ceiling on what is owed, such as a card limit: the warning comes when the amount owed is expected to go above it, and 0 means no warning.
_Avoid_: Minimum balance, alert level

**Card EMI**:
A purchase on a credit card that the bank bills in equal monthly installments, with interest, instead of all at once. The whole purchase counts as spent the day it was made; only the installments reach each Statement Amount. It can be foreclosed by paying off the rest early.
_Avoid_: Installment plan, loan, EMI conversion

**Statement Day**:
The day of the month a credit card's Liability Account closes its billing period.
_Avoid_: Billing date, cycle date

**Due Day**:
The day of the month the amount on a credit card's latest statement must be paid by.
_Avoid_: Payment date, deadline

**Statement**:
One billing period of a credit card, from the day after one Statement Day to the next, with its Due Day and Statement Amount. It is paid once a payment the user posts or records covers it.
_Avoid_: Bill, invoice, cycle

**Statement Amount**:
What a credit card's latest statement asks the user to pay. Velora estimates it until the user enters the actual amount from the real statement, which then replaces the estimate.
_Avoid_: Bill, outstanding, total due

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
