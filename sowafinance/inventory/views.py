from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
import json

from django.http import HttpResponse
from openpyxl import Workbook
from tempfile import NamedTemporaryFile
from datetime import datetime, timedelta
from django.utils import timezone
from decimal import Decimal
from django.db.models import Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
import openpyxl
import csv
import io
import os
from django.core.files import File
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from . models import Product,BundleItem,Category,Pclass
from sowaf.models import Newsupplier
from accounts.models import Account
from sales.models import InvoiceItem

# Create your views here.
def _dec(v):
    try:
        return Decimal(str(v)) if v not in (None, "",) else Decimal("0.00")
    except Exception:
        return Decimal("0.00")

# working on the product detail
ZERO_DEC = Value(Decimal("0"), output_field=DecimalField(max_digits=18, decimal_places=2))

def product_detail(request, pk: int):
    # Product + common FKs
    product = get_object_or_404(
        Product.objects.select_related("category", "class_field", "supplier", "income_account", "expense_account"),
        pk=pk
    )

    # How many units sold across all invoices
    sold_qty = (
        InvoiceItem.objects.filter(product_id=product.id)
        .aggregate(v=Coalesce(Sum("qty"), ZERO_DEC))
        .get("v") or Decimal("0")
    )

    on_hand = Decimal(product.quantity or 0)
    remaining = on_hand - sold_qty
    if remaining < 0:
        remaining = Decimal("0")

    # Status flags
    out_of_stock = remaining <= 0
    low_stock_threshold = Decimal("5")   # tweak if you want
    is_low_stock = (remaining > 0 and remaining <= low_stock_threshold)

    # Bundle rows (if bundle)
    bundle_rows = []
    if getattr(product, "is_bundle", False):
        bundle_rows = list(
            BundleItem.objects
            .select_related("product")
            .filter(bundle=product)
        )

    context = {
        "product": product,
        "sold_qty": sold_qty,
        "on_hand": on_hand,
        "remaining": remaining,
        "out_of_stock": out_of_stock,
        "is_low_stock": is_low_stock,
        "bundle_rows": bundle_rows,
    }
    return render(request, "product_detail.html", context)

# adding a product
def add_products(request):
    if request.method == "POST":
        type = request.POST.get("type")
        name = request.POST.get("name")
        sku = request.POST.get("sku")
        category_id = request.POST.get("category")
        category=None
        if category_id:
            try:
                category = Category.objects.get(pk=category_id)
            except Category.DoesNotExist:
                category=None

        class_field_id = request.POST.get("class_field")
        class_field=None
        if class_field_id:
            try:
                class_field = Pclass.objects.get(pk=class_field_id)
            except Pclass.DoesNotExist:
                class_field=None

        sales_description = request.POST.get("sales_description")
        purchase_description = request.POST.get("purchase_description")
        purchase_date = request.POST.get("purchase_date")
        sell_checkbox = request.POST.get("sell_checkbox") == 'on'
        sales_price = request.POST.get("sales_price")
        quantity=request.POST.get("quantity")
        purchase_price = request.POST.get("purchase_price")
        income_account_id = request.POST.get("income_account")
        income_account = Account.objects.filter(id=income_account_id).first() if income_account_id else None

        expense_account_id = request.POST.get("expense_account")
        expense_account=Account.objects.filter(id=expense_account_id).first() if expense_account_id else None

        supplier_id = request.POST.get('supplier')
        supplier=None
        if supplier_id:
            try:
                supplier = Newsupplier.objects.get(pk=supplier_id)
            except Newsupplier.DoesNotExist:
                supplier=None

        purchase_checkbox = request.POST.get("purchpurchase_checkbox") == 'on'
        display_bundle_contents = request.POST.get("display_bundle_contents") == 'on'
        taxable = request.POST.get("taxable") == "on"
        products = Product.objects.create(
            type=type,
            name=name,
            sku=sku,
            quantity=quantity,
            category=category,
            class_field=class_field,
            sales_description=sales_description,
            purchase_description=purchase_description,
            purchase_date=purchase_date,
            sell_checkbox=sell_checkbox,
            supplier=supplier,
            sales_price=sales_price or None,
            purchase_price=purchase_price or None,
            taxable=taxable,
            income_account=income_account,
            expense_account=expense_account,
            purchase_checkbox=purchase_checkbox,
            is_bundle=(type == "Bundle"),
            display_bundle_contents=display_bundle_contents,
        )

        if type == "Bundle":
            product_ids = request.POST.getlist("bundle_product_id[]")
            quantities = request.POST.getlist("bundle_product_qty[]")
            for prod_id, qty in zip(product_ids, quantities):
                if prod_id:
                    try:
                        child_product = Product.objects.get(pk=int(prod_id))
                        BundleItem.objects.create(
                        bundle=products,      # parent bundle
                        product=child_product,  # product inside bundle
                        quantity=int(qty) if qty else 1
                )
                    except Product.DoesNotExist:
                        pass
        # Handle Save action
        action = request.POST.get("save_action")
        if action == "save&new":
            return redirect('inventory:add-products')
        elif action == "save&close":
            return redirect('sales:sales')  # You should have this view
        return redirect('sales:sales')
    products = Product.objects.all()
    suppliers = Newsupplier.objects.all()
    categories = Category.objects.all()
    classes = Pclass.objects.all()
    income_accounts = Account.objects.filter(account_type="Income")
    expense_accounts = Account.objects.filter(account_type="Cost of Sales")
    return render(request, 'Products_and_services_form.html', {
        'products':products,
        'suppliers':suppliers,
        'categories':categories,
        'classes':classes,
        'income_accounts':income_accounts,
        'expense_accounts':expense_accounts,
    })

