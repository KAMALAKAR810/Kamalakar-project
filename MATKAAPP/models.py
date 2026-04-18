from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import datetime, timedelta
import uuid

# --- CHOICES ---

GAME_CHOICES = (
    ('SINGLE', 'Single'),
    ('JODI', 'Jodi'),
    ('SINGLE_PATTI', 'Single Patti'),
    ('DOUBLE_PATTI', 'Double Patti'),
    ('TRIPLE_PATTI', 'Triple Patti'),
)

SESSION_CHOICES = (
    ('OPEN', 'Open'),
    ('CLOSE', 'Close'),
)

STATUS_CHOICES = (
    ('PENDING', 'Pending'),
    ('WIN', 'Win'),
    ('LOSS', 'Loss'),
)

# --- MODELS ---

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    session_key = models.CharField(max_length=40, null=True, blank=True)
    user_code = models.CharField(
        max_length=12,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        help_text="Public ID e.g. KMWU0001",
    )
    mobile = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        unique=True,
        help_text="Normalized 10-digit Indian mobile; unique per account.",
    )
    is_new = models.BooleanField(default=True)
    # FIX: Field name is 'profile_pic' — base.html was using 'image' (wrong). Standardized here.
    profile_pic = models.ImageField(
        upload_to='profile_pics/',
        default='profile_pics/default.png',
        blank=True
    )
    bio = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Admin 2FA Fields
    admin_pin = models.CharField(max_length=6, default='123456', blank=True, null=True)
    admin_security_question = models.CharField(
        max_length=255, 
        default='My favourite name', 
        blank=True, 
        null=True
    )
    admin_security_answer = models.CharField(
        max_length=255, 
        default='Gandu', 
        blank=True, 
        null=True
    )

    def __str__(self):
        return self.user.username


class Message(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages')
    content = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='chat_images/', blank=True, null=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    auto_delete = models.BooleanField(default=False, help_text="If True, delete 30 mins after being read")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"From {self.sender} to {self.receiver} at {self.created_at}"


class RegistrationCounter(models.Model):
    """
    Single row (pk=1) for atomic sequential KMWU#### assignment.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Registration counter"

    @classmethod
    def next_user_code(cls):
        from django.db import transaction

        with transaction.atomic():
            obj, _ = cls.objects.select_for_update().get_or_create(
                pk=1,
                defaults={"last_number": 0},
            )
            obj.last_number += 1
            obj.save(update_fields=["last_number"])
            return f"KMWU{obj.last_number:04d}"


class Wallet(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - ₹{self.balance}"


class Market(models.Model):
    """
    Controlled by Superuser.
    Contains timing and Matka result codes.
    """
    name = models.CharField(max_length=100, unique=True)
    
    # Task 16: Collection date for the market
    collection_date = models.DateTimeField(null=True, blank=True, help_text="Market specific collection date and time")

    open_start_time = models.DateTimeField(null=True, blank=True, help_text="Time when Open betting starts")
    open_end_time = models.DateTimeField(null=True, blank=True, help_text="Official Open end time")

    close_start_time = models.DateTimeField(null=True, blank=True, help_text="Time when Close betting starts")
    close_end_time = models.DateTimeField(null=True, blank=True, help_text="Official Close end time")

    # Admin Results
    open_patti = models.CharField(max_length=3, blank=True, null=True)
    open_single = models.CharField(max_length=1, blank=True, null=True)
    open_declared_at = models.DateTimeField(null=True, blank=True)

    close_patti = models.CharField(max_length=3, blank=True, null=True)
    close_single = models.CharField(max_length=1, blank=True, null=True)
    close_declared_at = models.DateTimeField(null=True, blank=True)

    def is_betting_allowed(self, session_type):
        """
        User can bet between start_time and (end_time - 10 mins).
        Last 10 mins is locked.
        Also, if result is declared, betting is CLOSED.
        """
        now = timezone.localtime()

        if session_type == 'OPEN':
            # If open result is declared, no more betting for OPEN
            if self.open_single or self.open_patti:
                return False
            start = self.open_start_time
            end = self.open_end_time
        else:
            # If close result is declared, no more betting for CLOSE
            if self.close_single or self.close_patti:
                return False
            start = self.close_start_time
            end = self.close_end_time

        if not start or not end:
            return False

        lockout_limit = end - timedelta(minutes=10)

        return start <= now <= lockout_limit

    def is_betting_allowed_open(self):
        return self.is_betting_allowed("OPEN")

    def is_betting_allowed_close(self):
        return self.is_betting_allowed("CLOSE")

    @property
    def is_open_betting_open(self):
        return self.is_betting_allowed("OPEN")

    def __str__(self):
        return self.name


class MarketHistory(models.Model):
    """
    Archives market results and timings before a reset.
    """
    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='history')
    collection_date = models.DateTimeField(null=True, blank=True)
    open_patti = models.CharField(max_length=3, blank=True, null=True)
    open_single = models.CharField(max_length=1, blank=True, null=True)
    close_patti = models.CharField(max_length=3, blank=True, null=True)
    close_single = models.CharField(max_length=1, blank=True, null=True)
    archived_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-archived_at']

    def __str__(self):
        return f"History: {self.market.name} at {self.archived_at}"


class Bet(models.Model):
    game_type = models.CharField(max_length=20, choices=GAME_CHOICES)
    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='bets')
    session = models.CharField(max_length=10, choices=SESSION_CHOICES)
    date = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    user_id_str = models.CharField(max_length=50, help_text="Unique User ID string for filtering")
    number = models.CharField(max_length=10)
    amount = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    win_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    is_credited = models.BooleanField(default=False, help_text="True if winning amount is added to wallet")
    credited_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.game_type} | {self.market.name} | {self.number}"

class UserActivity(models.Model):
    ACTIVITY_TYPES = (
        ('BET_DELETE', 'Bet Deleted'),
        ('CLEANUP', 'Data Cleanup'),
        ('OTHER', 'Other'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    activity_type = models.CharField(max_length=20, choices=ACTIVITY_TYPES)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.activity_type} - {self.created_at}"


class Transaction(models.Model):
    TXN_TYPES = (
        ('DEPOSIT', 'Deposit'),
        ('WITHDRAWAL', 'Withdrawal'),
        ('BET', 'Bet Placed'),
        ('WIN', 'Winning Credit'),
    )
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    txn_type = models.CharField(choices=TXN_TYPES, max_length=20)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.txn_type} - ₹{self.amount}"


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=100)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification for {self.user.username}: {self.title}"


class PaymentSettings(models.Model):
    upi_id = models.CharField(max_length=255, default="8217228766")
    payee_name = models.CharField(max_length=255, default="Payee Name", help_text="Should match the name registered with the bank/UPI ID")
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Active UPI: {self.upi_id} ({self.payee_name})"

class DepositRequest(models.Model):
    """
    User deposit requests via UTR/Transaction ID.
    """
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='deposits')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    utr_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - ₹{self.amount} (UTR: {self.utr_number})"

class SiteSettings(models.Model):
    is_captcha_enabled = models.BooleanField(default=False)  
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Site Settings (Captcha: {self.is_captcha_enabled})"

class WithdrawalRequest(models.Model):
    """
    Task 13: Withdrawal requests from user.
    """
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='withdrawals')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    upi_id = models.CharField(max_length=100, blank=True, null=True)
    mobile_number = models.CharField(max_length=15, blank=True, null=True)
    bank_account = models.CharField(max_length=50, blank=True, null=True)
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    bank_holder_name = models.CharField(max_length=100, blank=True, null=True, help_text="Name as per Bank")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - ₹{self.amount} ({self.status})"
