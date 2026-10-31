"""
TrypDeals — models.py  v16.0
=============================

Company: TrypDeals Tech Labs Pvt. Ltd.
Address: FF 16, One Mart Mall, Sector 6, Vasundhara, Ghaziabad - 201012

Changes from v15.0
──────────────────
• Added TravelRequest  — stores raw FLOW_BASIC_TRAVEL submission payload.
• Added PackageSelection — records which rule-based package a user chose.
• Added CustomItinerary  — stores day-wise flow submission + generated itinerary.
• Added GroupTourLead    — records group-tour date selections.
• All new models link back to ChatSession for full conversation traceability.
• Existing models preserved unchanged (ChatSession, ChatMessage, Hotel,
  HotelRate, Itinerary, Lead, Package, FAQ, InternalNote, SalesProfile,
  ConversationLabel, ConversationStatus, Reminder, RoundRobinTracker,
  CRMTemplate).
"""

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import uuid


# =========================================================
# 💬 CHAT SESSION
# =========================================================

class ChatSession(models.Model):

    session_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        blank=True,
    )

    user_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    phone_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        db_index=True,
    )

    current_destination = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    current_package = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    step = models.IntegerField(default=1)

    is_human_takeover = models.BooleanField(default=False)

    assigned_sales_person = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="assigned_chats",
    )

    data = models.JSONField(default=dict, blank=True)

    last_message = models.TextField(blank=True, null=True)

    unread_count = models.IntegerField(default=0)

    is_active = models.BooleanField(default=True)

    last_customer_message_time = models.DateTimeField(blank=True, null=True)

    # Contact segmentation / marketing consent (used by campaigns)
    tags = models.ManyToManyField(
        "ContactTag",
        blank=True,
        related_name="sessions",
    )
    marketing_opt_out = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Contact asked not to receive broadcast/marketing messages",
    )
    marketing_opt_out_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.session_id:
            base = self.phone_number or "crm"
            self.session_id = f"{base}_{uuid.uuid4().hex}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.phone_number or self.session_id}"


# =========================================================
# 💬 CHAT MESSAGE HISTORY
# =========================================================

class ChatMessage(models.Model):

    MESSAGE_TYPES = [
        ("user",   "User"),
        ("bot",    "Bot"),
        ("sales",  "Sales"),
        ("agent",  "Agent"),
        ("system", "System"),
    ]

    MESSAGE_STATUS = [
        ("sent",      "Sent"),
        ("delivered", "Delivered"),
        ("read",      "Read"),
        ("failed",    "Failed"),
    ]

    MEDIA_TYPES = [
        ("",         "None"),
        ("image",    "Image"),
        ("video",    "Video"),
        ("audio",    "Audio"),
        ("document", "Document"),
    ]

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )

    sender_type = models.CharField(max_length=20, choices=MESSAGE_TYPES)
    message = models.TextField(blank=True, default="")

    media_url = models.URLField(blank=True, default="", max_length=1000)
    media_type = models.CharField(max_length=20, choices=MEDIA_TYPES, blank=True, default="")
    media_mime_type = models.CharField(max_length=100, blank=True, default="")
    media_filename = models.CharField(max_length=255, blank=True, default="")

    whatsapp_media_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    whatsapp_message_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)

    message_status = models.CharField(max_length=20, choices=MESSAGE_STATUS, default="sent")
    is_interactive = models.BooleanField(default=False)
    interactive_type = models.CharField(max_length=50, blank=True, null=True)

    raw_payload = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sender_type} - {self.session.session_id}"


# =========================================================
# ✈️  TRAVEL REQUEST  (FLOW_BASIC_TRAVEL submission)
# =========================================================

