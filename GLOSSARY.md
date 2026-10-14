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
What an Asset or Liability Account holds now: its Opening Balance moved by every Split into or out of it. For a Liability Account it is what the user owes. Amounts shown for a Liability Account always read as what is owed: + is charged, − is paid off. A negative Balance is shown as in credit.
_Avoid_: Total, net

**Reconciliation**:
The user's check that an Asset or Liability Account's Balance on a given day matches what the bank or card issuer says it held that day. It is recorded only when the two match, and every Split into or out of that Account dated on or before that day then counts as reconciled. A later change can move the Balance on that day, such as editing or back-dating a Transaction; the Reconciliation then no longer matches and shows how far off it is until the user fixes the difference or deletes it. The latest matching one gives the Account's reconciled-through date. Every Reconciliation is kept.
_Avoid_: Confirm, verify, audit, cleared

**Net Worth**:
What the user owns minus what they owe on a given day: the Balances of Asset Accounts minus the Balances of Liability Accounts, leaving out any Account the user has excluded from it, such as a car. An Investment Account counts at its Market Value, not its Balance.
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

**Untracked object**:
A stored file no Attachment points to any more, left behind when deleting it from storage failed for good or a crash interrupted an upload. It only wastes storage; nothing in Velora can reach it.
_Avoid_: Orphan, stray file, leaked file

**Quick Add**:
A short line of free text the user writes about a money event, such as "lunch at Toit 850 on hdfc card", which an AI reads to propose a Draft. Every Quick Add is Processing, Draft (its Draft awaits the user), Failed, Posted or Rejected.
_Avoid_: Prompt, quick entry, note

**Draft**:
A Transaction not yet posted, which the AI proposed from a Quick Add, a Schedule proposed on its due date, a credit card's Statement proposed as its payment, a Card EMI proposed for the interest, GST and fees billed with an installment, an Investment Import proposed for a Buy, Sell or Dividend with no matching Transaction, or the user started by hand as a placeholder. A Draft can carry a Buy, Sell or Dividend; posting it records the Transaction and the linked Investment Event together, and is refused while its units or Amount are missing. Every Draft shows which of these it came from. It needs only a date until it is posted, so it can wait for an amount the user does not know yet. It touches no Balance until the user posts it. The user can edit it and save it still waiting, gaps and all, or save and post it in one go, which is refused while anything is missing; the user can also reject it. A Draft dated after today can be posted early on its own, and is then recorded on today's date; posting all ready Drafts at once leaves it waiting for its day.
_Avoid_: Pending transaction, suggestion, draft entry

**Processing**:
A Quick Add the AI is still working on, which has no Draft yet. One still Processing five minutes after its job started is stalled, so the user can retry or discard it; time spent queued behind other jobs doesn't count.
_Avoid_: Pending, queued, in progress

**Failed**:
A Quick Add the AI could not turn into a valid Draft. The user can retry it, resubmit it with edited text, or discard it.
_Avoid_: Errored, invalid, broken

**Posted**:
A Quick Add whose Draft the user recorded as a Transaction, with or without edits.
_Avoid_: Accepted, approved, confirmed

**Rejected**:
A Quick Add the user dropped, by rejecting its Draft or discarding it after it failed or stalled. It is kept, but no longer waits for the user.
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
An Occurrence whose Draft the user posted, or that a Transaction the user recorded themselves already covers. A recorded Transaction covers it when it moves every Split of the Schedule, is for the Schedule's Party if it has one, and falls within a few days of the due date, fewer for daily and weekly Schedules.
_Avoid_: Done, settled, fulfilled

**Missed**:
An Occurrence with no Transaction covering it by the end of its Schedule's grace period after the due date, such as salary that has not arrived. A recorded Transaction can still make it Paid until 30 days after the due date; after that it stays Missed.
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
One billing period of a credit card, from the day after one Statement Day to the next, with its Due Day and Statement Amount. It is paid once the payments the user posts or records for it add up to its Statement Amount. A payment pays at most one Statement.
_Avoid_: Bill, invoice, cycle

