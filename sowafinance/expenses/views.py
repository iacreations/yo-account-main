# Create your views here.
from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
import json
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from .models import Expense, ExpenseCategoryLine, ExpenseItemLine,ColumnPreference,Bill, BillCategoryLine, BillItemLine
from sowaf.models import Newcustomer, Newsupplier
from accounts.models import Account,JournalEntry
from inventory.models import Product,Pclass
from .utils import generate_unique_ref_no
from .services import post_expense_to_gl

# Expenses view

DEFAULT_ACCOUNTS_COL_PREFS = {
    "payment_date": True,
    "payee_name": True,
    "payee_supplier": True,
    "payment_account": True,
    "payment_method": True,
    "ref_no": True,
    "memo": True,
    "attachments": True,  # keep actions togglable too
}
def expenses(request):
    qs = (
        Expense.objects
        .select_related("payee_supplier")
        .prefetch_related("cat_lines__category", "item_lines__product")
        .order_by("-payment_date", "-id")
    )

    # Optional: precompute line counts to avoid .count() hits in properties
    for e in qs:
        e._total_lines = (len(getattr(e, "cat_lines").all())
                          + len(getattr(e, "item_lines").all()))
    
    if getattr(request.user, "is_authenticated", False):
        prefs, _ = ColumnPreference.objects.get_or_create(
            user=request.user,
            table_name="accounts",
            defaults={"preferences": DEFAULT_ACCOUNTS_COL_PREFS},
        )
        merged_prefs = {**DEFAULT_ACCOUNTS_COL_PREFS, **(prefs.preferences or {})}
    else:
        merged_prefs = DEFAULT_ACCOUNTS_COL_PREFS

    return render(request, "expenses.html", {
        "expenses": qs,
        'column_prefs': merged_prefs
        })


@csrf_exempt
def save_column_prefs(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "detail": "POST required"}, status=400)

    try:
        data = json.loads(request.body or "{}")
        preferences = data.get("preferences", {})
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "detail": "Bad JSON"}, status=400)

    prefs, _ = ColumnPreference.objects.get_or_create(
        user=request.user,
        table_name="accounts",
    )
    # also ensure unknown keys don’t sneak in (optional)
    cleaned = {k: bool(preferences.get(k, True)) for k in DEFAULT_ACCOUNTS_COL_PREFS.keys()}
    prefs.preferences = cleaned
    prefs.save()
    return JsonResponse({"status": "ok"})
# adding an expense
def _dec(v, default="0.00"):
    try:
        return Decimal(str(v or default))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)

