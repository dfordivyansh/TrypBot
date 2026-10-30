"""
Spam Detection and Prevention System
====================================

Comprehensive spam detection to prevent WhatsApp Business Account locks
and maintain high message quality scores.
"""

from django.utils import timezone
from datetime import timedelta
from .models import ChatSession, UserEngagement, OptInRecord, SpamRiskAlert
import re


class SpamDetector:
    """
    Main spam detection engine that analyzes user behavior
    and flags suspicious patterns.
    """
    
    # Risk thresholds
    LOW_ENGAGEMENT_THRESHOLD = 0.2  # Less than 20% response rate
    HIGH_FAILURE_THRESHOLD = 0.5   # More than 50% failure rate
    CRITICAL_FAILURE_THRESHOLD = 0.7 # More than 70% failure rate
    
    # Positive response patterns
    POSITIVE_PATTERNS = [
        r'\b(interested|yes|yeah|sure|okay|ok|tell me|more|details|price|cost|book|booking)\b',
        r'\b(plan|itinerary|package|deal|offer)\b',
        r'\b(when|how|where|what)\b',
    ]
    
    # Negative response patterns
    NEGATIVE_PATTERNS = [
        r'\b(stop|not interested|no thanks|no thank you|cancel|remove|unsubscribe)\b',
        r'\b(don\'t|do not|never)\b',
    ]
    
    @staticmethod
    def get_or_create_engagement(session):
        """Get or create UserEngagement record for a session."""
        engagement, created = UserEngagement.objects.get_or_create(
            session=session,
            defaults={
                'quality_score': 50,
            }
        )
        return engagement
    
    @staticmethod
    def analyze_message_sentiment(message_text):
        """Analyze message sentiment for quality scoring."""
        message_lower = message_text.lower()
        
        # Check for positive patterns
        positive_match = any(re.search(pattern, message_lower) for pattern in SpamDetector.POSITIVE_PATTERNS)
        
        # Check for negative patterns
        negative_match = any(re.search(pattern, message_lower) for pattern in SpamDetector.NEGATIVE_PATTERNS)
        
        if positive_match and not negative_match:
            return 'positive'
        elif negative_match:
            return 'negative'
        else:
            return 'neutral'
    
    @staticmethod
    def update_engagement_metrics(session, message_type, message_text='', delivery_status='sent'):
        """
        Update engagement metrics after each message.
        
        Args:
            session: ChatSession instance
            message_type: 'user' or 'bot'
            message_text: Message content for sentiment analysis
            delivery_status: 'sent', 'delivered', 'read', 'failed'
        """
        engagement = SpamDetector.get_or_create_engagement(session)
        
        # Update message counts
        engagement.message_count += 1
        if message_type == 'user':
            engagement.user_response_count += 1
            # Analyze sentiment
            sentiment = SpamDetector.analyze_message_sentiment(message_text)
            if sentiment == 'positive':
                engagement.positive_responses += 1
            elif sentiment == 'negative':
                engagement.negative_responses += 1
                # Check for opt-out
                if SpamDetector._is_opt_out_message(message_text):
                    engagement.opt_out_requested = True
            else:
                engagement.neutral_responses += 1
        else:
            engagement.bot_message_count += 1
            # Track delivery status
            if delivery_status == 'failed':
                engagement.failed_deliveries += 1
            else:
                engagement.successful_deliveries += 1
        
        # Recalculate quality score
        engagement.quality_score = SpamDetector.calculate_quality_score(engagement)
        
        engagement.save()
        
        # Check for spam risks
        SpamDetector.check_spam_risks(engagement)
        
        return engagement
    
    @staticmethod
    def _is_opt_out_message(message_text):
        """Check if message indicates opt-out request."""
        opt_out_patterns = [
            r'\b(stop|not interested|remove|unsubscribe|cancel|delete)\b',
        ]
        return any(re.search(pattern, message_text.lower()) for pattern in opt_out_patterns)
    
    @staticmethod
    def calculate_quality_score(engagement):
        """
        Calculate quality score based on engagement metrics.
        
        Returns: Score between 0-100
        """
        score = 50  # Base score
        
        total_messages = engagement.message_count
        if total_messages == 0:
            return score
        
        # Response rate factor (higher is better)
        if engagement.bot_message_count > 0:
            response_rate = engagement.user_response_count / engagement.bot_message_count
            score += (response_rate - 0.5) * 30  # +/- 15 points
        
        # Positive response factor
        if engagement.user_response_count > 0:
            positive_ratio = engagement.positive_responses / engagement.user_response_count
            score += (positive_ratio - 0.3) * 20  # +/- 10 points
        
        # Delivery success factor
        total_deliveries = engagement.successful_deliveries + engagement.failed_deliveries
        if total_deliveries > 0:
            success_rate = engagement.successful_deliveries / total_deliveries
            score += (success_rate - 0.8) * 40  # +/- 20 points
        
        # Opt-out penalty
        if engagement.opt_out_requested:
            score -= 30
        
        # Spam flag penalty
        if engagement.flagged_as_spam:
            score -= 50
        
        # Clamp score between 0-100
        return max(0, min(100, int(score)))
    
    @staticmethod
    def check_spam_risks(engagement):
        """
        Check for spam risk patterns and create alerts if necessary.
        
        Returns: Boolean indicating if messaging should be stopped
        """
        session = engagement.session
        should_stop_messaging = False
        
        # Check 1: Low engagement
        if engagement.bot_message_count >= 3:
            response_rate = engagement.user_response_count / engagement.bot_message_count
            if response_rate < SpamDetector.LOW_ENGAGEMENT_THRESHOLD:
                SpamDetector._create_alert(
                    session,
                    'medium',
                    'low_engagement',
                    f'Low response rate: {response_rate:.1%} ({engagement.user_response_count}/{engagement.bot_message_count})'
                )
                if response_rate < 0.1:  # Very low engagement
                    should_stop_messaging = True
        
        # Check 2: High failure rate
        total_deliveries = engagement.successful_deliveries + engagement.failed_deliveries
        if total_deliveries >= 5:
            failure_rate = engagement.failed_deliveries / total_deliveries
            if failure_rate > SpamDetector.HIGH_FAILURE_THRESHOLD:
                risk_level = 'critical' if failure_rate > SpamDetector.CRITICAL_FAILURE_THRESHOLD else 'high'
                SpamDetector._create_alert(
                    session,
                    risk_level,
                    'high_failure_rate',
                    f'High failure rate: {failure_rate:.1%} ({engagement.failed_deliveries}/{total_deliveries})'
                )
                if failure_rate > SpamDetector.CRITICAL_FAILURE_THRESHOLD:
                    should_stop_messaging = True
        
        # Check 3: Opt-out requested
        if engagement.opt_out_requested:
            SpamDetector._create_alert(
                session,
                'high',
                'opt_out',
                'User requested opt-out from messaging'
            )
            should_stop_messaging = True
        
        # Check 4: Spam flags
        if engagement.flagged_as_spam:
            SpamDetector._create_alert(
                session,
                'critical',
                'spam_pattern',
                f'User flagged as spam (count: {engagement.spam_flag_count})'
            )
            should_stop_messaging = True
        
        return should_stop_messaging
    
    @staticmethod
    def _create_alert(session, risk_level, risk_type, description):
        """Create a spam risk alert."""
        # Check if similar alert already exists in last 24 hours
        recent_alert = SpamRiskAlert.objects.filter(
            session=session,
            risk_type=risk_type,
            created_at__gte=timezone.now() - timedelta(hours=24)
        ).first()
        
        if recent_alert:
            # Update existing alert
            recent_alert.description = description
            recent_alert.risk_level = risk_level
            recent_alert.save()
        else:
            # Create new alert
            SpamRiskAlert.objects.create(
                session=session,
                risk_level=risk_level,
                risk_type=risk_type,
                description=description,
                action_taken='flagged'
            )
    
    @staticmethod
    def should_allow_messaging(session):
        """
        Check if messaging should be allowed for this session.
        
        Returns: (allowed: bool, reason: str)
        """
        engagement = SpamDetector.get_or_create_engagement(session)
        
        # Check opt-out
        if engagement.opt_out_requested:
            return False, 'User opted out of messaging'
        
        # Check spam flags
        if engagement.flagged_as_spam:
            return False, 'User flagged as spam'
        
        # Check critical alerts
        critical_alerts = SpamRiskAlert.objects.filter(
            session=session,
            risk_level='critical',
            resolved=False
        ).exists()
        
        if critical_alerts:
            return False, 'Critical spam risk alert'
        
        # Check opt-in record
        if not SpamDetector.has_valid_opt_in(session.phone_number):
            return False, 'No valid opt-in record'
        
        return True, 'Messaging allowed'
    
    @staticmethod
    def has_valid_opt_in(phone_number):
        """Check if phone number has valid opt-in record."""
        if not phone_number:
            return False
        
        # Normalize phone number
        phone_number = phone_number.replace('+', '').replace(' ', '')
        
        # Check for active opt-in
        opt_in = OptInRecord.objects.filter(
            phone_number__endswith=phone_number[-10:],  # Match last 10 digits
            is_active=True,
            opt_out_timestamp__isnull=True
        ).first()
        
        if opt_in:
            # Check if double opt-in is required and confirmed
            # For now, we'll accept single opt-in but prefer double
            return True
        
        return False
    
    @staticmethod
    def record_opt_in(phone_number, method, session=None, consent_text=''):
        """Record a new opt-in."""
        phone_number = phone_number.replace('+', '').replace(' ', '')
        
        opt_in = OptInRecord.objects.create(
            phone_number=phone_number,
            opt_in_method=method,
            session=session,
            consent_text=consent_text
        )
        
        return opt_in
    
    @staticmethod
    def record_opt_out(phone_number, reason=''):
        """Record opt-out."""
        phone_number = phone_number.replace('+', '').replace(' ', '')
        
        opt_ins = OptInRecord.objects.filter(
            phone_number__endswith=phone_number[-10:],
            is_active=True
        )
        
        for opt_in in opt_ins:
            opt_in.is_active = False
            opt_in.opt_out_timestamp = timezone.now()
            opt_in.opt_out_reason = reason
            opt_in.save()
    
    @staticmethod
    def flag_as_spam(session, reason='User reported as spam'):
        """Flag a session as spam."""
        engagement = SpamDetector.get_or_create_engagement(session)
        engagement.flagged_as_spam = True
        engagement.spam_flag_count += 1
        engagement.quality_score = max(0, engagement.quality_score - 50)
        engagement.save()
        
        # Create alert
        SpamDetector._create_alert(
            session,
            'critical',
            'spam_pattern',
            reason
        )


