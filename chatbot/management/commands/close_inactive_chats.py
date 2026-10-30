"""
Management command to close inactive chats after 24 hours and send notifications.
Run this command periodically (e.g., via cron or Celery beat).
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from chatbot.models import ChatSession, ConversationStatus, CRMTemplate
from chatbot.crm_lead_signals import push_chat_closed_notification


class Command(BaseCommand):
    help = 'Close inactive chats after 24 hours and send notifications with template button'

    def handle(self, *args, **options):
        # Find sessions that haven't been updated in 24 hours and are not already closed
        cutoff_time = timezone.now() - timedelta(hours=24)
        
        inactive_sessions = ChatSession.objects.filter(
            updated_at__lt=cutoff_time,
            is_active=True
        ).select_related('assigned_sales_person')
        
        closed_count = 0
        for session in inactive_sessions:
            # Get or create conversation status
            conv_status, _ = ConversationStatus.objects.get_or_create(
                session=session,
                defaults={'assigned_to': session.assigned_sales_person}
            )
            
            # Check if already closed
            if conv_status.closed:
                continue
            
            # Mark as closed
            conv_status.closed = True
            conv_status.save(update_fields=['closed'])
            
            # Mark session as inactive
            session.is_active = False
            session.save(update_fields=['is_active'])
            
            # Send notification to assigned sales person
            if session.assigned_sales_person:
                push_chat_closed_notification(session)
            
            closed_count += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f'Closed chat for {session.phone_number or session.session_id} '
                    f'(inactive for 24h)'
                )
            )
        
        if closed_count == 0:
            self.stdout.write(self.style.WARNING('No inactive chats found to close.'))
        else:
            self.stdout.write(
                self.style.SUCCESS(f'Successfully closed {closed_count} inactive chats.')
            )
