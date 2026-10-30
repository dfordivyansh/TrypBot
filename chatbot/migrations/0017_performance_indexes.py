from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('chatbot', '0016_lead_category_rule'),
    ]

    operations = [
        # Index for ChatSession to speed up CRM list queries
        migrations.AddIndex(
            model_name='chatsession',
            index=models.Index(
                fields=['updated_at', 'is_active'],
                name='idx_session_updated_active'
            ),
        ),
        # Index for ChatSession to speed up last_customer_message_time queries
        migrations.AddIndex(
            model_name='chatsession',
            index=models.Index(
                fields=['last_customer_message_time'],
                name='idx_session_last_msg_time'
            ),
        ),
        # Index for Lead to speed up destination and status filtering
        migrations.AddIndex(
            model_name='lead',
            index=models.Index(
                fields=['destination', 'status', 'created_at'],
                name='idx_lead_destination_status_created'
            ),
        ),
        # Index for Lead to speed up source filtering
        migrations.AddIndex(
            model_name='lead',
            index=models.Index(
                fields=['source', 'created_at'],
                name='idx_lead_source_created'
            ),
        ),
        # Index for ChatMessage to speed up session message queries
        migrations.AddIndex(
            model_name='chatmessage',
            index=models.Index(
                fields=['session_id', 'created_at'],
                name='idx_message_session_created'
            ),
        ),
        # Index for ChatMessage to speed up whatsapp_message_id lookups
        migrations.AddIndex(
            model_name='chatmessage',
            index=models.Index(
                fields=['whatsapp_message_id'],
                name='idx_message_whatsapp_id'
            ),
        ),
        # Index for CampaignRecipient to speed up status queries
        migrations.AddIndex(
            model_name='campaignrecipient',
            index=models.Index(
                fields=['campaign', 'status'],
                name='idx_campaign_recipient_status'
            ),
        ),
    ]