class TravelRequest(models.Model):
    """
    Created when a user submits the FLOW_BASIC_TRAVEL WhatsApp Flow.
    One session can have many requests (user may restart and resubmit).
    The most recent active=True record is the current request.
    """

    STATUS_CHOICES = [
        ("pending",   "Pending"),
        ("packaged",  "Packaged"),       # packages generated and shown
        ("custom",    "Custom Flow"),    # day-wise flow sent
        ("group",     "Group Tour"),     # group tour path
        ("handoff",   "Sales Handoff"),  # transferred to sales agent
        ("completed", "Completed"),
    ]

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="travel_requests",
    )

    # ── Core travel details (parsed from flow) ────────
    destination = models.CharField(max_length=255, db_index=True)
    days = models.IntegerField(
        null=True,
        blank=True,
        help_text="Null means user selected 'Other' (> 6 days)"
    )
    days_raw = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Raw string from flow (e.g. '3', '4', 'Other')"
    )
    adults = models.IntegerField(default=2)
    children_count = models.IntegerField(default=0)
    children_ages = models.JSONField(default=list, blank=True)
    special_notes = models.TextField(blank=True, default="")

    # ── Routing outcome ───────────────────────────────
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    routed_to = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Stage/handler the request was routed to after submission",
    )

    # ── Audit ─────────────────────────────────────────
    raw_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Raw WhatsApp Flow nfm_reply payload for auditing",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Latest active request for this session",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["session", "is_active"]),
            models.Index(fields=["destination", "status"]),
        ]

    def __str__(self):
        return f"{self.session} → {self.destination} ({self.days}d)"


# =========================================================
# 📦 PACKAGE SELECTION
# =========================================================

class PackageSelection(models.Model):
    """
    Records which rule-based package a user selected from the
    STAGE_PACKAGE options list.
    """

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="package_selections",
    )

    travel_request = models.ForeignKey(
        TravelRequest,
        on_delete=models.CASCADE,
        related_name="package_selections",
        null=True,
        blank=True,
    )

    # ── Package details ───────────────────────────────
    package_index = models.IntegerField(
        help_text="1-based index of the package in the generated list"
    )
    package_title = models.CharField(max_length=255)
    route = models.JSONField(
        default=list,
        help_text="Ordered list of cities in the selected route",
    )
    highlights = models.JSONField(default=list, blank=True)

    # ── Generated itinerary ───────────────────────────
    generated_itinerary = models.TextField(blank=True, default="")

    # ── Audit ─────────────────────────────────────────
    raw_packages_shown = models.JSONField(
        default=list,
        blank=True,
        help_text="All packages that were shown when user made their choice",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.session} → {self.package_title}"


# =========================================================
# 📅 CUSTOM ITINERARY  (Day-wise Flow submission)
# =========================================================

class CustomItinerary(models.Model):
    """
    Created when a user submits a FLOW_DAYWISE_* WhatsApp Flow.
    day_data stores the per-day activity/stay list.
    generated_itinerary is the Gemini-formatted output.
    """

    FLOW_CHOICES = [
        ("FLOW_DAYWISE_3", "3-Day Custom"),
        ("FLOW_DAYWISE_4", "4-Day Custom"),
        ("FLOW_DAYWISE_5", "5-Day Custom"),
        ("FLOW_DAYWISE_6", "6-Day Custom"),
    ]

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="custom_itineraries",
    )

    travel_request = models.ForeignKey(
        TravelRequest,
        on_delete=models.CASCADE,
        related_name="custom_itineraries",
        null=True,
        blank=True,
    )

    flow_id = models.CharField(
        max_length=30,
        choices=FLOW_CHOICES,
        help_text="Which day-wise flow was submitted",
    )

    days = models.IntegerField()

    # ── Submitted data ────────────────────────────────
    day_data = models.JSONField(
        default=list,
        help_text="List of {day, activity, stay} dicts submitted by user",
    )

    # ── Generated output ──────────────────────────────
    generated_itinerary = models.TextField(blank=True, default="")

    # ── Audit ─────────────────────────────────────────
    raw_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Raw nfm_reply payload for auditing",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.session} → {self.days}d custom itinerary"


