from django.urls import path
from django.views.generic import RedirectView

urlpatterns = [
    # Redirect old auth URLs to new employee login system
    path(
        "auth/login/",
        RedirectView.as_view(url='/login/', permanent=True),
        name="auth-login-basic",
    ),
    path(
        "auth/register/",
        RedirectView.as_view(url='/employees/create/', permanent=True),
        name="auth-register-basic",
    ),
    path(
        "auth/forgot_password/",
        RedirectView.as_view(url='/admin/', permanent=True),  # Redirect to Django admin for password reset
        name="auth-forgot-password-basic",
    ),
]
