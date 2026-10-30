from django.core.management.base import BaseCommand
from chatbot.models import ConversationLabel


class Command(BaseCommand):
    help = 'Add Hot label to Conversation Labels if it does not exist'

    def handle(self, *args, **options):
        label_name = "HOT"
        label_color = "#ef4444"  # Red color for Hot
        
        # Check if label already exists
        existing_label = ConversationLabel.objects.filter(name__iexact=label_name).first()
        
        if existing_label:
            self.stdout.write(
                self.style.WARNING(f'Label "{label_name}" already exists with ID {existing_label.id}')
            )
            return
        
        # Create the Hot label
        label = ConversationLabel.objects.create(
            name=label_name,
            color=label_color,
            order=1  # High priority
        )
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully created label "{label_name}" with ID {label.id}')
        )
