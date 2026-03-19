from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings

# --- CHOICES DEFINITION ---

STATUS_CHOICES = (
    ('PENDING', 'Pending'),
    ('WIN', 'Win'),
    ('LOSS', 'Loss'),
)

GAME_CHOICES = (
    ('SINGLE', 'Single'),
    ('JODI', 'Jodi'),
    ('SINGLE_PATTI', 'Single Patti'),
    ('DOUBLE_PATTI', 'Double Patti'),
    ('TRIPPLE_PATTI', 'Tripple Patti'),
)

# --- MODELS ---

class MatkaNumber(models.Model):
    m_name = models.CharField(max_length=100, default="Lucky Drop", blank=True)
    m_time_1 = models.TimeField(null=True, blank=True, verbose_name="Opening Time")
    m_time_2 = models.TimeField(null=True, blank=True, verbose_name="Closing Time")
    m_number_1 = models.CharField(max_length=100, null=True, blank=True)
    m_number_2 = models.CharField(max_length=100, null=True, blank=True)
    m_number_3 = models.CharField(max_length=100, null=True, blank=True)
    m_number_4 = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f"{self.m_name} ({self.m_number_2}{self.m_number_3})"

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE) 
    mobile = models.CharField(max_length=15, blank=True, null=True)
    profile_pic = models.ImageField(upload_to='profile_pics/', default='profile_pics/default.png', blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    def __str__(self):
        return f'{self.user.username} Profile'

class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - ₹{self.balance}"

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
        return f"{self.txn_type} - {self.amount}"

class Bet(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    game_type = models.CharField(max_length=20, choices=GAME_CHOICES)
    market_name = models.CharField(max_length=100) 
    number = models.CharField(max_length=10)      
    amount = models.PositiveIntegerField() 
    # ADDED: To track actual winnings for the Ledger
    win_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00) 
    # ADDED: To track if it's Open or Close session
    session = models.CharField(max_length=10, choices=(('OPEN', 'Open'), ('CLOSE', 'Close')), default='OPEN')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.number} (Points: {self.amount})"

# --- SIGNALS ---

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
        Wallet.objects.get_or_create(user=instance)
    else:
        if hasattr(instance, 'profile'):
            instance.profile.save()
        else:
            Profile.objects.create(user=instance)
            
        if not hasattr(instance, 'wallet'):
            Wallet.objects.create(user=instance)
            