class RateLimiter:
    """
    Rate limiting to prevent volume spikes and suspicious patterns.
    """
    
    # Rate limits
    MAX_MESSAGES_PER_HOUR = 10
    MAX_MESSAGES_PER_DAY = 50
    MAX_NEW_USERS_PER_HOUR = 5
    
    @staticmethod
    def check_rate_limit(session):
        """
        Check if session is within rate limits.
        
        Returns: (allowed: bool, reason: str)
        """
        now = timezone.now()
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)
        
        # Check hourly limit
        hourly_count = session.chatmessage_set.filter(
            sender_type='bot',
            created_at__gte=hour_ago
        ).count()
        
        if hourly_count >= RateLimiter.MAX_MESSAGES_PER_HOUR:
            return False, f'Hourly rate limit exceeded ({hourly_count}/{RateLimiter.MAX_MESSAGES_PER_HOUR})'
        
        # Check daily limit
        daily_count = session.chatmessage_set.filter(
            sender_type='bot',
            created_at__gte=day_ago
        ).count()
        
        if daily_count >= RateLimiter.MAX_MESSAGES_PER_DAY:
            return False, f'Daily rate limit exceeded ({daily_count}/{RateLimiter.MAX_MESSAGES_PER_DAY})'
        
        return True, 'Within rate limits'
    
    @staticmethod
    def check_global_volume():
        """
        Check global message volume for suspicious spikes.
        
        Returns: (allowed: bool, reason: str)
        """
        now = timezone.now()
        hour_ago = now - timedelta(hours=1)
        
        # Count messages in last hour
        hourly_volume = ChatSession.objects.filter(
            updated_at__gte=hour_ago
        ).count()
        
        # Check for unusual spike (simple heuristic)
        if hourly_volume > RateLimiter.MAX_NEW_USERS_PER_HOUR * 10:  # 10x normal
            return False, f'Unusual volume spike detected ({hourly_volume} sessions/hour)'
        
        return True, 'Global volume normal'
