from django.db import migrations


AI_PLANNER_MESSAGE = (
    "Plan your perfect trip with our AI Trip Planner! 🌟\n\n"
    "Share your destination, dates, and budget — and get a custom itinerary in minutes.\n\n"
    "👉 https://www.trypdeals.com/ai-trip-planner/\n\n"
    "Or reply here with your trip details and our team will help you plan it!"
)

# Keywords that trigger the auto-reply — strictly 1-day trip related
AI_PLANNER_KEYWORDS = (
    "1 day trip, 1 day tour, one day trip, one day tour, 1 day plan, one day plan, "
    "1 din, ek din, 1 din ka trip, 1 din ka tour, ek din ka trip, ek din ka tour, "
    "1 day itinerary, one day itinerary, day trip, day tour, 1 day package, "
    "one day package, 1 day travel, ai planner 1 day"
)


def add_faq_and_template(apps, schema_editor):
    FAQ = apps.get_model("chatbot", "FAQ")
    CRMTemplate = apps.get_model("chatbot", "CRMTemplate")

    FAQ.objects.get_or_create(
        question="1 Day AI Trip Planner kya hai?",
        defaults={
            "answer": AI_PLANNER_MESSAGE,
            "keywords": AI_PLANNER_KEYWORDS,
            "category": "itinerary",
            "priority": 1,
            "is_active": True,
        },
    )

    CRMTemplate.objects.get_or_create(
        title="AI Trip Planner — 1 Day",
        defaults={
            "template_text": AI_PLANNER_MESSAGE,
            "whatsapp_template_id": "",
            "template_name": "",
            "language": "en",
            "buttons": [],
        },
    )


def remove_faq_and_template(apps, schema_editor):
    FAQ = apps.get_model("chatbot", "FAQ")
    CRMTemplate = apps.get_model("chatbot", "CRMTemplate")
    FAQ.objects.filter(question="1 Day AI Trip Planner kya hai?").delete()
    CRMTemplate.objects.filter(title="AI Trip Planner — 1 Day").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("chatbot", "0024_backfill_sent_by"),
    ]

    operations = [
        migrations.RunPython(add_faq_and_template, remove_faq_and_template),
    ]