def add_expense(request):
    if request.method == "POST":
        try:
            with transaction.atomic():
                # Header
                payee_name      = request.POST.get("payee_name") or ""
                supplier_id     = request.POST.get("payee_supplier") or ""
                payment_account = get_object_or_404(Account, pk=request.POST.get("payment_account"))
                payment_date    = request.POST.get("payment_date") or timezone.localdate()
                payment_method  = request.POST.get("payment_method") or "cash"
                ref_no          = request.POST.get("ref_no") or ""
                location        = request.POST.get("location") or ""
                memo            = request.POST.get("memo") or ""
                attachment      = request.FILES.get("attachments")

                supplier = Newsupplier.objects.filter(pk=supplier_id).first() if supplier_id else None
                # ensure we have a valid 8-digit numeric ref; if not, generate one
                if not (len(ref_no) == 8 and ref_no.isdigit()):
                    ref_no = generate_unique_ref_no()
        # guard against the (very rare) race where the same ref got used meanwhile
                if Expense.objects.filter(ref_no=ref_no).exists():
                    ref_no = generate_unique_ref_no()
                exp = Expense.objects.create(
                    payee_name=payee_name,
                    payee_supplier=supplier,
                    payment_account=payment_account,
                    payment_date=payment_date,
                    payment_method=payment_method,
                    ref_no=ref_no,
                    location=location,
                    memo=memo,
                    attachments=attachment,
                )

                total = Decimal("0.00")

                # -------- Category lines --------
                cat_category_ids = request.POST.getlist("cat_category[]")
                cat_descs        = request.POST.getlist("cat_desc[]")
                cat_amounts      = request.POST.getlist("cat_amount[]")
                cat_billable     = set(request.POST.getlist("cat_billable[]"))  # contains row idx strings
                cat_customer_ids = request.POST.getlist("cat_customer[]")
                cat_class_ids    = request.POST.getlist("cat_class[]")

                for idx, cat_id in enumerate(cat_category_ids):
                    if not cat_id:
                        continue
                    category = Account.objects.filter(pk=cat_id).first()
                    if not category:
                        continue

                    amt = _dec(cat_amounts[idx])
                    if amt == 0:
                        continue

                    is_bill = str(idx) in cat_billable
                    customer = Newcustomer.objects.filter(pk=cat_customer_ids[idx] or None).first()
                    klass    = Pclass.objects.filter(pk=cat_class_ids[idx] or None).first()

                    ExpenseCategoryLine.objects.create(
                        expense=exp, category=category,
                        description=cat_descs[idx],
                        amount=amt, is_billable=is_bill,
                        customer=customer, class_field=klass
                    )
                    total += amt

                # -------- Item lines --------
                item_product_ids = request.POST.getlist("item_product[]")
                item_descs       = request.POST.getlist("item_desc[]")
                item_qtys        = request.POST.getlist("item_qty[]")
                item_rates       = request.POST.getlist("item_rate[]")
                item_amounts     = request.POST.getlist("item_amount[]")
                item_billable    = set(request.POST.getlist("item_billable[]"))
                item_customer_ids= request.POST.getlist("item_customer[]")
                item_class_ids   = request.POST.getlist("item_class[]")

                for idx, prod_id in enumerate(item_product_ids):
                    if not prod_id:
                        continue
                    product = Product.objects.filter(pk=prod_id).first()
                    if not product:
                        continue

                    qty  = _dec(item_qtys[idx], "0")
                    rate = _dec(item_rates[idx], "0")
                    amt  = _dec(item_amounts[idx]) or (qty * rate)

                    is_bill = str(idx) in item_billable
                    customer = Newcustomer.objects.filter(pk=item_customer_ids[idx] or None).first()
                    klass    = Pclass.objects.filter(pk=item_class_ids[idx] or None).first()

                    ExpenseItemLine.objects.create(
                        expense=exp, product=product,
                        description=item_descs[idx],
                        qty=qty, rate=rate, amount=amt,
                        is_billable=is_bill, customer=customer, class_field=klass
                    )
                    total += amt

                exp.total_amount = total
                exp.save(update_fields=["total_amount"])
                # posting to chart of accounts
                post_expense_to_gl(exp)
                messages.success(request, "Expense saved.")
                action = request.POST.get("save_action") or "save"
                if action == "save":
                    return redirect("expenses:expenses")
                if action == "save&new":
                    return redirect("expenses:add-expenses")
                # tweak ‘save&close’ destination as you wish:
                return redirect("expenses:expenses")

        except Exception as e:
            messages.error(request, f"Could not save expense: {e}")
    ref_no = generate_unique_ref_no()
    # GET: load form lists
    context = {
        "accounts": Account.objects.all().order_by("account_name"),
        "expense_accounts": Account.objects.filter(account_type__in=[
            "EXPENSE", "OTHER_EXPENSE", "COST_OF_SALES", "Expense", "Other Expenses", "Cost of Sales"
        ]).order_by("account_name"),
        "products": Product.objects.all().order_by("name"),
        "customers": Newcustomer.objects.all().order_by("customer_name"),
        "suppliers": Newsupplier.objects.all().order_by("company_name"),
        "classes": Pclass.objects.all().order_by("class_name"),
        "ref_no":ref_no,
        "payment_methods": Expense.PAYMENT_METHODS, 
    }
    return render(request, "expenses_form.html", context)
# expense list 
def expense_list(request):
    qs = (
        Expense.objects
        .select_related("payee_supplier", "payment_account")
        .prefetch_related("cat_lines__category", "item_lines__product")
        .order_by("-payment_date", "-id")
    )
    return render(request, "expenses_list.html", {"expenses": qs})
