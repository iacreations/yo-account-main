# utils for GL posting
from decimal import Decimal
from accounts.models import Account, JournalEntry, JournalLine

UNCATEGORIZED_EXP_NAME = "Uncategorized Expense"

def _get_uncategorized_expense_account():
    acc = Account.objects.filter(account_name=UNCATEGORIZED_EXP_NAME).first()
    if acc:
        return acc
    # Create a simple EXPENSE account as a fallback
    return Account.objects.create(
        account_name=UNCATEGORIZED_EXP_NAME,
        account_type="EXPENSE",
        detail_type="Other Expenses",
        description="Auto-created fallback for item lines without an expense account."
    )


def post_expense_to_gl(expense):
    """
    Create a JournalEntry for the given Expense.
    DR: each category/item line to its expense account
    CR: payment account with total amount
    """
    # 1) Journal entry header
    ref = expense.ref_no or f"EXP-{expense.pk}"
    who = (expense.payee_supplier.company_name
           if expense.payee_supplier else (expense.payee_name or "Payee"))
    desc = f"Expense from {who} with Ref- {ref}"
    entry = JournalEntry.objects.create(
        date=expense.payment_date,
        description=desc,
    )

    total_credit = Decimal("0.00")

    # 2) Debit: Category (GL) lines
    for cl in expense.cat_lines.select_related("category").all():
        if not cl.amount or cl.amount == 0:
            continue
        JournalLine.objects.create(
            entry=entry,
            account=cl.category,
            debit=cl.amount,
            credit=Decimal("0.00"),
        )
        total_credit += cl.amount

    # 3) Debit: Item lines → product expense/COGS account (or fallback)
    for il in expense.item_lines.select_related("product").all():
        if not il.amount or il.amount == 0:
            continue
        prod = il.product
        # Try common field names used in product models
        exp_acc = getattr(prod, "expense_account", None) or getattr(prod, "cogs_account", None)
        if exp_acc is None:
            exp_acc = _get_uncategorized_expense_account()
        JournalLine.objects.create(
            entry=entry,
            account=exp_acc,
            debit=il.amount,
            credit=Decimal("0.00"),
        )
        total_credit += il.amount

    # 4) Credit: Payment account (single line with total)
    if total_credit and expense.payment_account:
        JournalLine.objects.create(
            entry=entry,
            account=expense.payment_account,
            debit=Decimal("0.00"),
            credit=total_credit,
        )

    return entry
