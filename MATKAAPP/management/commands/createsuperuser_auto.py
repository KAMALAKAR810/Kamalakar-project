from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from MATKAAPP.models import Profile, Wallet
import os


class Command(BaseCommand):
    help = 'Creates a superuser automatically if one does not exist'

    def handle(self, *args, **options):
        # Check if any superuser exists
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write(self.style.SUCCESS('Superuser already exists.'))
            return

        # Get credentials from environment variables or use defaults
        username = os.environ.get('ADMIN_USERNAME', 'admin')
        email = os.environ.get('ADMIN_EMAIL', 'admin@changelifewithnumbers.com')
        password = os.environ.get('ADMIN_PASSWORD', 'Admin@123456')

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