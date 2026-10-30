from django.db import transaction
from django.db.models import F as models_F

from .models import (
    ConversationLabel,
    ConversationStatus,
    SalesProfile,
    RoundRobinTracker,
    DestinationAssignment,
)
from .crm_lead_signals import push_label_notification

# =========================================================
# LABEL NAMES
# =========================================================
# These are the exact (case-insensitive) names that must already exist as
# ConversationLabel rows in the Django admin before any of the automation
# below can apply them. We NEVER auto-create labels — see _fetch_label().

LABEL_FOLLOW_UP = "FOLLOW UP"
LABEL_NEW_LEAD = "NEW LEAD"
LABEL_TODAY = "TODAY"


# =========================================================
# SOURCE-BASED ASSIGNMENT
# =========================================================

def assign_website_lead(session):
    """
    Assign website leads using a dedicated assignment pool and logic.
    Website leads come from the widget on the website.
    
    Returns the assigned user if successful, None otherwise.
    """
    try:
        print(f"[WEBSITE LEAD ASSIGNMENT] Starting assignment for session {session.id}")
        
        # First try destination-based assignment
        destination_assigned = assign_by_destination(session)
        if destination_assigned:
            print(f"[WEBSITE LEAD ASSIGNMENT] Assigned by destination to {destination_assigned.username}")
            return destination_assigned
        
        print(f"[WEBSITE LEAD ASSIGNMENT] No destination assignment, using website-specific round-robin")
        
        with transaction.atomic():
            # Use a separate tracker for website leads
            tracker = (
                RoundRobinTracker.objects
                .select_for_update()
                .get_or_create(id=2)[0]  # Use ID 2 for website leads
            )
            print(f"[WEBSITE ROUND ROBIN] Tracker last_assigned_order: {tracker.last_assigned_order}")

            # Filter for agents who are active for website lead assignment
            agents = SalesProfile.objects.filter(
                is_active_for_assignment=True,
                is_active_for_website=True,
                role="sales",
            ).order_by("assignment_order")
            
            print(f"[WEBSITE ROUND ROBIN] Found {agents.count()} active sales agents")
            
            if not agents.exists():
                print("[WEBSITE ROUND ROBIN] No active sales agents found")
                return None

            # Pick the next agent using round-robin
            next_agent = agents.filter(
                assignment_order__gt=tracker.last_assigned_order
            ).first()

            if not next_agent:
                print(f"[WEBSITE ROUND ROBIN] Wrapping to first agent")
                next_agent = agents.first()

            print(f"[WEBSITE ROUND ROBIN] Selected agent: {next_agent.user.username}")

            session.assigned_sales_person = next_agent.user
            session.save(update_fields=["assigned_sales_person"])
            print(f"[WEBSITE ROUND ROBIN] Assigned session {session.id} to {next_agent.user.username}")

            tracker.last_assigned_order = next_agent.assignment_order
            tracker.save(update_fields=["last_assigned_order"])

            next_agent.total_leads += 1
            next_agent.save(update_fields=["total_leads"])

        print(f"[WEBSITE ROUND ROBIN] Lead assigned to {next_agent.user.username}")
        return next_agent.user

    except Exception as e:
        print(f"[WEBSITE ROUND ROBIN ERROR] {e}")
        import traceback
        traceback.print_exc()
        return None


def assign_meta_lead(session):
    """
    Assign Meta/WhatsApp leads using a dedicated assignment pool and logic.
    Meta leads come from WhatsApp/Meta platforms.
    
    Returns the assigned user if successful, None otherwise.
    """
    try:
        print(f"[META LEAD ASSIGNMENT] Starting assignment for session {session.id}")
        
        # First try destination-based assignment
        destination_assigned = assign_by_destination(session)
        if destination_assigned:
            print(f"[META LEAD ASSIGNMENT] Assigned by destination to {destination_assigned.username}")
            return destination_assigned
        
        print(f"[META LEAD ASSIGNMENT] No destination assignment, using meta-specific round-robin")
        
        with transaction.atomic():
            # Use a separate tracker for meta leads
            tracker = (
                RoundRobinTracker.objects
                .select_for_update()
                .get_or_create(id=3)[0]  # Use ID 3 for meta leads
            )
            print(f"[META ROUND ROBIN] Tracker last_assigned_order: {tracker.last_assigned_order}")

            # Filter for agents who are active for meta lead assignment
            agents = SalesProfile.objects.filter(
                is_active_for_assignment=True,
                is_active_for_meta=True,
                role="sales",
            ).order_by("assignment_order")
            
            print(f"[META ROUND ROBIN] Found {agents.count()} active sales agents")
            
            if not agents.exists():
                print("[META ROUND ROBIN] No active sales agents found")
                return None

            # Pick the next agent using round-robin
            next_agent = agents.filter(
                assignment_order__gt=tracker.last_assigned_order
            ).first()

            if not next_agent:
                print(f"[META ROUND ROBIN] Wrapping to first agent")
                next_agent = agents.first()

            print(f"[META ROUND ROBIN] Selected agent: {next_agent.user.username}")

            session.assigned_sales_person = next_agent.user
            session.save(update_fields=["assigned_sales_person"])
            print(f"[META ROUND ROBIN] Assigned session {session.id} to {next_agent.user.username}")

            tracker.last_assigned_order = next_agent.assignment_order
            tracker.save(update_fields=["last_assigned_order"])

            next_agent.total_leads += 1
            next_agent.save(update_fields=["total_leads"])

        print(f"[META ROUND ROBIN] Lead assigned to {next_agent.user.username}")
        return next_agent.user

    except Exception as e:
        print(f"[META ROUND ROBIN ERROR] {e}")
        import traceback
        traceback.print_exc()
        return None


