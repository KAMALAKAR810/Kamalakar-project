from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import datetime, timedelta

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
    user_code = models.CharField(
        max_length=12,
        unique=True,
        null=True,
        blank=True,
        help_text="Public ID e.g. KMWU0001",
    )
    mobile = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        unique=True,
        help_text="Normalized 10-digit Indian mobile; unique per account.",
    )
    # FIX: Field name is 'profile_pic' — base.html was using 'image' (wrong). Standardized here.
    profile_pic = models.ImageField(
        upload_to='profile_pics/',
        default='profile_pics/default.png',
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.username


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

    open_start_time = models.TimeField(help_text="Time when Open betting starts")
    open_end_time = models.TimeField(help_text="Official Open end time")

    close_start_time = models.TimeField(help_text="Time when Close betting starts")
    close_end_time = models.TimeField(help_text="Official Close end time")

    open_patti = models.CharField(max_length=3, blank=True, null=True, help_text="e.g. 123")
    open_single = models.CharField(max_length=1, blank=True, null=True, help_text="e.g. 6")

    close_single = models.CharField(max_length=1, blank=True, null=True, help_text="e.g. 7")
    close_patti = models.CharField(max_length=3, blank=True, null=True, help_text="e.g. 601")

    def is_betting_allowed(self, session_type):
        """
        User can bet between start_time and (end_time - 10 mins).
        Last 10 mins is locked.
        """
        now = timezone.localtime().time()

        if session_type == 'OPEN':
            start = self.open_start_time
            end = self.open_end_time
        else:
            start = self.close_start_time
            end = self.close_end_time

        dummy_date = datetime.today()
        end_dt = datetime.combine(dummy_date, end)
        lockout_limit = (end_dt - timedelta(minutes=10)).time()

        return start <= now <= lockout_limit

    @property
    def is_open_betting_open(self):
        return self.is_betting_allowed("OPEN")

    def __str__(self):
        return self.name


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

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.game_type} | {self.market.name} | {self.number}"


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
