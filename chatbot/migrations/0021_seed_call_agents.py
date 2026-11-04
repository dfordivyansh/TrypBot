# The first call agents (user, 2026-11-03), in this turn order, and a
# 60-minute rotation. Each is linked to the CRM user with the same first name
# or username, if there is one, so they see their own calls.
from django.db import migrations

AGENTS = [
    ("Nikhil", "8595899384"),
    ("Kajal", "9310597828"),
    ("Gaurav", "8076540958"),
    ("Avanish", "7982990654"),
    ("Asmin", "8796984407"),
]


def seed(apps, schema_editor):
    CallAgent = apps.get_model("chatbot", "CallAgent")
    CallSettings = apps.get_model("chatbot", "CallSettings")
    User = apps.get_model("auth", "User")
    CallSettings.objects.get_or_create(pk=1, defaults={"rotation_minutes": 60})
    if CallAgent.objects.exists():
        return
    for order, (name, phone) in enumerate(AGENTS, start=1):
        user = (User.objects.filter(first_name__iexact=name).first()
                or User.objects.filter(username__iexact=name).first()
                or User.objects.filter(username__istartswith=name).first())
        CallAgent.objects.create(name=name, phone=phone, order=order, user=user)


class Migration(migrations.Migration):

    dependencies = [
        ("chatbot", "0020_call_routing"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