def assign_by_source(session):
    """
    Main entry point for source-based assignment.
    Routes to the appropriate assignment method based on lead source.
    
    Returns the assigned user if successful, None otherwise.
    """
    try:
        # Get the lead source
        lead_source = session.lead.source if hasattr(session, 'lead') and session.lead else "whatsapp"
        
        print(f"[SOURCE ASSIGNMENT] Lead source: {lead_source}")

        # Category rules (Admin -> Lead category rules) come first.
        category_assigned = assign_by_category(session)
        if category_assigned:
            return category_assigned

        if lead_source in ("website", "google_ads"):
            # Google Ads Lead Form leads are a filled-in form, same as the
            # website widget — route them through the same pool/reps.
            return assign_website_lead(session)
        else:
            # Default to meta/whatsapp assignment for all other sources
            return assign_meta_lead(session)
            
    except Exception as e:
        print(f"[SOURCE ASSIGNMENT ERROR] {e}")
        import traceback
        traceback.print_exc()
        return None


# =========================================================
# CATEGORY-BASED ASSIGNMENT
# =========================================================

def _tour_days(*texts):
    """1 or 2 for a 1-day / 2-day tour named in any of the texts, else None."""
    import re
    for text in texts:
        m = re.search(r"\b([12])[\s-]*days?\b", str(text or ""), re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def lead_category(session):
    """
    The lead's category for routing: personal_tour, cab, tour_1day,
    tour_2day or route. Set by the website webhooks and the bot's cab flow
    (session.data["lead_category"]); anything else is a personal tour.
    """
    data = session.data if isinstance(session.data, dict) else {}
    category = data.get("lead_category")
    if category:
        return category
    booking = data.get("website_booking") or {}
    if booking.get("type") == "cab":
        return "cab"
    if booking:
        tour = booking.get("tour") or {}
        days = _tour_days(tour.get("duration"), tour.get("title"), tour.get("slug"))
        if days:
            return f"tour_{days}day"
    return "personal_tour"


def assign_by_category(session):
    """Round robin among the people of the category's rule; None if no rule applies."""
    from .models import LeadCategoryRule

    category = lead_category(session)
    try:
        with transaction.atomic():
            rule = (LeadCategoryRule.objects.select_for_update()
                    .filter(category=category, is_active=True).first())
            if not rule:
                return None
            people = list(rule.sales_people.filter(is_active=True).order_by("id"))
            if not people:
                return None
            next_user = next((u for u in people if u.id > rule.last_assigned_user_id), people[0])
            rule.last_assigned_user_id = next_user.id
            rule.save(update_fields=["last_assigned_user_id"])
            session.assigned_sales_person = next_user
            session.save(update_fields=["assigned_sales_person"])
            SalesProfile.objects.filter(user=next_user).update(total_leads=models_F("total_leads") + 1)
        print(f"[CATEGORY ASSIGNMENT] {category}: session {session.id} -> {next_user.username}")
        return next_user
    except Exception as e:
        print(f"[CATEGORY ASSIGNMENT ERROR] {e}")
        return None


# =========================================================
# DESTINATION-BASED ASSIGNMENT
# =========================================================

def assign_by_destination(session):
    """
    Check if the session has a destination and assign to the corresponding
    sales person based on destination assignment rules.
    
    Returns the assigned user if a destination match is found, None otherwise.
    """
    try:
        # Check both current_destination field and data dictionary
        destination = session.current_destination or session.data.get("destination")
        if not destination:
            print(f"[DESTINATION ASSIGNMENT] No destination for session {session.id}")
            return None
        
        print(f"[DESTINATION ASSIGNMENT] Checking destination: {destination}")
        
        # Look for active destination assignments
        destination_assignments = DestinationAssignment.objects.filter(
            destination__iexact=destination,
            is_active=True
        ).select_related('sales_person')
        
        if not destination_assignments.exists():
            print(f"[DESTINATION ASSIGNMENT] No assignment found for destination: {destination}")
            return None
        
        # Get the first matching assignment (could add load balancing logic here if needed)
        assignment = destination_assignments.first()
        sales_person = assignment.sales_person
        
        print(f"[DESTINATION ASSIGNMENT] Found assignment: {sales_person.username} → {destination}")
        
        # Check if the sales person is active for assignment
        try:
            sales_profile = SalesProfile.objects.get(user=sales_person)
            if not sales_profile.is_active_for_assignment or sales_profile.role != "sales":
                print(f"[DESTINATION ASSIGNMENT] Sales person {sales_person.username} is not active for assignment")
                return None
        except SalesProfile.DoesNotExist:
            print(f"[DESTINATION ASSIGNMENT] Sales profile not found for {sales_person.username}")
            return None
        
        # Assign the sales person
        session.assigned_sales_person = sales_person
        session.save(update_fields=["assigned_sales_person"])
        print(f"[DESTINATION ASSIGNMENT] Assigned session {session.id} to {sales_person.username}")
        
        # Update sales person stats
        sales_profile.total_leads += 1
        sales_profile.save(update_fields=["total_leads"])
        print(f"[DESTINATION ASSIGNMENT] Updated {sales_person.username} total_leads to {sales_profile.total_leads}")
        
        return sales_person
        
    except Exception as e:
        print(f"[DESTINATION ASSIGNMENT ERROR] {e}")
        import traceback
        traceback.print_exc()
        return None


# =========================================================
# ROUND-ROBIN ASSIGNMENT
# =========================================================

def assign_next_sales_agent(session):
    """
    Assign the next available sales agent using a strict round-robin sequence.
    First checks for destination-based assignment, falls back to round-robin.

    The entire read-decide-write cycle is inside select_for_update() so the
    DB row is row-locked for the duration of the transaction.  Any concurrent
    request waits at the SELECT … FOR UPDATE line until the first transaction
    commits, then re-reads the freshly-updated order value and picks the next
    agent — preventing the race condition where two requests assign the same
    agent simultaneously.
    """

    try:
        print(f"[ASSIGNMENT] Starting assignment for session {session.id}")
        
        # First try destination-based assignment
        destination_assigned = assign_by_destination(session)
        if destination_assigned:
            print(f"[ASSIGNMENT] Assigned by destination to {destination_assigned.username}")
            return destination_assigned
        
        print(f"[ASSIGNMENT] No destination assignment found, falling back to round-robin")
        
        with transaction.atomic():

            # Lock the tracker row so no concurrent request can read it
            # until this transaction finishes.
            tracker = (
                RoundRobinTracker.objects
                .select_for_update()
                .get_or_create(id=1)[0]
            )
            print(f"[ROUND ROBIN] Tracker last_assigned_order: {tracker.last_assigned_order}")

            agents = SalesProfile.objects.filter(
                is_active_for_assignment=True,
                role="sales",
            ).order_by("assignment_order")
            
            print(f"[ROUND ROBIN] Found {agents.count()} active sales agents")
            
            for agent in agents:
                print(f"[ROUND ROBIN] Agent: {agent.user.username}, order: {agent.assignment_order}, active: {agent.is_active_for_assignment}")

            if not agents.exists():
                print("[ROUND ROBIN] No active sales agents found")
                return None

            # Pick the first agent whose order is strictly greater than the
            # last assigned order.  If none is found (we reached the end of
            # the list), wrap back to the first agent.
            next_agent = agents.filter(
                assignment_order__gt=tracker.last_assigned_order
            ).first()

            if not next_agent:
                print(f"[ROUND ROBIN] No agent with order > {tracker.last_assigned_order}, wrapping to first agent")
                next_agent = agents.first()

            print(f"[ROUND ROBIN] Selected agent: {next_agent.user.username} (order: {next_agent.assignment_order})")

            session.assigned_sales_person = next_agent.user
            session.save(update_fields=["assigned_sales_person"])
            print(f"[ROUND ROBIN] Assigned session {session.id} to {next_agent.user.username}")

            # Advance the pointer INSIDE the same transaction so it's always
            # consistent with the assignment that just happened.
            tracker.last_assigned_order = next_agent.assignment_order
            tracker.save(update_fields=["last_assigned_order"])
            print(f"[ROUND ROBIN] Updated tracker last_assigned_order to {next_agent.assignment_order}")

            next_agent.total_leads += 1
            next_agent.save(update_fields=["total_leads"])
            print(f"[ROUND ROBIN] Updated {next_agent.user.username} total_leads to {next_agent.total_leads}")

        print(
            f"[ROUND ROBIN] Lead assigned to {next_agent.user.username}"
        )

        return next_agent.user

    except Exception as e:
        print(f"[ROUND ROBIN ERROR] {e}")
        import traceback
        traceback.print_exc()
        return None


# =========================================================
# LABEL HELPERS
# Shared plumbing used by both mark_lead_follow_up() and mark_lead_hot().
# =========================================================

def _fetch_label(label_name):
    """
    Fetch a ConversationLabel by case-insensitive name.

    We NEVER use get_or_create() here — silently creating a phantom label
    when the real one is missing (wrong casing, deleted/recreated row, etc.)
    produces duplicate labels with none of the configured color/order values.
    If the label is genuinely missing, the admin must create it first.

    Returns: (label_or_None, error_message_or_None)
    """
    try:
        return ConversationLabel.objects.get(name__iexact=label_name), None
    except ConversationLabel.DoesNotExist:
        return None, (
            f"'{label_name}' label not found in the database. "
            f"Please create it via the Django admin before it can be applied."
        )
    except ConversationLabel.MultipleObjectsReturned:
        # If duplicates exist (e.g. from a historical get_or_create bug), use
        # the one with the lowest PK (the original) and log a warning.
        label = (
            ConversationLabel.objects
            .filter(name__iexact=label_name)
            .order_by("id")
            .first()
        )
        print(
            f"[LABEL] WARNING — multiple '{label_name}' labels found. "
            f"Using id={label.id}. Please clean up duplicates via admin."
        )
        return label, None


def _apply_conversation_label(session, label_name, upgrade_from=()):
    """
    Set session's ConversationStatus.label to `label_name`, subject to:

      • session.is_human_takeover  -> hands off entirely, nothing changes.
      • status.label is None       -> always safe to set.
      • status.label.name (case-insensitive) is one of `upgrade_from`
                                    -> safe automation-to-automation upgrade
                                       (e.g. FOLLOW UP -> HOT as a lead warms
                                       up through the funnel).
      • anything else (a human agent, or some other automated status such as
        "PAID" / "PENDING", already owns this lead) -> left completely
        untouched.

    This is the single choke point both mark_lead_follow_up() and
    mark_lead_hot() route through, so the "never silently clobber a label
    someone else already set" rule only has to be implemented once.

    Returns True if the label was (re)applied, False otherwise.
    """
    print(f"[LABEL] _apply_conversation_label called for session {session.id}, label: {label_name}")
    print(f"[LABEL] session.is_human_takeover: {session.is_human_takeover}")
    
    if session.is_human_takeover:
        print(f"[LABEL] Skipped — session {session.id} is under human takeover")
        return False

    label, err = _fetch_label(label_name)
    print(f"[LABEL] Fetched label: {label}, error: {err}")
    if label is None:
        print(f"[LABEL] ERROR — {err}")
        return False

    status, _ = ConversationStatus.objects.get_or_create(session=session)
    upgrade_names = {u.upper() for u in upgrade_from}
    current_name  = status.label.name.upper() if status.label else None
    
    print(f"[LABEL] Current label: {current_name}, upgrade_from: {upgrade_names}")

    if status.label is None or current_name in upgrade_names:
        status.label = label
        status.save(update_fields=["label"])
        print(f"[LABEL] Session {session.id} labelled {label.name}")
        return True

    print(
        f"[LABEL] Session {session.id} already has label "
        f"'{status.label.name}' — not overwriting with '{label_name}'"
    )
    return False


# =========================================================
# MARK LEAD — NEW LEAD (was FOLLOW UP)
# =========================================================

def mark_lead_new_lead(session):
    try:
        if session.is_human_takeover:
            print(f"[NEW LEAD] Skipped — session {session.id} is under human takeover")
            return

        applied = _apply_conversation_label(session, LABEL_NEW_LEAD, upgrade_from=())

        if not session.assigned_sales_person:
            assigned_user = assign_by_source(session)
            if assigned_user:
                status, _ = ConversationStatus.objects.get_or_create(session=session)
                if status.assigned_to is None:
                    status.assigned_to = assigned_user
                    status.save(update_fields=["assigned_to"])
        else:
            print(
                f"[NEW LEAD] Session {session.id} already assigned to "
                f"{session.assigned_sales_person.username}"
            )

        # ── Human takeover ──────────────────────────────────────
        if not session.is_human_takeover:
            session.is_human_takeover = True
            session.save(update_fields=["is_human_takeover"])
            print(f"[NEW LEAD] Session {session.id} set to human takeover")

        # Notify AFTER assignment so push_label_notification finds assigned_sales_person
        if applied:
            session.refresh_from_db(fields=["assigned_sales_person"])
            push_label_notification(session, LABEL_NEW_LEAD)

    except Exception as e:
        print(f"[NEW LEAD LABEL ERROR] {e}")


# =========================================================
# MARK LEAD — FOLLOW UP (was HOT)
# =========================================================

def mark_lead_follow_up(session):
    try:
        if session.is_human_takeover:
            print(f"[FOLLOW UP LEAD] Skipped — session {session.id} is under human takeover")
            return

        applied = _apply_conversation_label(session, LABEL_FOLLOW_UP)

        status, _ = ConversationStatus.objects.get_or_create(session=session)
        if not status.label or status.label.name.upper() != LABEL_FOLLOW_UP:
            return

        if not session.assigned_sales_person:
            assigned_user = assign_by_source(session)
            if assigned_user:
                status.refresh_from_db(fields=["assigned_to"])
                if status.assigned_to is None:
                    status.assigned_to = assigned_user
                    status.save(update_fields=["assigned_to"])
        else:
            print(
                f"[FOLLOW UP LEAD] Session {session.id} already assigned to "
                f"{session.assigned_sales_person.username} — skipping auto-assign"
            )

        # ── Human takeover ──────────────────────────────────────
        if not session.is_human_takeover:
            session.is_human_takeover = True
            session.save(update_fields=["is_human_takeover"])
            print(f"[FOLLOW UP LEAD] Session {session.id} set to human takeover")

        # Notify AFTER assignment so push_label_notification finds assigned_sales_person
        if applied:
            session.refresh_from_db(fields=["assigned_sales_person"])
            push_label_notification(session, LABEL_FOLLOW_UP)

    except Exception as e:
        print(f"[FOLLOW UP LABEL ERROR] {e}")


# =========================================================
# MARK LEAD — TODAY (first follow-up)
# =========================================================

def mark_lead_today(session):
    try:
        print(f"[TODAY LEAD] Starting mark_lead_today for session {session.id}")
        print(f"[TODAY LEAD] Current is_human_takeover: {session.is_human_takeover}")
        print(f"[TODAY LEAD] Current assigned_sales_person: {session.assigned_sales_person}")

        # Don't skip if already under human takeover - still want to send notification
        # if session.is_human_takeover:
        #     print(f"[TODAY LEAD] Skipped — session {session.id} is under human takeover")
        #     return

        applied = _apply_conversation_label(session, LABEL_TODAY)
        print(f"[TODAY LEAD] Label applied: {applied}")

        if not session.assigned_sales_person:
            print(f"[TODAY LEAD] No assigned sales person, calling assign_by_source")
            assigned_user = assign_by_source(session)
            print(f"[TODAY LEAD] Assigned user: {assigned_user}")
            if assigned_user:
                status, _ = ConversationStatus.objects.get_or_create(session=session)
                if status.assigned_to is None:
                    status.assigned_to = assigned_user
                    status.save(update_fields=["assigned_to"])
                    print(f"[TODAY LEAD] Updated ConversationStatus assigned_to to {assigned_user.username}")
        else:
            print(
                f"[TODAY LEAD] Session {session.id} already assigned to "
                f"{session.assigned_sales_person.username}"
            )

        # ── Human takeover ──────────────────────────────────────
        if not session.is_human_takeover:
            session.is_human_takeover = True
            session.save(update_fields=["is_human_takeover"])
            print(f"[TODAY LEAD] Session {session.id} set to human takeover")

        # Notify AFTER assignment so push_label_notification finds assigned_sales_person
        if applied:
            session.refresh_from_db(fields=["assigned_sales_person"])
            print(f"[TODAY LEAD] Refreshed session, assigned_sales_person: {session.assigned_sales_person}")
            push_label_notification(session, LABEL_TODAY)
            print(f"[TODAY LEAD] Notification sent for label {LABEL_TODAY}")

    except Exception as e:
        print(f"[TODAY LABEL ERROR] {e}")
        import traceback
        traceback.print_exc()