# =========================================================
# 👥 GROUP TOUR LEAD
# =========================================================

class GroupTourLead(models.Model):
    """
    Created when a user chooses Group Tour for Rameshwaram or Varanasi
    and selects a departure date.
    """

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="group_tour_leads",
    )

    travel_request = models.ForeignKey(
        TravelRequest,
        on_delete=models.CASCADE,
        related_name="group_tour_leads",
        null=True,
        blank=True,
    )

    destination = models.CharField(max_length=255, db_index=True)

    departure_date = models.CharField(
        max_length=20,
        help_text="Selected departure date string, e.g. '14 Aug'",
    )

    adults = models.IntegerField(default=2)
    children_count = models.IntegerField(default=0)
    children_ages = models.JSONField(default=list, blank=True)

    # ── Itinerary delivered ────────────────────────────
    itinerary_sent = models.TextField(blank=True, default="")

    # ── Sales handoff ─────────────────────────────────
    handed_off = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["destination", "departure_date"]),
        ]

    def __str__(self):
        return f"{self.session} → {self.destination} on {self.departure_date}"


# =========================================================
# 🧾 ITINERARY MODEL
# =========================================================

class Itinerary(models.Model):

    STATUS_CHOICES = [
        ("generated", "Generated"),
        ("edited",    "Edited"),
        ("approved",  "Approved"),
        ("sent",      "Sent"),
    ]

    title = models.CharField(max_length=255, blank=True, null=True)
    generated_by_ai = models.TextField()
    edited_version = models.TextField(blank=True, null=True)
    final_version = models.TextField(blank=True, null=True)
    generated_places = models.JSONField(default=list, blank=True)
    total_days = models.IntegerField(default=0)
    estimated_budget = models.IntegerField(default=0)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="generated")
    edited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title or f"Itinerary #{self.id}"


# =========================================================
# 📞 LEADS
# =========================================================

class Lead(models.Model):

    STATUS_CHOICES = [
        ("new",       "New"),
        ("hot",       "Hot"),
        ("followup",  "Follow Up"),
        ("quoted",    "Quoted"),
        ("converted", "Converted"),
        ("closed",    "Closed"),
    ]

    PRIORITY_CHOICES = [
        ("low",    "Low"),
        ("medium", "Medium"),
        ("high",   "High"),
    ]

    session = models.OneToOneField(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="lead",
    )

    full_name = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=20, db_index=True)
    email = models.EmailField(blank=True, null=True)
    destination = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    departure_city = models.CharField(max_length=255, blank=True, null=True)
    travel_date = models.CharField(max_length=255, blank=True, null=True)
    budget = models.CharField(max_length=255, blank=True, null=True)
    travellers = models.IntegerField(default=1)
    lead_score = models.IntegerField(default=0)
    
    # Widget/Website lead tracking
    source = models.CharField(max_length=50, default="whatsapp", help_text="Source of lead: whatsapp, website, etc.")
    page_url = models.URLField(blank=True, null=True, help_text="Page URL where lead was created")
    browser = models.CharField(max_length=100, blank=True, null=True, help_text="Browser information")
    device = models.CharField(max_length=50, blank=True, null=True, help_text="Device type: Mobile, Tablet, Desktop")

    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="medium")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new")

    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="assigned_leads",
    )

    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.phone} - {self.destination}"


# =========================================================
# 🏝️ PACKAGE MODEL
# =========================================================

class Package(models.Model):

    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True, null=True)
    destination = models.CharField(max_length=100, db_index=True)
    days = models.IntegerField()
    nights = models.IntegerField(default=0)
    price = models.IntegerField()
    offer_price = models.IntegerField(blank=True, null=True)
    hotel_type = models.CharField(max_length=50, blank=True, null=True)

    meals_included = models.BooleanField(default=True)
    flight_included = models.BooleanField(default=False)
    sightseeing_included = models.BooleanField(default=True)
    transfer_included = models.BooleanField(default=True)

    itinerary = models.TextField()
    highlights = models.JSONField(default=list, blank=True)
    exclusions = models.JSONField(default=list, blank=True)
    cover_image = models.URLField(blank=True, null=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} - ₹{self.price}"


