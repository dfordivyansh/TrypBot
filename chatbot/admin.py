from django.contrib import admin

from .models import (
    LeadCategoryRule,
    ChatSession,
    ChatMessage,
    Lead,
    Package,
    FAQ,
    Itinerary,
    InternalNote,
    SalesProfile,
    ConversationLabel,
    ConversationStatus,
    Reminder,
    CRMTemplate,
    DestinationAssignment,
    UserEngagement,
    OptInRecord,
    SpamRiskAlert,
    ContactTag,
    Segment,
    Campaign,
    CampaignRecipient,
)


# =========================================================
# 💬 CHAT MESSAGE INLINE
# =========================================================

class ChatMessageInline(admin.TabularInline):

    model = ChatMessage

    extra = 0

    can_delete = False

    ordering = ("created_at",)

    readonly_fields = (
        "sender_type",
        "message",
        "message_status",
        "created_at",
    )

    fields = (
        "sender_type",
        "message",
        "message_status",
        "created_at",
    )


# =========================================================
# 💬 CHAT SESSION ADMIN
# =========================================================

@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):

    list_display = (
        "session_id",
        "user_name",
        "phone_number",
        "current_destination",
        "step",
        "unread_count",
        "is_human_takeover",
        "updated_at",
    )

    search_fields = (
        "session_id",
        "phone_number",
        "user_name",
    )

    list_filter = (
        "step",
        "is_human_takeover",
        "is_active",
        "created_at",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    ordering = (
        "-updated_at",
    )

    inlines = [
        ChatMessageInline
    ]

    actions = [
        "enable_human_takeover",
        "disable_human_takeover",
        "mark_read",
    ]

    def enable_human_takeover(self, request, queryset):

        queryset.update(
            is_human_takeover=True
        )

    enable_human_takeover.short_description = (
        "Enable Human Takeover"
    )

    def disable_human_takeover(self, request, queryset):

        queryset.update(
            is_human_takeover=False
        )

    disable_human_takeover.short_description = (
        "Disable Human Takeover"
    )

    def mark_read(self, request, queryset):

        queryset.update(
            unread_count=0
        )

    mark_read.short_description = (
        "Mark selected chats as read"
    )


# =========================================================
# 💬 CHAT MESSAGE ADMIN
# =========================================================

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):

    list_display = (
        "session",
        "sender_type",
        "short_message",
        "message_status",
        "created_at",
    )

    search_fields = (
        "message",
        "session__phone_number",
        "session__user_name",
    )

    list_filter = (
        "sender_type",
        "message_status",
        "created_at",
    )

    ordering = (
        "-created_at",
    )

    readonly_fields = (
        "created_at",
    )

    def short_message(self, obj):

        return obj.message[:80]

    short_message.short_description = (
        "Message Preview"
    )


# =========================================================
# 📞 LEAD ADMIN
# =========================================================

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):

    list_display = (
        "full_name",
        "phone",
        "destination",
        "priority",
        "status",
        "assigned_to",
        "created_at",
    )

    search_fields = (
        "full_name",
        "phone",
        "destination",
        "email",
    )

    list_filter = (
        "status",
        "priority",
        "destination",
    )

    ordering = (
        "-created_at",
    )

    actions = [
        "mark_followup",
        "mark_new_lead",
        "mark_converted",
    ]

    def mark_followup(self, request, queryset):

        queryset.update(
            priority="high"
        )

    mark_followup.short_description = (
        "Mark selected leads as Follow Up"
    )

    def mark_new_lead(self, request, queryset):

        queryset.update(
            status="new_lead"
        )

    mark_new_lead.short_description = (
        "Mark selected leads as New Lead"
    )

    def mark_converted(self, request, queryset):

        queryset.update(
            status="converted"
        )

    mark_converted.short_description = (
        "Mark selected leads as Converted"
    )


# =========================================================
# 🧾 ITINERARY ADMIN
# =========================================================

@admin.register(Itinerary)
class ItineraryAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "status",
        "total_days",
        "estimated_budget",
        "created_at",
    )

    search_fields = (
        "generated_by_ai",
    )

    list_filter = (
        "status",
        "created_at",
    )

    ordering = (
        "-created_at",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )
    
# =========================================================
# 📦 PACKAGE ADMIN
# =========================================================

@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):

    list_display = (
        "title",
        "destination",
        "days",
        "nights",
        "price",
        "offer_price",
        "hotel_type",
        "flight_included",
        "is_active",
    )

    search_fields = (
        "title",
        "destination",
    )

    list_filter = (
        "destination",
        "hotel_type",
        "flight_included",
        "meals_included",
        "is_active",
    )

    ordering = (
        "price",
    )

    list_editable = (
        "price",
        "offer_price",
        "hotel_type",
        "is_active",
    )


# =========================================================
# 🧠 FAQ ADMIN
# =========================================================

@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):

    list_display = (
        "question",
        "category",
        "priority",
        "is_active",
        "short_answer",
    )

    search_fields = (
        "question",
        "answer",
        "keywords",
    )

    list_filter = (
        "category",
        "is_active",
    )

    ordering = (
        "category",
    )

    list_editable = (
        "priority",
        "is_active",
    )

    def short_answer(self, obj):

        return obj.answer[:60] + "..."

    short_answer.short_description = (
        "Answer Preview"
    )