**Statement Amount**:
What a credit card's latest statement asks the user to pay. Velora estimates it from the card's spending, payments and refunds in the Statement's period until the user enters the actual amount from the real statement, which then replaces the estimate. A payment linked to an earlier Statement paid for that period, so the estimate leaves it out and takes off the earlier Statement's Carried Credit instead. An estimate is never below zero.
_Avoid_: Bill, outstanding, total due

**Carried Credit**:
What a Statement leaves for the next one: how far its payments went beyond its Statement Amount, or how far its activity fell below zero. It lowers the next Statement Amount, never below zero, and what is still left carries on. An actual Statement Amount from the bank already counts it.
_Avoid_: Overpayment, credit balance, excess, rollover

**Refund**:
A Split from an Expense Account back to an Asset or Liability Account, which reduces what was spent under that Expense Account.
_Avoid_: Return, reversal, income

**Budget**:
The most the user plans to spend under one Expense Account in a calendar month. It holds every month until the user changes it; a change reaches back to the start of the current month, never earlier.
_Avoid_: Limit, cap, envelope, allowance

**Overall Budget**:
The most the user plans to spend across all Expense Accounts in a calendar month, Unbudgeted spending included. It is optional and set apart from the Budgets, which may add up to more than it.
_Avoid_: Total budget, monthly budget, spending limit

**Spent**:
What went out under an Expense Account in a calendar month through posted Transactions, less Refunds dated that month. It can fall below zero.
_Avoid_: Spending, used, actual

**Expected**:
What Upcoming Occurrences and waiting Drafts dated in the month are set to add to Spent once posted. It never counts as Spent.
_Avoid_: Committed, pending, planned

**Unbudgeted**:
Spent under Expense Accounts that have no Budget.
_Avoid_: Uncategorised, other

**Merge**:
Folding one Party into another, one Tag into another, or one Account into another of the same kind. The source disappears and everything that pointed at it points at the target.
_Avoid_: Transfer, combine, consolidate

**Number Format**:
How the user chooses to see amounts grouped: Indian, in lakhs and crores (₹12,34,567.89), or International, in thousands and millions (₹1,234,567.89). It changes only how amounts look, never their value.
_Avoid_: Locale, currency format

**Privacy Mode**:
A setting that masks every amount Velora shows, so someone who sees the screen can't learn what the user has, owes or spends. It changes only what is shown, never any value.
_Avoid_: Hide amounts, stealth mode, incognito

**Investment Account**:
An Asset Account for one place the user holds Instruments, such as a broker or a mutual fund platform. Its Balance is the money the user moved into it less what came out; what it is worth is its Market Value. It either Holds Cash or is Direct, and this never changes.
_Avoid_: Portfolio, demat, folio, broker account

**Holds Cash**:
An Investment Account that keeps money of its own between Buys and Sells, such as a broker. Money reaches it by an ordinary Transfer from a bank, and a Buy or Sell inside it moves no money in the ledger, only between its Cash and its Holdings.
_Avoid_: Broker mode, wallet

**Direct**:
An Investment Account with no money of its own, such as a mutual fund platform, where every Buy is paid straight from its Pays from Asset Account and every Sell pays straight into its Pays into Asset Account. Its Cash is always zero.
_Avoid_: Platform mode, pass-through

**Cash**:
The money an Investment Account that Holds Cash has not put into Instruments, as the broker would report it.
_Avoid_: Funds, margin, free balance

**Instrument**:
Something the user can hold units of, identified by its ISIN: a mutual fund scheme, a stock or an ETF. Two Instruments are never the same thing under different names.
_Avoid_: Security, scrip, scheme, ticker, asset

**Price**:
What one unit of an Instrument was worth at the end of a day: a mutual fund's NAV or a stock's or ETF's closing price. The latest Price is used until a newer one arrives, and is Stale once it is more than five days old.
_Avoid_: NAV, quote, rate, LTP

**Trade Price**:
What one unit changed hands at in a Buy or Sell: its amount, before charges, divided by its units. It is worked out, never entered or stored, and shown to four decimals like a Price. It is not the day's Price, though for a mutual fund it is usually close to that day's NAV.
_Avoid_: Price (on its own), rate, cost per unit