# =========================================================
# ❓ FAQ MODEL
# =========================================================

class FAQ(models.Model):

    CATEGORY_CHOICES = [
        ("destination", "Destination"),
        ("pricing",     "Pricing"),
        ("itinerary",   "Itinerary"),
        ("comparison",  "Comparison"),
        ("logistics",   "Logistics"),
        ("trust",       "Trust"),
        ("visa",        "Visa"),
        ("hotel",       "Hotel"),
        ("flight",      "Flight"),
    ]

    question = models.TextField(db_index=True)
    answer = models.TextField()
    keywords = models.TextField(help_text="Comma separated keywords")
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    priority = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.question


# =========================================================
# 📝 INTERNAL NOTES
# =========================================================

class InternalNote(models.Model):

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="notes")
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Note - {self.session.session_id}"


# =========================================================
# 👨‍💼 SALES PROFILE
# =========================================================

class SalesProfile(models.Model):

    ROLE_CHOICES = [
        ("sales",   "Sales"),
        ("manager", "Manager"),
        ("admin",   "Admin"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="sales")
    is_active_for_assignment = models.BooleanField(default=True)
    is_active_for_meta = models.BooleanField(default=True, help_text="Receive Meta/WhatsApp leads")
    is_active_for_website = models.BooleanField(default=True, help_text="Receive Website leads")
    assignment_order = models.PositiveIntegerField(default=1)
    is_online = models.BooleanField(default=False)
    total_leads = models.IntegerField(default=0)
    total_conversions = models.IntegerField(default=0)

    # Team leader: a sales person who also sees, and can assign, the chats of
    # the team members picked below (set in Admin → Sales Profiles).
    is_team_leader = models.BooleanField(
        default=False,
        help_text="Can see the chats of the team members below and assign chats to them",
    )
    team_members = models.ManyToManyField(
        User,
        blank=True,
        related_name="team_leader_profiles",
        help_text="Sales people in this team leader's team",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.username


# =========================================================
# 🏷️ CONVERSATION LABEL
# =========================================================

class ConversationLabel(models.Model):

    name = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=20, default="#25D366")
    order = models.IntegerField(default=0)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["order", "name"]


# =========================================================
# 📌 CONVERSATION STATUS
# =========================================================

class ConversationStatus(models.Model):

    session = models.OneToOneField(
        "ChatSession",
        on_delete=models.CASCADE,
        related_name="conv_status",
    )

    label = models.ForeignKey(
        ConversationLabel,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="conversations",
    )

    assigned_to = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="crm_assigned_chats",
    )

    closed = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        label_name = self.label.name if self.label else "No Label"
        return f"{self.session} — {label_name}"


# =========================================================
# ⏰ REMINDER
# =========================================================

class Reminder(models.Model):

    session = models.ForeignKey(
        "ChatSession",
        on_delete=models.CASCADE,
        related_name="reminders",
    )

    note = models.TextField()
    reminder_at = models.DateTimeField()
    done = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_reminders",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reminder for {self.session} at {self.reminder_at}"

    class Meta:
        ordering = ["reminder_at"]


# =========================================================
# 🔄 ROUND ROBIN TRACKER
# =========================================================

class RoundRobinTracker(models.Model):
    last_assigned_order = models.IntegerField(default=0)

    def __str__(self):
        return f"Last Order: {self.last_assigned_order}"


# =========================================================
# 🏝️ DESTINATION ASSIGNMENT RULE
# =========================================================

