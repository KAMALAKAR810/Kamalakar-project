from django.db.models.signals import post_save
from django.contrib.auth.models import User
from django.dispatch import receiver
from .models import Profile, Wallet, RegistrationCounter


@receiver(post_save, sender=User)
def create_user_profile_and_wallet(sender, instance, created, **kwargs):
    """Auto-create Profile and Wallet when a new User registers."""
    if created:
        user_code = RegistrationCounter.next_user_code()
        Profile.objects.get_or_create(user=instance, defaults={'user_code': user_code})
        Wallet.objects.get_or_create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Save profile when user is saved."""
    if hasattr(instance, 'profile'):
        instance.profile.save()