# =========================================================
# 📝 INTERNAL NOTES ADMIN
# =========================================================

@admin.register(InternalNote)
class InternalNoteAdmin(admin.ModelAdmin):

    list_display = (
        "session",
        "added_by",
        "created_at",
    )

    search_fields = (
        "note",
        "session__phone_number",
    )

    ordering = (
        "-created_at",
    )


# =========================================================
# 👨‍💼 SALES PROFILE ADMIN
# =========================================================

@admin.register(SalesProfile)
class SalesProfileAdmin(admin.ModelAdmin):

    list_display = (
        "user",
        "role",
        "is_team_leader",
        "team_size",
        "is_active_for_assignment",
        "is_active_for_meta",
        "is_active_for_website",
        "assignment_order",
        "total_leads",
        "total_conversions",
    )

    list_editable = (
        "is_active_for_assignment",
        "is_active_for_meta",
        "is_active_for_website",
        "assignment_order",
    )

    # Team leader: tick the box and move the members to the right-hand list.
    filter_horizontal = ("team_members",)
    fieldsets = (
        (None, {"fields": ("user", "role")}),
        ("Team leader", {
            "fields": ("is_team_leader", "team_members"),
            "description": "A team leader sees their own chats and their team members' chats, "
                           "and can assign chats to anyone in the team.",
        }),
        ("Lead assignment", {"fields": (
            "is_active_for_assignment", "is_active_for_meta", "is_active_for_website",
            "assignment_order", "is_online",
        )}),
        ("Stats", {"fields": ("total_leads", "total_conversions")}),
    )

    @admin.display(description="Team members")
    def team_size(self, obj):
        return obj.team_members.count() if obj.is_team_leader else "-"
    

# =========================================================
# 🏷️ CONVERSATION LABEL ADMIN
# =========================================================

@admin.register(ConversationLabel)
class ConversationLabelAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "color",
        "order",
    )

    search_fields = (
        "name",
    )

    ordering = (
        "order",
        "name",
    )

    list_editable = (
        "color",
        "order",
    )

# =========================================================
# 📌 CONVERSATION STATUS ADMIN
# =========================================================

@admin.register(ConversationStatus)
class ConversationStatusAdmin(admin.ModelAdmin):

    list_display = (
        "session",
        "label",
        "assigned_to",
        "closed",
        "updated_at",
    )

    search_fields = (
        "session__phone_number",
        "session__user_name",
    )

    list_filter = (
        "closed",
        "label",
    )

    ordering = (
        "-updated_at",
    )

# =========================================================
# ⏰ REMINDER ADMIN
# =========================================================

@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):

    list_display = (
        "session",
        "reminder_at",
        "done",
        "created_by",
    )

    search_fields = (
        "note",
        "session__phone_number",
    )

    list_filter = (
        "done",
        "reminder_at",
    )

    ordering = (
        "reminder_at",
    )

    list_editable = (
        "done",
    )



@admin.register(CRMTemplate)
class CRMTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "template_name",
        "whatsapp_template_id",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "created_at",
    )

    search_fields = (
        "title",
        "template_name",
        "template_text",
    )

    fieldsets = (
        (None, {
            "fields": ("title", "template_name", "whatsapp_template_id", "template_text")
        }),
    )


# =========================================================
# 🏝️ DESTINATION ASSIGNMENT ADMIN
# =========================================================

@admin.register(DestinationAssignment)
class DestinationAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "sales_person",
        "destination",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
        "destination",
        "created_at",
    )

    search_fields = (
        "sales_person__username",
        "sales_person__first_name",
        "sales_person__last_name",
        "destination",
    )

    list_editable = (
        "is_active",
    )


# =========================================================
# 🎯 USER ENGAGEMENT ADMIN
# =========================================================

@admin.register(UserEngagement)
class UserEngagementAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "quality_score",
        "message_count",
        "user_response_count",
        "bot_message_count",
        "successful_deliveries",
        "failed_deliveries",
        "flagged_as_spam",
        "opt_out_requested",
        "last_engagement",
    )
    
    list_filter = (
        "flagged_as_spam",
        "opt_out_requested",
        "last_engagement",
    )
    
    search_fields = (
        "session__session_id",
        "session__phone_number",
        "session__user_name",
    )
    
    readonly_fields = (
        "session",
        "message_count",
        "user_response_count",
        "bot_message_count",
        "first_response_time_seconds",
        "avg_response_time_seconds",
        "positive_responses",
        "negative_responses",
        "neutral_responses",
        "successful_deliveries",
        "failed_deliveries",
        "spam_flag_count",
        "quality_score",
        "last_engagement",
        "created_at",
    )
    
    fieldsets = (
        ("Session Info", {
            "fields": ("session",)
        }),
        ("Engagement Metrics", {
            "fields": (
                "message_count",
                "user_response_count",
                "bot_message_count",
                "first_response_time_seconds",
                "avg_response_time_seconds",
            )
        }),
        ("Response Quality", {
            "fields": (
                "positive_responses",
                "negative_responses",
                "neutral_responses",
            )
        }),
        ("Delivery Tracking", {
            "fields": (
                "successful_deliveries",
                "failed_deliveries",
            )
        }),
        ("Risk Indicators", {
            "fields": (
                "flagged_as_spam",
                "spam_flag_count",
                "opt_out_requested",
            )
        }),
        ("Quality Score", {
            "fields": ("quality_score",)
        }),
        ("Timestamps", {
            "fields": ("last_engagement", "created_at")
        }),
    )