class DestinationAssignment(models.Model):
    """
    Maps sales persons to specific destinations.
    When a lead has a matching destination, it gets assigned
    to the corresponding sales person instead of round-robin.
    """
    
    sales_person = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="destination_assignments",
    )
    
    destination = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Destination name (e.g., 'Rameshwaram', 'Varanasi')"
    )
    
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ("sales_person", "destination")
        ordering = ["destination", "sales_person"]
        verbose_name = "Destination Assignment"
        verbose_name_plural = "Destination Assignments"
    
    def __str__(self):
        return f"{self.sales_person.username} → {self.destination}"


# =========================================================
# 📋 CRM TEMPLATE
# =========================================================

class CRMTemplate(models.Model):

    title = models.CharField(max_length=255)
    whatsapp_template_id = models.CharField(
        max_length=255,
        help_text="WhatsApp template ID from Meta Business Manager (numeric ID)",
        blank=True,
        default=""
    )
    template_name = models.CharField(
        max_length=255,
        help_text="WhatsApp template name (approved by Meta)",
        blank=True,
        default=""
    )
    template_text = models.TextField(
        help_text="Template message content (for reference)"
    )
    language = models.CharField(
        max_length=10,
        default="en",
        help_text="Language code the template was approved in (e.g. en, en_US, hi)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        verbose_name = "CRM Template"
        verbose_name_plural = "CRM Templates"

    def __str__(self):
        return self.title
    


# =========================================================
# 🎯 USER ENGAGEMENT TRACKING
# =========================================================

class UserEngagement(models.Model):
    """
    Tracks user engagement metrics to calculate quality scores
    and detect potential spam risks.
    """
    
    session = models.OneToOneField(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="engagement"
    )
    
    # Engagement metrics
    message_count = models.IntegerField(default=0)
    user_response_count = models.IntegerField(default=0)
    bot_message_count = models.IntegerField(default=0)
    
    # Response timing
    first_response_time_seconds = models.IntegerField(null=True, blank=True)
    avg_response_time_seconds = models.FloatField(null=True, blank=True)
    
    # Quality indicators
    positive_responses = models.IntegerField(default=0)  # Interested, booking, etc.
    negative_responses = models.IntegerField(default=0)  # Stop, not interested, etc.
    neutral_responses = models.IntegerField(default=0)
    
    # Message delivery tracking
    successful_deliveries = models.IntegerField(default=0)
    failed_deliveries = models.IntegerField(default=0)
    
    # Risk indicators
    flagged_as_spam = models.BooleanField(default=False)
    spam_flag_count = models.IntegerField(default=0)
    opt_out_requested = models.BooleanField(default=False)
    
    # Quality score (0-100)
    quality_score = models.IntegerField(default=50)
    
    # Timestamps
    last_engagement = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "User Engagement"
        verbose_name_plural = "User Engagements"
    
    def __str__(self):
        return f"{self.session.session_id} - Score: {self.quality_score}"


# =========================================================
# ✅ OPT-IN RECORD
# =========================================================

class OptInRecord(models.Model):
    """
    Records user opt-in consent for WhatsApp messaging.
    Ensures compliance with WhatsApp policies.
    """
    
    phone_number = models.CharField(max_length=20, db_index=True)
    
    # Opt-in details
    opt_in_method = models.CharField(
        max_length=50,
        choices=[
            ('web_form', 'Web Form'),
            ('whatsapp', 'WhatsApp Initiated'),
            ('manual', 'Manual Entry'),
            ('import', 'Imported List'),
        ]
    )
    
    opt_in_timestamp = models.DateTimeField(auto_now_add=True)
    consent_text = models.TextField(blank=True)
    
    # Double opt-in
    double_opt_in_confirmed = models.BooleanField(default=False)
    double_opt_in_timestamp = models.DateTimeField(null=True, blank=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    opt_out_timestamp = models.DateTimeField(null=True, blank=True)
    opt_out_reason = models.CharField(max_length=255, blank=True)
    
    # Session reference
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opt_in_records"
    )
    
    class Meta:
        verbose_name = "Opt-In Record"
        verbose_name_plural = "Opt-In Records"
        ordering = ["-opt_in_timestamp"]
    
    def __str__(self):
        return f"{self.phone_number} - {self.opt_in_method}"


# =========================================================
# 🚨 SPAM RISK ALERT
# =========================================================

class SpamRiskAlert(models.Model):
    """
    Records spam risk alerts and suspicious patterns detected
    by the spam detection system.
    """
    
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="spam_alerts"
    )
    
    # Risk details
    risk_level = models.CharField(
        max_length=20,
        choices=[
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
            ('critical', 'Critical'),
        ]
    )
    
    risk_type = models.CharField(
        max_length=50,
        choices=[
            ('low_engagement', 'Low Engagement'),
            ('high_failure_rate', 'High Failure Rate'),
            ('spam_pattern', 'Spam Pattern'),
            ('opt_out', 'Opt Out Requested'),
            ('suspicious_timing', 'Suspicious Timing'),
            ('volume_spike', 'Volume Spike'),
        ]
    )
    
    description = models.TextField()
    
    # Action taken
    action_taken = models.CharField(
        max_length=50,
        choices=[
            ('none', 'No Action'),
            ('flagged', 'Flagged Only'),
            ('limited', 'Rate Limited'),
            ('stopped', 'Messaging Stopped'),
            ('blocked', 'Blocked'),
        ],
        default='none'
    )
    
    # Resolution
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Spam Risk Alert"
        verbose_name_plural = "Spam Risk Alerts"
        ordering = ["-created_at"]
    
    def __str__(self):
        return f"{self.session.session_id} - {self.risk_level} {self.risk_type}"

