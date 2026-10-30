from django.urls import path

from .views import (
    chat_api,
    chatbot_ui,
    search_hotels_api,
    hotel_rates_api,
    place_photo_api,
    whatsapp_webhook,
    dashboard,
    widget_lead_create,
    widget_lead_update,
    widget_chat,
    widget_files,
    google_ads_lead_webhook,
    meta_leads_webhook,
    website_booking_webhook,
    website_enquiry_webhook,
)

urlpatterns = [

    path(
        "T5Y8U2I9O3P1A6S4/",
        chat_api
    ),

    path(
        "dashboard/",
        dashboard,
        name="dashboard"
    ),

    path(
        "search-hotels/",
        search_hotels_api,
        name="search_hotels_api"
    ),

    path(
        "hotel-rates/",
        hotel_rates_api,
        name="hotel_rates_api"
    ),

    path(
        "",
        chatbot_ui,
        name="chatbot_ui"
    ),
    path(
        "place-photo/",
        place_photo_api,
        name="place_photo_api"
    ),

    path(
        "whatsapp-webhook/",
        whatsapp_webhook,
        name="whatsapp_webhook"
    ),

    # Widget APIs
    path(
        "lead/",
        widget_lead_create,
        name="widget_lead_create"
    ),
    path(
        "lead/<int:lead_id>/",
        widget_lead_update,
        name="widget_lead_update"
    ),

    # Google Ads Lead Form Extension webhook
    path(
        "leads/google-ads/",
        google_ads_lead_webhook,
        name="google_ads_lead_webhook"
    ),

    # Meta (Facebook/Instagram) Lead Ads webhook
    path(
        "leads/meta-ads/",
        meta_leads_webhook,
        name="meta_leads_webhook"
    ),

    # www.trypdeals.com online booking (short tours + cabs), from the website's Firebase functions
    path(
        "leads/website-booking/",
        website_booking_webhook,
        name="website_booking_webhook"
    ),
    # Website enquiries (cab / route / small tour / chat), from the same Firebase functions
    path(
        "leads/website-enquiry/",
        website_enquiry_webhook,
        name="website_enquiry_webhook"
    ),
    path(
        "chat/",
        widget_chat,
        name="widget_chat"
    ),

    # Widget static files
    path(
        "widget/<str:file_name>",
        widget_files,
        name="widget_files"
    ),
]
