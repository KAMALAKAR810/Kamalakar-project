import logging
import os
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from MATKAAPP.models import Profile, Wallet

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Creates a superuser automatically if one does not exist'

    def handle(self, *args, **options):
        # Get credentials from environment variables or use defaults
        username = os.environ.get('ADMIN_USERNAME', 'admin')
        email = os.environ.get('ADMIN_EMAIL', 'admin@changelifewithnumbers.com')
        password = os.environ.get('ADMIN_PASSWORD', 'Admin@123456')

        # Check if the specific admin user exists
        user = User.objects.filter(username=username).first()
        if user:
            if user.is_superuser:
                logger.info(f"Superuser '{username}' already exists.")
                self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' already exists."))
                return
            else:
                logger.warning(f"User '{username}' exists but is NOT a superuser. Promoting to superuser.")
                user.is_superuser = True
                user.is_staff = True
                user.save()
                self.stdout.write(self.style.SUCCESS(f"User '{username}' promoted to superuser."))
                return

        # If no superuser exists at all, or if the specific one is missing
        logger.info(f"Creating superuser '{username}'...")
        
        # Create the superuser
        try:
            user = User.objects.create_superuser(
                username=username,
                email=email,
                password=password,
                first_name='Admin'
            )
            
            # Ensure profile and wallet are created
            profile, created = Profile.objects.get_or_create(
                user=user,
                defaults={
                    'is_email_verified': True,
                    'admin_pin': '123456',
                    'admin_security_question': 'What is your favorite color?',
                    'admin_security_answer': 'blue'
                }
            )
            
            wallet, created = Wallet.objects.get_or_create(user=user)
            
            self.stdout.write(self.style.SUCCESS(
                f'Superuser created successfully!\n'
                f'Username: {username}\n'
                f'Password: {password}\n'
                f'Email: {email}\n\n'
                f'Please change the password after first login!'
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error creating superuser: {e}'))