# =========================================================
# 🏷️ CONTACT TAG
# =========================================================

class ContactTag(models.Model):
    """Label attached to contacts (ChatSession) for segmentation."""

    name = models.CharField(max_length=60, unique=True)
    color = models.CharField(max_length=9, default="#25D366")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_contact_tags",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Contact Tag"
        verbose_name_plural = "Contact Tags"

    def __str__(self):
        return self.name


# =========================================================
# 🎯 SEGMENT  (saved audience filter)
# =========================================================

class Segment(models.Model):
    """
    A saved set of contact filters. Segments are dynamic: the matching
    contacts are re-evaluated every time the segment is used.
    """

    name = models.CharField(max_length=120, unique=True)
    description = models.CharField(max_length=255, blank=True, default="")
    filters = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_segments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# =========================================================
# 📣 CAMPAIGN  (WhatsApp broadcast)
# =========================================================

class Campaign(models.Model):

    STATUS_CHOICES = [
        ("draft",     "Draft"),
        ("scheduled", "Scheduled"),
        ("running",   "Running"),
        ("paused",    "Paused"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("failed",    "Failed"),
    ]

    HEADER_MEDIA_CHOICES = [
        ("",         "None"),
        ("image",    "Image"),
        ("video",    "Video"),
        ("document", "Document"),
    ]

    name = models.CharField(max_length=255)

    template = models.ForeignKey(
        CRMTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns",
    )
    # Snapshot of the template at launch so history survives template edits.
    template_title = models.CharField(max_length=255, blank=True, default="")
    template_name = models.CharField(max_length=255, blank=True, default="")
    template_language = models.CharField(max_length=10, default="en")
    template_text = models.TextField(blank=True, default="")

    # {"1": {"source": "name", "value": "", "fallback": "there"}, ...}
    variable_mapping = models.JSONField(default=dict, blank=True)

    header_media_type = models.CharField(
        max_length=20, choices=HEADER_MEDIA_CHOICES, blank=True, default=""
    )
    header_media_url = models.URLField(max_length=1000, blank=True, default="")
    header_media_filename = models.CharField(max_length=255, blank=True, default="")

    # How the audience was chosen (informational — recipients are materialised)
    audience_type = models.CharField(max_length=20, blank=True, default="filters")
    audience_filters = models.JSONField(default=dict, blank=True)
    segment = models.ForeignKey(
        Segment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns",
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="draft", db_index=True
    )
    scheduled_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    consent_confirmed = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.status})"


