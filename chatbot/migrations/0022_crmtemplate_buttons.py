from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0021_seed_call_agents'),
    ]

    operations = [
        migrations.AddField(
            model_name='crmtemplate',
            name='buttons',
            field=models.JSONField(blank=True, default=list, help_text='The template\'s buttons, shown under it in the CRM chat. Filled by "manage.py sync_template_buttons", e.g. [{"type": "PHONE_NUMBER", "text": "Call Now", "phone_number": "+91..."}]'),
        ),
    ]
