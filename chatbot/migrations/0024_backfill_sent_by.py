"""
Backfill sent_by for old sales/agent messages using the session's
current assigned_sales_person. Best-effort: if the chat was reassigned
after those messages were sent, the attribution will be to the current
agent, not the original sender.
"""
from django.db import migrations


def backfill_sent_by(apps, schema_editor):
    ChatMessage = apps.get_model("chatbot", "ChatMessage")
    db = schema_editor.connection.alias

    # Fetch old outgoing messages that have no sent_by but whose session
    # has an assigned person. Done in Python (not bulk update) so we can
    # group by session and avoid N+1 queries.
    sessions_seen = {}
    msgs_to_update = []

    qs = (
        ChatMessage.objects.using(db)
        .filter(sender_type__in=("sales", "agent"), sent_by__isnull=True)
        .select_related("session__assigned_sales_person")
        .order_by("id")
    )

    for msg in qs.iterator(chunk_size=500):
        session = msg.session
        sid = session.pk
        if sid not in sessions_seen:
            sessions_seen[sid] = session.assigned_sales_person_id
        agent_id = sessions_seen[sid]
        if agent_id:
            msg.sent_by_id = agent_id
            msgs_to_update.append(msg)

        if len(msgs_to_update) >= 500:
            ChatMessage.objects.using(db).bulk_update(msgs_to_update, ["sent_by"])
            msgs_to_update = []

    if msgs_to_update:
        ChatMessage.objects.using(db).bulk_update(msgs_to_update, ["sent_by"])


class Migration(migrations.Migration):

    dependencies = [
        ("chatbot", "0023_chatmessage_sent_by"),
    ]

    operations = [
        migrations.RunPython(backfill_sent_by, migrations.RunPython.noop),
    ]