# =========================================================
# ✅ OPT-IN RECORD ADMIN
# =========================================================

@admin.register(OptInRecord)
class OptInRecordAdmin(admin.ModelAdmin):
    list_display = (
        "phone_number",
        "opt_in_method",
        "double_opt_in_confirmed",
        "is_active",
        "opt_in_timestamp",
        "opt_out_timestamp",
    )
    
    list_filter = (
        "opt_in_method",
        "double_opt_in_confirmed",
        "is_active",
        "opt_in_timestamp",
    )
    
    search_fields = (
        "phone_number",
        "session__session_id",
        "session__user_name",
    )
    
    readonly_fields = (
        "opt_in_timestamp",
        "double_opt_in_timestamp",
        "opt_out_timestamp",
    )
    
    fieldsets = (
        ("Contact Info", {
            "fields": ("phone_number", "session")
        }),
        ("Opt-In Details", {
            "fields": (
                "opt_in_method",
                "opt_in_timestamp",
                "consent_text",
                "double_opt_in_confirmed",
                "double_opt_in_timestamp",
            )
        }),
        ("Status", {
            "fields": (
                "is_active",
                "opt_out_timestamp",
                "opt_out_reason",
            )
        }),
    )


# =========================================================
# 🚨 SPAM RISK ALERT ADMIN
# =========================================================

@admin.register(SpamRiskAlert)
class SpamRiskAlertAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "risk_level",
        "risk_type",
        "action_taken",
        "resolved",
        "created_at",
    )
    
    list_filter = (
        "risk_level",
        "risk_type",
        "action_taken",
        "resolved",
        "created_at",
    )
    
    search_fields = (
        "session__session_id",
        "session__phone_number",
        "session__user_name",
        "description",
    )
    
    readonly_fields = (
        "session",
        "risk_level",
        "risk_type",
        "description",
        "created_at",
    )
    
    list_editable = (
        "action_taken",
        "resolved",
    )
    
    fieldsets = (
        ("Session Info", {
            "fields": ("session",)
        }),
        ("Risk Details", {
            "fields": (
                "risk_level",
                "risk_type",
                "description",
            )
        }),
        ("Action Taken", {
            "fields": ("action_taken",)
        }),
        ("Resolution", {
            "fields": (
                "resolved",
                "resolved_at",
                "resolution_notes",
            )
        }),
        ("Timestamps", {
            "fields": ("created_at",)
        }),
    )

# =========================================================
# 📣 CAMPAIGNS / TAGS / SEGMENTS
# =========================================================

@admin.register(ContactTag)
class ContactTagAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "created_by", "created_at")
    search_fields = ("name",)


@admin.register(Segment)
class SegmentAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "created_by", "created_at")
    search_fields = ("name",)


class CampaignRecipientInline(admin.TabularInline):
    model = CampaignRecipient
    extra = 0
    can_delete = False
    fields = ("phone", "name", "status", "sent_at", "delivered_at", "read_at", "error_message")
    readonly_fields = fields
    show_change_link = False
    max_num = 0


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "template_name", "scheduled_at", "created_by", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "template_name")
    readonly_fields = ("created_at", "updated_at", "started_at", "completed_at")



@admin.register(LeadCategoryRule)
class LeadCategoryRuleAdmin(admin.ModelAdmin):
    """
    Category-wise lead routing: new leads of a category go to its people in
    turn (before the website / Meta round robin). Categories come from the
    website forms and the bot (personal tour, cab, 1 day / 2 day tour, route).
    """
    list_display = ("category", "people", "is_active", "updated_at")
    list_editable = ("is_active",)
    filter_horizontal = ("sales_people",)
    actions = ["assign_unassigned_leads"]

    def people(self, obj):
        return ", ".join(u.get_full_name() or u.username for u in obj.sales_people.all()) or "-"
    people.short_description = "Sales people"

    @admin.action(description="Assign this category's UNASSIGNED open leads to its people now")
    def assign_unassigned_leads(self, request, queryset):
        from .crm_helpers import assign_by_category, lead_category
        categories = set(queryset.filter(is_active=True).values_list("category", flat=True))
        done = 0
        sessions = (ChatSession.objects.filter(assigned_sales_person__isnull=True)
                    .exclude(conv_status__closed=True))
        for session in sessions.iterator():
            if lead_category(session) in categories and assign_by_category(session):
                done += 1
        self.message_user(request, f"Assigned {done} unassigned lead(s).")
