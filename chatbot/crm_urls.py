# =========================================================
# FILE: chatbot/crm_urls.py
# =========================================================

from django.urls import path
from . import crm_views
from . import campaign_views

urlpatterns = [

    # --------------------------------------------------
    # AUTH
    # --------------------------------------------------
    path(
        "login/",
        crm_views.crm_login,
        name="crm_login"
    ),

    path(
        "logout/",
        crm_views.crm_logout,
        name="crm_logout"
    ),

    # --------------------------------------------------
    # DASHBOARD (root of /crm/)
    # --------------------------------------------------
    path(
        "chat-home/",
        crm_views.crm_dashboard,
        name="crm_dashboard"
    ),

    # --------------------------------------------------
    # CHAT HOME
    # --------------------------------------------------
    path(
        "",
        crm_views.crm_chat_home,
        name="crm_chat_home"
    ),

    # --------------------------------------------------
    # CHAT DETAIL
    # --------------------------------------------------
    path(
        "chat/<int:session_id>/",
        crm_views.crm_chat_detail,
        name="crm_chat_detail"
    ),

    # --------------------------------------------------
    # LABEL
    # --------------------------------------------------
    path(
        "update-label/",
        crm_views.crm_update_label,
        name="crm_update_label"
    ),

    # --------------------------------------------------
    # ASSIGN CHAT
    # --------------------------------------------------
    path(
        "assign-chat/",
        crm_views.crm_assign_chat,
        name="crm_assign_chat"
    ),

    path(
        "check-assignments/",
        crm_views.crm_check_assignments,
        name="crm_check_assignments"
    ),

    path(
        "notifications/",
        crm_views.crm_check_assignments,
        name="crm_notifications"
    ),

    # --------------------------------------------------
    # NOTES
    # --------------------------------------------------
    path(
        "add-note/",
        crm_views.crm_add_note,
        name="crm_add_note"
    ),

    path(
        "delete-note/<int:note_id>/",
        crm_views.crm_delete_note,
        name="crm_delete_note"
    ),

    # --------------------------------------------------
    # REMINDER
    # --------------------------------------------------
    # NOTE: "reminder/" (no extra segments) must come AFTER the more
    # specific "reminder/done/<id>/" and "reminder/delete/<id>/" routes
    # would only matter if it had a trailing wildcard — it doesn't, so
    # order among these three is safe either way. Kept as-is.
    path(
        "reminder/",
        crm_views.crm_add_reminder,
        name="crm_add_reminder"
    ),

    path(
        "reminder/done/<int:reminder_id>/",
        crm_views.crm_reminder_done,
        name="crm_reminder_done"
    ),

    path(
        "reminder/delete/<int:reminder_id>/",
        crm_views.crm_reminder_delete,
        name="crm_reminder_delete"
    ),

    # --------------------------------------------------
    # HUMAN TAKEOVER
    # --------------------------------------------------
    path(
        "human-takeover/<int:session_id>/",
        crm_views.crm_human_takeover,
        name="crm_human_takeover"
    ),

    # --------------------------------------------------
    # CLOSE TICKET
    # --------------------------------------------------
    path(
        "close-ticket/<int:session_id>/",
        crm_views.crm_close_ticket,
        name="crm_close_ticket"
    ),

    # --------------------------------------------------
    # SEND MESSAGE (text) — AJAX
    # --------------------------------------------------
    path(
        "send-message/<int:session_id>/",
        crm_views.crm_send_message,
        name="crm_send_message"
    ),

    # --------------------------------------------------
    # SEND FILE / IMAGE / PDF (media) — AJAX multipart
    # --------------------------------------------------
    path(
        "chat/<int:session_id>/send-file/",
        crm_views.crm_send_file,
        name="crm_send_file"
    ),

    # --------------------------------------------------
    # SEND TO NEW NUMBER
    # --------------------------------------------------
    path(
        "send-to-number/",
        crm_views.crm_send_to_number,
        name="crm_send_to_number"
    ),
    path(
        "bulk-add-chats/",
        crm_views.crm_bulk_add_chats,
        name="crm_bulk_add_chats"
    ),
    path(
        "bulk-add-chats/sample/",
        crm_views.crm_bulk_add_sample,
        name="crm_bulk_add_sample"
    ),

    # Chat page: rename (pencil) and block / unblock (3-dot menu)
    path(
        "chat/<int:session_id>/rename/",
        crm_views.crm_rename_chat,
        name="crm_rename_chat"
    ),
    path(
        "chat/<int:session_id>/block/",
        crm_views.crm_block_chat,
        name="crm_block_chat"
    ),

    # Next page of the conversation list (infinite scroll)
    path(
        "conversations/",
        crm_views.crm_conversations_page,
        name="crm_conversations_page"
    ),

    # --------------------------------------------------
    # LIVE POLLING (AJAX)
    # --------------------------------------------------
    path(
        "live/",
        crm_views.crm_live,
        name="crm_live"
    ),

    path(
        "live/messages/<int:session_id>/",
        crm_views.crm_live_messages,
        name="crm_live_messages"
    ),

    # --------------------------------------------------
    # MEDIA PROXY
    # --------------------------------------------------
    path(
        "media/<int:message_id>/",
        crm_views.crm_media_proxy,
        name="crm_media_proxy"
    ),

    # --------------------------------------------------
    # CONTACTS
    # --------------------------------------------------
    path(
        "contacts/",
        crm_views.crm_contacts,
        name="crm_contacts"
    ),

    path(
        "contacts/export/",
        crm_views.crm_export_contacts,
        name="crm_export_contacts"
    ),

    # --------------------------------------------------
    # CREATE ITINERARY
    # --------------------------------------------------
    path(
        "itinerary/",
        crm_views.crm_create_itinerary,
        name="crm_create_itinerary"
    ),

    # --------------------------------------------------
    # BULK LEADS
    # --------------------------------------------------
    path(
        "bulk-leads/",
        crm_views.crm_bulk_leads,
        name="crm_bulk_leads"
    ),

    path(
        "templates/",
        crm_views.crm_templates,
        name="crm_templates"
    ),

    path(
        "api/templates/",
        crm_views.crm_api_templates,
        name="crm_api_templates"
    ),

    path(
        "chat/<int:session_id>/send-template/",
        crm_views.crm_send_template,
        name="crm_send_template"
    ),

    # --------------------------------------------------
    # LEAD ANALYSIS
    # --------------------------------------------------
    path(
        "lead-analysis/",
        crm_views.crm_lead_analysis,
        name="crm_lead_analysis"
    ),

    path(
        "lead-analysis/export/",
        crm_views.crm_export_leads_analysis,
        name="crm_export_leads_analysis"
    ),

    # --------------------------------------------------
    # ALL REMINDERS
    # --------------------------------------------------
    path(
        "all-reminders/",
        crm_views.crm_all_reminders,
        name="crm_all_reminders"
    ),

    # --------------------------------------------------
    # NOTE: this file is already included under the "crm/" prefix in the
    # project's main urls.py (e.g. path("crm/", include("chatbot.crm_urls"))).
    # The original entry here was "crm/api/daywise-stats/", which would have
    # resolved to /crm/crm/api/daywise-stats/ — almost certainly not what was
    # intended. Fixed to "api/daywise-stats/" so it resolves to
    # /crm/api/daywise-stats/. If you actually want the doubled "crm/" in the
    # URL, change this back.
    # --------------------------------------------------
    path(
        "api/daywise-stats/",
        crm_views.crm_daywise_stats,
        name="crm_daywise_stats"
    ),

    # --------------------------------------------------
    # CAMPAIGNS (WhatsApp broadcasts)
    # --------------------------------------------------
    path("campaigns/", campaign_views.campaign_list, name="crm_campaign_list"),
    path("campaigns/new/", campaign_views.campaign_create, name="crm_campaign_create"),
    path("campaigns/api/list-stats/", campaign_views.campaign_list_stats, name="crm_campaign_list_stats"),
    path("campaigns/api/create/", campaign_views.campaign_create_api, name="crm_campaign_create_api"),
    path("campaigns/api/audience/preview/", campaign_views.campaign_audience_preview, name="crm_campaign_audience_preview"),
    path("campaigns/api/audience/contacts/", campaign_views.campaign_audience_contacts, name="crm_campaign_audience_contacts"),
    path("campaigns/api/audience/csv/", campaign_views.campaign_audience_csv, name="crm_campaign_audience_csv"),
    path("campaigns/api/media/", campaign_views.campaign_media_upload, name="crm_campaign_media"),
    path("campaigns/<int:campaign_id>/", campaign_views.campaign_detail, name="crm_campaign_detail"),
    path("campaigns/<int:campaign_id>/stats/", campaign_views.campaign_stats_api, name="crm_campaign_stats"),
    path("campaigns/<int:campaign_id>/recipients/", campaign_views.campaign_recipients_api, name="crm_campaign_recipients"),
    path("campaigns/<int:campaign_id>/export/", campaign_views.campaign_export, name="crm_campaign_export"),
    path("campaigns/<int:campaign_id>/action/<str:action>/", campaign_views.campaign_action, name="crm_campaign_action"),

    # --------------------------------------------------
    # TAGS, SEGMENTS, CONTACT ACTIONS
    # --------------------------------------------------
    path("audience/", campaign_views.audience_page, name="crm_audience"),
    path("audience/tags/save/", campaign_views.tag_save, name="crm_tag_save"),
    path("audience/tags/<int:tag_id>/delete/", campaign_views.tag_delete, name="crm_tag_delete"),
    path("audience/segments/save/", campaign_views.segment_save, name="crm_segment_save"),
    path("audience/segments/<int:segment_id>/delete/", campaign_views.segment_delete, name="crm_segment_delete"),
    path("contacts/tags/apply/", campaign_views.contacts_tag_apply, name="crm_contacts_tag_apply"),
    path("contacts/opt-out/", campaign_views.contacts_opt_out, name="crm_contacts_opt_out"),
    path("contacts/import/", campaign_views.contacts_import, name="crm_contacts_import"),
]
