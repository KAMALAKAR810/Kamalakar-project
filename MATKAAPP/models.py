from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone  # Add this import

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
    
    # UPDATE THIS LINE: Add 'profile_pics/' to the default path
    profile_pic = models.ImageField(
        upload_to='profile_pics/', 
        default='profile_pics/default.png', 
        blank=True
    )
    
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    def __str__(self):
        return f'{self.user.username} Profile'
    
    
    def get_profile_pic_url(self):
        """Return the profile picture URL or a default if none exists"""
        if self.profile_pic and hasattr(self.profile_pic, 'url'):
            return self.profile_pic.url
        return '/static/images/default-avatar.png'
    
    class Meta:
        verbose_name = "Profile"
        verbose_name_plural = "Profiles"

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    """
    Create or update user profile automatically when user is saved
    """
    if created:
        Profile.objects.create(user=instance)
    else:
        try:
            instance.profile.save()
        except:
            # If profile doesn't exist, create it
            Profile.objects.create(user=instance)