#  the edit view 


def product_edit(request, pk: int):
    """
    Reuse your existing create form template for edit.
    We pass edit_mode=True and the product, and switch the form's action to this view.
    On POST we update the record and replace bundle lines.
    """
    product = get_object_or_404(Product, pk=pk)

    if request.method == "POST":
        ptype = request.POST.get("type") or product.type
        product.type = ptype
        product.name = request.POST.get("name") or ""
        product.sku  = request.POST.get("sku") or ""

        # FKs
        category_id   = request.POST.get("category")
        class_field_id= request.POST.get("class_field")
        supplier_id   = request.POST.get("supplier")
        income_acc_id = request.POST.get("income_account")
        expense_acc_id= request.POST.get("expense_account")

        product.category    = Category.objects.filter(pk=category_id).first() if category_id else None
        product.class_field = Pclass.objects.filter(pk=class_field_id).first() if class_field_id else None
        product.supplier    = Newsupplier.objects.filter(pk=supplier_id).first() if supplier_id else None
        product.income_account  = Account.objects.filter(pk=income_acc_id).first() if income_acc_id else None
        product.expense_account = Account.objects.filter(pk=expense_acc_id).first() if expense_acc_id else None

        # Booleans / fields
        product.sell_checkbox      = (request.POST.get("sell_checkbox") == "on")
        product.purchase_checkbox  = (request.POST.get("purchase_checkbox") == "on")
        product.taxable            = (request.POST.get("taxable") == "on")
        product.display_bundle_contents = (request.POST.get("display_bundle_contents") == "on")

        product.sales_description     = request.POST.get("sales_description") or ""
        product.purchase_description  = request.POST.get("purchase_description") or ""

        # Dates & numerics
        product.purchase_date = request.POST.get("purchase_date") or None
        product.sales_price   = _dec(request.POST.get("sales_price"))
        product.purchase_price= _dec(request.POST.get("purchase"))
        product.quantity      = request.POST.get("quantity") or 0  # if IntegerField
        # If DecimalField for quantity, do: product.quantity = _dec(request.POST.get("quantity"))

        # Bundle flag by type
        product.is_bundle = (ptype == "Bundle")

        product.save()

        # Replace bundle items when in bundle mode
        if product.is_bundle:
            product.bundleitem_set.all().delete()
            product_ids = request.POST.getlist("bundle_product_id[]")
            quantities  = request.POST.getlist("bundle_product_qty[]")
            for prod_id, qty in zip(product_ids, quantities):
                if prod_id:
                    child = Product.objects.filter(pk=int(prod_id)).first()
                    if child:
                        BundleItem.objects.create(
                            bundle=product,
                            product=child,
                            quantity=int(qty) if qty else 1
                        )
        else:
            # If switching away from Bundle, ensure old bundle lines are removed
            product.bundleitem_set.all().delete()

        # Save actions (optional)
        action = request.POST.get("save_action")
        if action == "save&new":
            return redirect("inventory:add-products")
        if action == "save&close":
            return redirect("sales:sales")
        # default: stay on detail
        return redirect("inventory:product-detail", pk=product.pk)

    # GET: render the same form template, prefilled
    context = {
        "edit_mode": True,
        "product": product,
        "products": Product.objects.all(),           # for bundle dropdown
        "suppliers": Newsupplier.objects.all(),
        "categories": Category.objects.all(),
        "classes": Pclass.objects.all(),
        "income_accounts": Account.objects.filter(account_type="Income"),
        "expense_accounts": Account.objects.filter(account_type="Cost of Sales"),
    }
    return render(request, "Products_and_services_form.html", context)

# end
def add_category_ajax(request):
    if request.method == "POST":
        name = request.POST.get("name")
        if not name:
            return JsonResponse({"success": False, "error": "Category name required"})
        
        cat, created = Category.objects.get_or_create(category_type=name)
        return JsonResponse({
            "success": True,
            "id": cat.id,
            "name": cat.category_type,
        })

def add_class_ajax(request):
    if request.method == "POST":
        name = request.POST.get("name")
        if not name:
            return JsonResponse({"success": False, "error": "Class name required"})
        
        cls, created = Pclass.objects.get_or_create(class_name=name)
        return JsonResponse({
            "success": True,
            "id": cls.id,
            "name": cls.class_name,
        })