from django.apps import AppConfig


# Outgoing HTTP calls (WhatsApp Graph API, website lookups, media downloads)
# without their own timeout could hang a request thread forever when the
# other side is slow; give them one.
DEFAULT_HTTP_TIMEOUT = 30


def _default_timeout():
    import requests

    original = requests.Session.request
    if getattr(original, "_has_default_timeout", False):
        return

    def request(self, method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = DEFAULT_HTTP_TIMEOUT
        return original(self, method, url, **kwargs)

    request._has_default_timeout = True
    requests.Session.request = request


class ChatbotConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'chatbot'

    def ready(self):
        _default_timeout()
