"""
URL configuration for sowafinance project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
urlpatterns = [
    path('', include('sowafinance.sowaAuth.urls')),  # login, register, otp, etc.
    path('sowaAuth/', include('django.contrib.auth.urls')),
    # Nest all app URLs under 'sowaf/'
    path('sowaf/', include([
        path('', include('sowafinance.sowaf.urls')),         # dashboard and home
        path('sales/', include('sowafinance.sales.urls')),   # sales module
        path('expenses/', include('sowafinance.expenses.urls')),  # expenses
        path('accounts/', include('sowafinance.accounts.urls')),
        path('inventory/', include('sowafinance.inventory.urls')),
    ])),
    path('admin/', admin.site.urls),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

