# =========================================================
# STEP 2 — FORMS
# FILE: chatbot/forms.py
# ACTION: CREATE (or EDIT if already exists — just add these)
# =========================================================

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from .models import InternalNote, Reminder, ConversationStatus, ConversationLabel
from django.contrib.auth.models import User


# =========================================================
# LOGIN FORM
# =========================================================

class CRMLoginForm(AuthenticationForm):

    username = forms.CharField(
        widget=forms.TextInput(attrs={
            "class": "crm-input",
            "placeholder": "Username",
            "autofocus": True,
        })
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "crm-input",
            "placeholder": "Password",
        })
    )


# =========================================================
# ADD NOTE FORM
# =========================================================

class NoteForm(forms.ModelForm):

    class Meta:
        model = InternalNote
        fields = ["note"]
        widgets = {
            "note": forms.Textarea(attrs={
                "class": "crm-textarea",
                "placeholder": "Add an internal note...",
                "rows": 4,
            })
        }


# =========================================================
# REMINDER FORM
# =========================================================

class ReminderForm(forms.ModelForm):

    class Meta:
        model = Reminder
        fields = ["note", "reminder_at"]
        widgets = {
            "note": forms.Textarea(attrs={
                "class": "crm-textarea",
                "placeholder": "Reminder note...",
                "rows": 3,
            }),
            "reminder_at": forms.DateTimeInput(
                attrs={
                    "class": "crm-input",
                    "type": "datetime-local",
                },
                format="%Y-%m-%dT%H:%M"
            ),
        }


# =========================================================
# ASSIGN CHAT FORM
# =========================================================

class AssignChatForm(forms.Form):

    user_id = forms.IntegerField(
        widget=forms.HiddenInput()
    )

    session_id = forms.IntegerField(
        widget=forms.HiddenInput()
    )


# =========================================================
# LABEL FORM
# =========================================================

class LabelForm(forms.Form):

    label_id = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput()
    )

    session_id = forms.IntegerField(
        widget=forms.HiddenInput()
    )


# =========================================================
# SEND MESSAGE FORM
# =========================================================

class SendMessageForm(forms.Form):

    message = forms.CharField(
        widget=forms.TextInput(attrs={
            "class": "crm-msg-input",
            "placeholder": "Type a message...",
            "autocomplete": "off",
        })
    )