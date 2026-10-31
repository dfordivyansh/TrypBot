import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0017_performance_indexes'),
    ]

    operations = [
        migrations.CreateModel(
            name='Booking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=20, unique=True)),
                ('booking_type', models.CharField(choices=[('cab', 'Cab'), ('tour', 'Tour')], default='tour', max_length=10)),
                ('category', models.CharField(choices=[('personal_tour', 'Personal Tour'), ('cab', 'Cab'), ('tour_1day', '1 Day Tour'), ('tour_2day', '2 Day Tour'), ('route', 'Route')], default='personal_tour', max_length=30)),
                ('title', models.CharField(blank=True, default='', max_length=255)),
                ('customer_name', models.CharField(blank=True, default='', max_length=255)),
                ('phone', models.CharField(blank=True, db_index=True, default='', max_length=20)),
                ('email', models.CharField(blank=True, default='', max_length=254)),
                ('travel_date', models.CharField(blank=True, default='', max_length=100)),
                ('travellers', models.PositiveIntegerField(default=0)),
                ('amount', models.PositiveIntegerField(default=0, help_text='Advance amount (Rs.)')),
                ('estimated_total', models.PositiveIntegerField(default=0, help_text='Estimated package / cab fare (Rs.)')),
                ('payment_status', models.CharField(choices=[('pending', 'Pending'), ('paid', 'Paid'), ('failed', 'Failed'), ('amount_mismatch', 'Paid (amount mismatch)')], db_index=True, default='pending', max_length=20)),
                ('paid_at', models.DateTimeField(blank=True, null=True)),
                ('data', models.JSONField(blank=True, default=dict, help_text='The booking as the website sent it')),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('session', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bookings', to='chatbot.chatsession')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