# expense detail
def expense_detail(request, pk: int):
    exp = get_object_or_404(
        Expense.objects
        .select_related("payee_supplier", "payment_account")
        .prefetch_related("cat_lines__category", "item_lines__product"),
        pk=pk
    )
    # Optional: get the journal if you linked it with FK expense
    je = JournalEntry.objects.filter(expense=exp).prefetch_related("lines__account").first()
    return render(request, "expense_detail.html", {"e": exp, "journal": je})
# expense edit
def expense_edit(request, pk: int):
    exp = get_object_or_404(
        Expense.objects
        .select_related("payee_supplier", "payment_account")
        .prefetch_related("cat_lines__category", "item_lines__product"),
        pk=pk
    )

    if request.method == "POST":
        try:
            with transaction.atomic():
                # ---- Header
                exp.payee_name      = request.POST.get("payee_name") or ""
                supplier_id         = request.POST.get("payee_supplier") or ""
                exp.payee_supplier  = Newsupplier.objects.filter(pk=supplier_id).first() if supplier_id else None
                exp.payment_account = get_object_or_404(Account, pk=request.POST.get("payment_account"))
                exp.payment_date    = request.POST.get("payment_date") or timezone.localdate()
                exp.payment_method  = request.POST.get("payment_method") or "cash"
                exp.ref_no          = request.POST.get("ref_no") or exp.ref_no or ""
                exp.location        = request.POST.get("location") or ""
                exp.memo            = request.POST.get("memo") or ""
                if request.FILES.get("attachments"):
                    exp.attachments = request.FILES["attachments"]
                exp.save()

                # ---- Replace lines
                ExpenseCategoryLine.objects.filter(expense=exp).delete()
                ExpenseItemLine.objects.filter(expense=exp).delete()

                total = Decimal("0.00")

                # Category lines
                cat_category_ids = request.POST.getlist("cat_category[]")
                cat_descs        = request.POST.getlist("cat_desc[]")
                cat_amounts      = request.POST.getlist("cat_amount[]")
                cat_billable     = set(request.POST.getlist("cat_billable[]"))
                cat_customer_ids = request.POST.getlist("cat_customer[]")
                cat_class_ids    = request.POST.getlist("cat_class[]")

                for idx, cat_id in enumerate(cat_category_ids):
                    if not cat_id:
                        continue
                    category = Account.objects.filter(pk=cat_id).first()
                    if not category:
                        continue
                    amt = _dec(cat_amounts[idx])
                    if amt == 0:
                        continue
                    is_bill = str(idx) in cat_billable
                    customer = Newcustomer.objects.filter(pk=cat_customer_ids[idx] or None).first()
                    klass    = Pclass.objects.filter(pk=cat_class_ids[idx] or None).first()

                    ExpenseCategoryLine.objects.create(
                        expense=exp, category=category,
                        description=cat_descs[idx],
                        amount=amt, is_billable=is_bill,
                        customer=customer, class_field=klass
                    )
                    total += amt

                # Item lines
                item_product_ids = request.POST.getlist("item_product[]")
                item_descs       = request.POST.getlist("item_desc[]")
                item_qtys        = request.POST.getlist("item_qty[]")
                item_rates       = request.POST.getlist("item_rate[]")
                item_amounts     = request.POST.getlist("item_amount[]")
                item_billable    = set(request.POST.getlist("item_billable[]"))
                item_customer_ids= request.POST.getlist("item_customer[]")
                item_class_ids   = request.POST.getlist("item_class[]")

                for idx, prod_id in enumerate(item_product_ids):
                    if not prod_id:
                        continue
                    product = Product.objects.filter(pk=prod_id).first()
                    if not product:
                        continue
                    qty  = _dec(item_qtys[idx], "0")
                    rate = _dec(item_rates[idx], "0")
                    amt  = _dec(item_amounts[idx]) or (qty * rate)

                    is_bill = str(idx) in item_billable
                    customer = Newcustomer.objects.filter(pk=item_customer_ids[idx] or None).first()
                    klass    = Pclass.objects.filter(pk=item_class_ids[idx] or None).first()

                    ExpenseItemLine.objects.create(
                        expense=exp, product=product,
                        description=item_descs[idx],
                        qty=qty, rate=rate, amount=amt,
                        is_billable=is_bill, customer=customer, class_field=klass
                    )
                    total += amt

                exp.total_amount = total
                exp.save(update_fields=["total_amount"])

                # ---- Rebuild journal (delete old + re-post)
                JournalEntry.objects.filter(expense=exp).delete()
                post_expense_to_gl(exp)
                return redirect("expenses:expense-detail", pk=exp.pk)

        except Exception as e:
            return redirect("expenses:add-expense")

    # GET → prefill context
    context = {
        "expense": exp,
        "accounts": Account.objects.all().order_by("account_name"),
        "expense_accounts": Account.objects.filter(account_type__in=[
            "EXPENSE", "OTHER_EXPENSE", "COST_OF_SALES", "Expense", "Other Expenses", "Cost of Sales"
        ]).order_by("account_name"),
        "products": Product.objects.all().order_by("name"),
        "customers": Newcustomer.objects.all().order_by("customer_name"),
        "suppliers": Newsupplier.objects.all().order_by("company_name"),
        "classes": Pclass.objects.all().order_by("class_name"),
        # existing lines to loop in the form:
        "cat_lines": exp.cat_lines.select_related("category", "customer", "class_field").all(),
        "item_lines": exp.item_lines.select_related("product", "customer", "class_field").all(),
        "payment_methods": Expense.PAYMENT_METHODS, 
    }
    return render(request, "expenses_form.html", context)