**Investment Event**:
One dated thing that happened to the user's units of an Instrument in an Investment Account: a Buy, Sell, Dividend, Stock Split, Bonus or Merger.
_Avoid_: Trade, investment transaction, order

**Buy**:
An Investment Event that adds units at a Trade Price, costing their amount plus charges such as brokerage, STT and stamp duty. Every Buy starts a Lot.
_Avoid_: Purchase, investment, subscription

**Sell**:
An Investment Event that removes units at a Trade Price, taken from the oldest Lots first. What it brings in less the Cost Basis of those units is its Realized Gain.
_Avoid_: Redemption, withdrawal, exit

**Dividend**:
An Investment Event that pays the user money for holding an Instrument, without changing units. It is Income, linked to the Holding it came from.
_Avoid_: IDCW, payout, distribution

**Stock Split**:
An Investment Event that multiplies every Lot's units of an Instrument by a ratio, leaving their Cost Basis unchanged.
_Avoid_: Split (that is part of a Transaction), subdivision

**Bonus**:
An Investment Event that gives free units of an Instrument, starting a Lot with no Cost Basis dated the day of the Bonus.
_Avoid_: Bonus issue, free units

**Merger**:
An Investment Event that turns every Lot of one Instrument into units of another, keeping each Lot's date and Cost Basis, such as when a fund house merges two schemes.
_Avoid_: Switch, conversion, amalgamation

**Lot**:
Units of one Instrument the user got together in one Buy or Bonus, with the date and Cost Basis they came at. A Sell takes from the oldest Lots first.
_Avoid_: Tranche, purchase, position

**Holding**:
All the units of one Instrument the user has in one Investment Account: its open Lots.
_Avoid_: Position, investment, stock

**Cost Basis**:
What the user paid, charges included, for the units still held. Also shown as Invested.
_Avoid_: Average price, invested amount, principal

**Market Value**:
What Holdings are worth at their latest Prices. For an Investment Account, its Cash plus the Market Value of its Holdings.
_Avoid_: Current value, worth, NAV value

**Unrealized Gain**:
Market Value less Cost Basis for units still held. It is negative when they are worth less than they cost.
_Avoid_: Paper profit, returns, P&L

**Realized Gain**:
What a Sell brought in less the Cost Basis of the units it took. It is negative for a loss.
_Avoid_: Profit, booked gain, capital gain

**XIRR**:
The yearly return that explains every Buy, Sell and Dividend by its date along with today's Market Value, so money invested longer counts for more.
_Avoid_: CAGR, return %, annualised return

**SIP**:
A Schedule that buys one Instrument for a set amount on each due date. Its Draft fills in the units from that day's Price.
_Avoid_: Recurring investment, systematic plan

**Investment Import**:
A CSV file of Investment Events, in Velora's own format, that the user fills in and uploads. It is checked in full and applied all at once or not at all, and uploading the same Investment Events again adds nothing. An Investment Export writes the same format back out.
_Avoid_: CAS import, statement upload, tradebook

**Goal**:
Something the user is saving for, such as a house or a child's education, with a target amount in today's money, a target date, and the inflation and expected return the user assumes for it. Goals only show progress and never change a Balance or Market Value.
_Avoid_: Piggy bank, target, savings pot, envelope

**Allocation**:
The share of an Asset Account or Holding counted toward a Goal, as a percentage or a fixed amount. One Account or Holding's Allocations never add up to more than all of it; what is left is unallocated.
_Avoid_: Earmark, assignment, contribution

**Goal Progress**:
What a Goal's Allocations are worth now, at Market Value for Holdings and Balance for other Asset Accounts. A fixed-amount Allocation counts for no more than what it is allocated from.
_Avoid_: Saved, funded, achieved amount

**Projection**:
What a Goal's Progress is expected to grow to by its target date, at its expected return and with the SIPs and other Schedules linked to it carrying on unchanged until the target date or their end. The Goal is on track when the Projection reaches the inflated target, and behind by the gap when it does not.
_Avoid_: Forecast (that is the next 30 days of Balances), estimate

**Required Monthly Investment**:
What the user would need to add every month, at the Goal's expected return, for its Projection to reach the inflated target.
_Avoid_: Required SIP, monthly target, shortfall
