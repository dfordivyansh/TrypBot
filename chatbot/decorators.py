# =========================================================
# STEP 2b — DECORATORS
# FILE: chatbot/decorators.py
# ACTION: CREATE NEW FILE
# =========================================================

from functools import wraps
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.utils.cache import add_never_cache_headers


def crm_login_required(view_func):
    """
    Redirects unauthenticated users to /crm/login/
    instead of the default Django login URL.

    CRM pages are never cached: phones (and the CRM added to the home screen)
    otherwise show an old copy of the chat list on Back, without the newest chats.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("crm_login")
        response = view_func(request, *args, **kwargs)
        if not response.has_header("Cache-Control"):
            add_never_cache_headers(response)
        return response
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