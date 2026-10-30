from django.contrib import admin
from django.urls import path, include
from chatbot.views import chatbot_ui

urlpatterns = [
    path('admin/', admin.site.urls),

    # ✅ Chatbot UI
    path('', chatbot_ui, name='chatbot_ui'),

    # ✅ Existing APIs
    path('api/', include('chatbot.urls')),

    path('crm/', include('chatbot.crm_urls')),
]

# Serve uploaded media in local development only; in production nginx serves /media/.
from django.conf import settings
from django.conf.urls.static import static

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
