from django.contrib import admin
from .models import Product,Pclass,Category
# Register your models here.

admin.site.register(Pclass)
admin.site.register(Category)