class CampaignRecipient(models.Model):

    STATUS_CHOICES = [
        ("pending",   "Pending"),
        ("sending",   "Sending"),
        ("sent",      "Sent"),
        ("delivered", "Delivered"),
        ("read",      "Read"),
        ("failed",    "Failed"),
        ("skipped",   "Skipped"),
    ]

    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="recipients",
    )
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaign_recipients",
    )

    phone = models.CharField(max_length=20)
    name = models.CharField(max_length=255, blank=True, default="")
    # Resolved template variables, e.g. {"1": "Rahul", "2": "Goa"}
    variables = models.JSONField(default=dict, blank=True)
    # Extra per-row data from an uploaded CSV (used by "CSV column" variables)
    extra = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    claimed_at = models.DateTimeField(null=True, blank=True)

    whatsapp_message_id = models.CharField(
        max_length=255, blank=True, default="", db_index=True
    )
    error_code = models.CharField(max_length=20, blank=True, default="")
    error_message = models.TextField(blank=True, default="")

    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        unique_together = ("campaign", "phone")
        indexes = [
            models.Index(fields=["campaign", "status"]),
        ]

    def __str__(self):
        return f"{self.campaign_id} → {self.phone} ({self.status})"


# =========================================================
# CATEGORY-WISE LEAD ROUTING
# =========================================================

class LeadCategoryRule(models.Model):
    """
    Which sales people get new leads of a category (round robin between them).
    Set in Admin -> Lead category rules. A category with no active rule, or
    no active people, falls back to the normal website / Meta round robin.
    """

    CATEGORY_CHOICES = [
        ("personal_tour", "Personal Tour"),
        ("cab", "Cab"),
        ("tour_1day", "1 Day Tour"),
        ("tour_2day", "2 Day Tour"),
        ("route", "Route"),
    ]

    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, unique=True)
    sales_people = models.ManyToManyField(
        User, blank=True, related_name="lead_category_rules",
        help_text="New leads of this category go to these people in turn",
    )
    is_active = models.BooleanField(default=True)
    last_assigned_user_id = models.IntegerField(default=0, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lead category rule"
        verbose_name_plural = "Lead category rules"
        ordering = ["category"]

    def __str__(self):
        return self.get_category_display()


# =========================================================
# BOOKING (www.trypdeals.com cab / short tour with a PayU advance)
# =========================================================

class Booking(models.Model):
    """
    One row per website booking code (TD-XXXXXX), kept up to date by the
    booking webhook (website_bookings.save_booking). Listed on CRM -> Booking.
    """

    PAYMENT_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("failed", "Failed"),
        ("amount_mismatch", "Paid (amount mismatch)"),
    ]
    TYPE_CHOICES = [
        ("cab", "Cab"),
        ("tour", "Tour"),
    ]

    code = models.CharField(max_length=20, unique=True)
    session = models.ForeignKey(
        "ChatSession", on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings",
    )
    booking_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default="tour")
    category = models.CharField(max_length=30, choices=LeadCategoryRule.CATEGORY_CHOICES, default="personal_tour")
    title = models.CharField(max_length=255, blank=True, default="")
    customer_name = models.CharField(max_length=255, blank=True, default="")
    phone = models.CharField(max_length=20, blank=True, default="", db_index=True)
    email = models.CharField(max_length=254, blank=True, default="")
    travel_date = models.CharField(max_length=100, blank=True, default="")
    travellers = models.PositiveIntegerField(default=0)
    amount = models.PositiveIntegerField(default=0, help_text="Advance amount (Rs.)")
    estimated_total = models.PositiveIntegerField(default=0, help_text="Estimated package / cab fare (Rs.)")
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default="pending", db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    data = models.JSONField(default=dict, blank=True, help_text="The booking as the website sent it")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} - {self.title or self.get_booking_type_display()}"