# end
# bill views

def _dec(v, default="0.00"):
    try:
        return Decimal(str(v if v not in (None, "") else default))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def generate_unique_bill_no(prefix="BILL"):
    """
    8-digit numeric suffix (like 00001234) with a prefix for readability. Ensures uniqueness.
    """
    base_date = timezone.now().strftime("%y%m")  # e.g., '2510'
    seed = f"{base_date}0001"
    suffix = int(seed)
    while True:
        candidate = f"{prefix}{suffix:08d}"
        if not Bill.objects.filter(bill_no=candidate).exists():
            return candidate
        suffix += 1


def add_bill(request):
    """
    Create & save a Bill with category lines and item lines.
    POST expects list fields with the same naming as Expenses, e.g.:
      Category rows:
        cat_category[], cat_desc[], cat_amount[], cat_billable[], cat_customer[], cat_class[]
      Item rows:
        item_product[], item_desc[], item_qty[], item_rate[], item_amount[], item_billable[], item_customer[], item_class[]
    """
    if request.method == "POST":
        try:
            with transaction.atomic():
                # Header
                supplier_id      = request.POST.get("supplier_id") or ""   # prefer selecting supplier by id
                supplier_name    = request.POST.get("supplier") or ""      # fallback free text (your HTML has name="supplier")
                mailing_address  = request.POST.get("mailing_address") or ""
                terms            = request.POST.get("terms") or ""
                bill_date        = request.POST.get("bill_date") or timezone.localdate()
                due_date         = request.POST.get("due_date") or None
                bill_no          = request.POST.get("bill_no") or ""
                location         = request.POST.get("location") or ""
                memo             = request.POST.get("memo") or ""
                attachment       = request.FILES.get("attachments")

                supplier = Newsupplier.objects.filter(pk=supplier_id).first() if supplier_id else None

                # Ensure a unique bill_no (auto-generate if missing/invalid)
                if not bill_no or Bill.objects.filter(bill_no=bill_no).exists():
                    bill_no = generate_unique_bill_no()

                bill = Bill.objects.create(
                    supplier=supplier,
                    supplier_name=supplier_name if not supplier else None,
                    mailing_address=mailing_address,
                    terms=terms,
                    bill_date=bill_date,
                    due_date=due_date,
                    bill_no=bill_no,
                    location=location,
                    memo=memo,
                    attachments=attachment,
                )

                total = Decimal("0.00")

                # -------- Category lines --------
                cat_category_ids = request.POST.getlist("cat_category[]")
                cat_descs        = request.POST.getlist("cat_desc[]")
                cat_amounts      = request.POST.getlist("cat_amount[]")
                cat_billable     = set(request.POST.getlist("cat_billable[]"))  # contains row indices (as strings)
                cat_customer_ids = request.POST.getlist("cat_customer[]")
                cat_class_ids    = request.POST.getlist("cat_class[]")

                for idx, acc_id in enumerate(cat_category_ids):
                    if not acc_id:
                        continue
                    category = Account.objects.filter(pk=acc_id).first()
                    if not category:
                        continue

                    amt = _dec(cat_amounts[idx])
                    if amt == 0:
                        continue

                    is_bill = str(idx) in cat_billable
                    customer = Newcustomer.objects.filter(pk=cat_customer_ids[idx] or None).first()
                    klass    = Pclass.objects.filter(pk=cat_class_ids[idx] or None).first()

                    BillCategoryLine.objects.create(
                        bill=bill, category=category,
                        description=cat_descs[idx],
                        amount=amt, is_billable=is_bill,
                        customer=customer, class_field=klass
                    )
                    total += amt

                # -------- Item lines --------
                item_product_ids = request.POST.getlist("item_product[]")
                item_descs       = request.POST.getlist("item_desc[]")
                item_qtys        = request.POST.getlist("item_qty[]")
                item_rates       = request.POST.getlist("item_rate[]")
                item_amounts     = request.POST.getlist("item_amount[]")
                item_billable    = set(request.POST.getlist("item_billable[]"))
                item_customer_ids= request.POST.getlist("item_customer[]")
                item_class_ids   = request.POST.getlist("item_class[]")

                for idx, prod_id in enumerate(item_product_ids):
                    if not prod_id:
                        continue
                    product = Product.objects.filter(pk=prod_id).first()
                    if not product:
                        continue

                    qty  = _dec(item_qtys[idx], "0")
                    rate = _dec(item_rates[idx], "0")
                    amt  = _dec(item_amounts[idx]) or (qty * rate)

                    is_bill = str(idx) in item_billable
                    customer = Newcustomer.objects.filter(pk=item_customer_ids[idx] or None).first()
                    klass    = Pclass.objects.filter(pk=item_class_ids[idx] or None).first()

                    BillItemLine.objects.create(
                        bill=bill, product=product,
                        description=item_descs[idx],
                        qty=qty, rate=rate, amount=amt,
                        is_billable=is_bill, customer=customer, class_field=klass
                    )
                    total += amt

                bill.total_amount = total
                bill.save(update_fields=["total_amount"])

                action = request.POST.get("save_action") or "save"
                if action == "save&new":
                    return redirect("expenses:expenses")
                if action == "save&new":
                    return redirect("expenses:add-bill")
                # adjust to your list route
                return redirect("expenses:expenses")

        except Exception as e:
            messages.error(request, f"Could not save bill: {e}")

    # GET
    context = {
        "accounts": Account.objects.all().order_by("account_name"),
        "expense_accounts": Account.objects.filter(
            account_type__in=["EXPENSE", "OTHER_EXPENSE", "COST_OF_SALES", "Expense", "Other Expenses", "Cost of Sales"]
        ).order_by("account_name"),
        "products": Product.objects.all().order_by("name"),
        "customers": Newcustomer.objects.all().order_by("customer_name"),
        "suppliers": Newsupplier.objects.all().order_by("company_name"),
        "classes": Pclass.objects.all().order_by("class_name"),
        "generated_bill_no": generate_unique_bill_no(),  # prefill UI
    }
    return render(request, "bill_form.html", context)

# end




def add_time_activity(request):
   
    return render(request, 'time_activity_form.html', {})

def purchase_order(request):
   
    return render(request, 'purchase_order_form.html', {})
def supplier_credit(request):
   
    return render(request, 'supplier_credit_form.html', {})

def pay_down_credit(request):
   
    return render(request, 'pay_down_credit_form.html', {})
def import_bills(request):
   
    return render(request, 'import_bills_form.html', {})
def credit_card(request):
   
    return render(request, 'credit_card_credit_form.html', {})
def add_cheque(request):
   
    return render(request, 'cheque_form.html', {})


