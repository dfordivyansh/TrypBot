# =========================================================
# STEP 2b — DECORATORS
# FILE: chatbot/decorators.py
# ACTION: CREATE NEW FILE
# =========================================================

from functools import wraps
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required


def crm_login_required(view_func):
    """
    Redirects unauthenticated users to /crm/login/
    instead of the default Django login URL.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("crm_login")
        return view_func(request, *args, **kwargs)
    return wrapper


def manager_required(view_func):
    """
    Allows only users with SalesProfile role=manager or admin,
    or Django superusers.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("crm_login")

        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)

        try:
            profile = request.user.salesprofile
            if profile.role in ("manager", "admin"):
                return view_func(request, *args, **kwargs)
        except Exception:
            pass

        return redirect("crm_chat_home")

    return wrapper