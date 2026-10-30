# Combined migration for the SERVER's migration chain (0001-0013).
# Adds: contact tags, segments, marketing opt-out, campaigns, template language.
# Removes: Hotel, HotelRate, TreeboHotel.
# NOTE: AlterUniqueTogether must come BEFORE RemoveField on SQLite.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0013_salesprofile_is_active_for_meta_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='chatsession',
            name='marketing_opt_out',
            field=models.BooleanField(db_index=True, default=False, help_text='Contact asked not to receive broadcast/marketing messages'),
        ),
        migrations.AddField(
            model_name='chatsession',
            name='marketing_opt_out_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='crmtemplate',
            name='language',
            field=models.CharField(default='en', help_text='Language code the template was approved in (e.g. en, en_US, hi)', max_length=10),
        ),
        migrations.CreateModel(
            name='ContactTag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=60, unique=True)),
                ('color', models.CharField(default='#25D366', max_length=9)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_contact_tags', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Contact Tag',
                'verbose_name_plural': 'Contact Tags',
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='chatsession',
            name='tags',
            field=models.ManyToManyField(blank=True, related_name='sessions', to='chatbot.contacttag'),
        ),
        migrations.CreateModel(
            name='Segment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120, unique=True)),
                ('description', models.CharField(blank=True, default='', max_length=255)),
                ('filters', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_segments', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Campaign',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('template_title', models.CharField(blank=True, default='', max_length=255)),
                ('template_name', models.CharField(blank=True, default='', max_length=255)),
                ('template_language', models.CharField(default='en', max_length=10)),
                ('template_text', models.TextField(blank=True, default='')),
                ('variable_mapping', models.JSONField(blank=True, default=dict)),
                ('header_media_type', models.CharField(blank=True, choices=[('', 'None'), ('image', 'Image'), ('video', 'Video'), ('document', 'Document')], default='', max_length=20)),
                ('header_media_url', models.URLField(blank=True, default='', max_length=1000)),
                ('header_media_filename', models.CharField(blank=True, default='', max_length=255)),
                ('audience_type', models.CharField(blank=True, default='filters', max_length=20)),
                ('audience_filters', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('scheduled', 'Scheduled'), ('running', 'Running'), ('paused', 'Paused'), ('completed', 'Completed'), ('cancelled', 'Cancelled'), ('failed', 'Failed')], db_index=True, default='draft', max_length=20)),
                ('scheduled_at', models.DateTimeField(blank=True, null=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True, default='')),
                ('consent_confirmed', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='campaigns', to=settings.AUTH_USER_MODEL)),
                ('template', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='campaigns', to='chatbot.crmtemplate')),
                ('segment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='campaigns', to='chatbot.segment')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='CampaignRecipient',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone', models.CharField(max_length=20)),
                ('name', models.CharField(blank=True, default='', max_length=255)),
                ('variables', models.JSONField(blank=True, default=dict)),
                ('extra', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('sending', 'Sending'), ('sent', 'Sent'), ('delivered', 'Delivered'), ('read', 'Read'), ('failed', 'Failed'), ('skipped', 'Skipped')], db_index=True, default='pending', max_length=20)),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('claimed_at', models.DateTimeField(blank=True, null=True)),
                ('whatsapp_message_id', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('error_code', models.CharField(blank=True, default='', max_length=20)),
                ('error_message', models.TextField(blank=True, default='')),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('delivered_at', models.DateTimeField(blank=True, null=True)),
                ('read_at', models.DateTimeField(blank=True, null=True)),
                ('replied_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('campaign', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='recipients', to='chatbot.campaign')),
                ('session', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='campaign_recipients', to='chatbot.chatsession')),
            ],
            options={
                'ordering': ['id'],
                'indexes': [models.Index(fields=['campaign', 'status'], name='chatbot_cam_campaig_6255be_idx')],
                'unique_together': {('campaign', 'phone')},
            },
        ),

        migrations.AlterUniqueTogether(
            name='hotelrate',
            unique_together=None,
        ),
        migrations.RemoveField(
            model_name='hotelrate',
            name='hotel',
        ),
        migrations.DeleteModel(
            name='TreeboHotel',
        ),
        migrations.DeleteModel(
            name='Hotel',
        ),
        migrations.DeleteModel(
            name='HotelRate',
        ),
    ]
