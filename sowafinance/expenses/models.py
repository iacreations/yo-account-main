from django.db import models
from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.conf import settings
from sowaf.models import Newcustomer, Newsupplier      # adjust if paths differ
from accounts.models import Account                             # your COA model
from inventory.models import Product                            # your Product model
from inventory.models import Pclass
# Create your models here.
DEC = dict(max_digits=12, decimal_places=2)

class Expense(models.Model):
    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("bank_transfer", "Bank Transfer"),
        ("mobile_money", "Mobile Money"),
        ("cheque", "Cheque"),
        ("card", "Card"),
    ]

    payee_name      = models.CharField(max_length=255, blank=True)          # free text
    payee_supplier  = models.ForeignKey(Newsupplier, null=True, blank=True,
                                        on_delete=models.CASCADE)
    payment_account = models.ForeignKey(Account, on_delete=models.CASCADE)
    payment_date    = models.DateField(default=timezone.localdate)
    payment_method  = models.CharField(max_length=40, choices=PAYMENT_METHODS, default="cash")
    ref_no          = models.CharField(max_length=50, blank=True)
    location        = models.CharField(max_length=120, blank=True)
    memo            = models.TextField(blank=True)
    attachments     = models.FileField(upload_to="expense_attachments/", blank=True, null=True)

    total_amount    = models.DecimalField(**DEC, default=Decimal("0.00"))
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-payment_date", "-id"]

    def __str__(self):
        who = self.payee_supplier.company_name if self.payee_supplier else self.payee_name or "Payee"
        return f"Expense {self.id} - {who} ({self.payment_date})"
    @property
    def payee_display(self):
        return (self.payee_supplier.company_name
            if self.payee_supplier else (self.payee_name or "—"))

    @property
    def type_display(self):
        return "Expense"

    @property
    def number_display(self):
    # fallback to pk if ref is empty
        return self.ref_no or f"{self.pk:06d}"

    @property
    def category_display(self):
    # If there are multiple lines (cat or item), show "--Split--" like QBO
        total_lines = getattr(self, "_total_lines", None)
        if total_lines is None:
            total_lines = self.cat_lines.count() + self.item_lines.count()
        if total_lines > 1:
            return "--Split--"

    # exactly one line → show its name
        cat = next(iter(self.cat_lines.all()), None)
        if cat:
            return getattr(cat.category, "account_name", "—")
        item = next(iter(self.item_lines.all()), None)
        if item:
            return getattr(item.product, "name", "—")
        return "—"

    @property
    def total_before_tax(self):
    # Until tax is tracked, treat total_amount as pre-tax
        return self.total_amount

    @property
    def sales_tax_amount(self):
    # Wire later; 0 for now

        return Decimal("0.00")

    @property
    def total_display(self):
    # If you later add taxes, return pre-tax + tax
        return self.total_amount

    @property
    def approval_status(self):
    # Placeholder; can be wired to a real approval workflow
        return "—"


class ExpenseCategoryLine(models.Model):
    """Category details rows (GL expense accounts)."""
    BILL_STATUS = [("unbilled", "Unbilled"), ("billed", "Billed")]

    expense     = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name="cat_lines")
    category    = models.ForeignKey(Account, on_delete=models.CASCADE)  # limit to expense types in form
    description = models.CharField(max_length=255, blank=True)
    amount      = models.DecimalField(**DEC, default=Decimal("0.00"))

    is_billable = models.BooleanField(default=False)
    customer    = models.ForeignKey(Newcustomer, null=True, blank=True, on_delete=models.CASCADE)
    class_field = models.ForeignKey(Pclass, null=True, blank=True, on_delete=models.CASCADE)
    bill_status = models.CharField(max_length=10, choices=BILL_STATUS, default="unbilled")

    def __str__(self):
        return f"Category line {self.category} {self.amount}"


class ExpenseItemLine(models.Model):
    """Item details rows (products/services)."""
    BILL_STATUS = [("unbilled", "Unbilled"), ("billed", "Billed")]

    expense     = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name="item_lines")
    product     = models.ForeignKey(Product, on_delete=models.CASCADE)
    description = models.CharField(max_length=255, blank=True)

    qty   = models.DecimalField(**DEC, default=Decimal("0.00"))
    rate  = models.DecimalField(**DEC, default=Decimal("0.00"))
    amount= models.DecimalField(**DEC, default=Decimal("0.00"))

    is_billable = models.BooleanField(default=False)
    customer    = models.ForeignKey(Newcustomer, null=True, blank=True, on_delete=models.CASCADE)
    class_field = models.ForeignKey(Pclass, null=True, blank=True, on_delete=models.CASCADE)
    bill_status = models.CharField(max_length=10, choices=BILL_STATUS, default="unbilled")

    def __str__(self):
        return f"Item line {self.product} x {self.qty} @ {self.rate}"

class ColumnPreference(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,related_name='expense_column_preferences')
    table_name = models.CharField(max_length=100)  # e.g. "accounts"
    preferences = models.JSONField(default=dict)   # store {col_name: true/false}

    class Meta:
        unique_together = ('user', 'table_name')

    def __str__(self):
        return f"{self.user} - {self.table_name}"
    

# bills model
class Bill(models.Model):
    supplier = models.ForeignKey(Newsupplier, on_delete=models.CASCADE, related_name='bills')
    mailing_address = models.CharField(max_length=255, blank=True)
    terms = models.CharField(max_length=50, blank=True)
    bill_date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)
    bill_no = models.CharField(max_length=50, unique=True)
    location = models.CharField(max_length=100, blank=True)
    memo = models.TextField(blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    attachment = models.FileField(upload_to='uploads/bills/', null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-bill_date', '-created_at']

    def __str__(self):
        return f'Bill {self.bill_no} - {self.supplier}'


class BillCategoryLine(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name='category_lines')
    # account is optional right now since the form uses a text box; we’ll accept blank and improve later
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True, related_name='bill_category_lines')
    account_text = models.CharField(max_length=120, blank=True)  # capture what the user typed
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    billable = models.BooleanField(default=False)
    customer = models.ForeignKey(Newcustomer, null=True, blank=True, on_delete=models.CASCADE)
    class_field = models.ForeignKey(Pclass, null=True, blank=True, on_delete=models.CASCADE)
    order_index = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f'CategoryLine {self.bill.bill_no} #{self.order_index}'


class BillItemLine(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name='item_lines')
    product = models.ForeignKey(Product, on_delete=models.CASCADE,default="1")
    description = models.CharField(max_length=255, blank=True)
    qty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    billable = models.BooleanField(default=False)
    customer = models.ForeignKey(Newcustomer, null=True, blank=True, on_delete=models.CASCADE)
    class_field = models.ForeignKey(Pclass, null=True, blank=True, on_delete=models.CASCADE)
    order_index = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f'ItemLine {self.bill.bill_no} #{self.order_index}'
