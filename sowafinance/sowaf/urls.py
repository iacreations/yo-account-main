from django.urls import path
from . import views


app_name='sowaf'
# my urls
urlpatterns = [
    path('home/', views.home, name='home'),
    
    # asset urls
    path('assets/', views.assets, name='assets'),
    path('assets/add/asset', views.add_assests, name='add-asset'),
    path('assets/edit/<str:pk>/', views.edit_asset, name='edit-asset'),
    path('assets/delete/<str:pk>/', views.delete_asset, name='delete-asset'),
    path('assets/import/import-assets', views.import_assets, name='import-assets'),
    path('templates/assets/', views.download_assets_template, name='import_assets_template'),
    
    # customer urls
    path('customers/', views.customers, name='customers'),
    path('customers/add/', views.add_customer, name='add-customer'),
    path('customers/edit/<str:pk>/', views.edit_customer, name='edit-customer'),
    path('customers/delete/<str:pk>/', views.delete_customer, name='delete-customer'),
    path('customers/import/import-customers', views.import_customers, name='import-customers'),
    path('templates/customers/', views.download_customers_template, name='import_customers_template'),
    
    # clents urls
    path('clients/', views.clients, name='clients'),
    path('clients/add/', views.add_client, name='add-client'),
    path('clients/edit/<str:pk>/', views.edit_client, name='edit-client'),
    path('clients/delete/<str:pk>/', views.delete_client, name='delete-client'),
    path('clients/import/import-clients', views.import_clients, name='import-clients'), 
    path('templates/clients/', views.download_clients_template, name='import_clients_template'),
    
    # employee urls
    path('employees/', views.employee, name='employees'),
    path('employees/add/employee', views.add_employees, name='add-employee'),
    path('employees/edit/<str:pk>/', views.edit_employee, name='edit-employee'),
    path('employees/delete/<str:pk>/', views.delete_employee, name='delete-employee'),
    path('employees/import/import-employees', views.import_employees, name='import-employees'),
    path('templates/employees/', views.download_employees_template, name='import_employees_template'),
  
    # supplier urls
    path('suppliers/', views.supplier, name='suppliers'),
    path('suppliers/add/supplier', views.add_supplier, name='add-supplier'),
    path('suppliers/edit/<str:pk>', views.edit_supplier, name='edit-supplier'),
    path('suppliers/delete/<str:pk>', views.delete_supplier, name='delete-supplier'),
    path('suppliers/import/import-suppliers', views.import_suppliers, name='import-suppliers'),
    path('templates/suppliers/', views.download_suppliers_template, name='import_suppliers_template'),
    
 
        # expenses url
    path('expenses/', views.expenses, name='expenses'),
    # tasks url
    path('tasks/', views.tasks, name='tasks'),
    # taxes url
    path('taxes/', views.taxes, name='taxes'),

    # -------------------
    path('miscellaneous/', views.miscellaneous, name='miscellaneous'),
    # -------------
    path('reports/', views.reports, name='reports'),
    # -----------------
    
]
