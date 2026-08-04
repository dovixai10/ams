"""
URL configuration for web_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
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
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),

    # Redirect Django's default auth URLs to our employee system
    path("accounts/login/", RedirectView.as_view(url='/login/', permanent=False)),
    path("accounts/profile/", RedirectView.as_view(url='/profile/', permanent=False)),
    path("accounts/logout/", RedirectView.as_view(url='/logout/', permanent=False)),

    # Employee Management System URLs (before other apps to catch login/ first)
    path("", include("employees.urls")),

    # Dashboard urls
    # path("", include("apps.dashboards.urls")),

    # layouts urls
    # path("", include("apps.layouts.urls")),

    # Pages urls
    # path("", include("apps.pages.urls")),

    # Auth urls (redirected to employee system)
    # path("", include("apps.authentication.urls")),

    # Card urls
    # path("", include("apps.cards.urls")),

    # UI urls
    # path("", include("apps.ui.urls")),

    # Extended UI urls
    # path("", include("apps.extended_ui.urls")),

    # Icons urls
    # path("", include("apps.icons.urls")),

    # Forms urls
    # path("", include("apps.forms.urls")),

    # FormLayouts urls
    # path("", include("apps.form_layouts.urls")),

    # Tables urls
    # path("", include("apps.tables.urls")),
]

# Serve static and media files during development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    
    # Favicon redirect
    from django.views.generic import RedirectView
    urlpatterns += [
        path('favicon.ico', RedirectView.as_view(url=settings.STATIC_URL + 'img/favicon/favicon.ico', permanent=False)),
    ]

# handler404 = SystemView.as_view(template_name="pages_misc_error.html", status=404)
# handler400 = SystemView.as_view(template_name="pages_misc_error.html", status=400)
# handler500 = SystemView.as_view(template_name="pages_misc_error.html", status=500)

# Basic error handlers
from django.views.defaults import page_not_found, server_error, bad_request

handler404 = page_not_found
handler500 = server_error
handler400 = bad_request
