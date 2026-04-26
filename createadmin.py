import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "MATKA.settings")
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

USERNAME = os.getenv("DJANGO_SUPERUSER_USERNAME", "").strip()
EMAIL = os.getenv("DJANGO_SUPERUSER_EMAIL", "").strip()
PASSWORD = os.getenv("DJANGO_SUPERUSER_PASSWORD", "").strip()


def main():
    if not USERNAME or not EMAIL or not PASSWORD:
        print(
            "Missing superuser credentials. Set DJANGO_SUPERUSER_USERNAME, "
            "DJANGO_SUPERUSER_EMAIL, and DJANGO_SUPERUSER_PASSWORD environment variables."
        )
        return

    if User.objects.filter(username=USERNAME).exists():
        print("Superuser already exists.")
        return

    User.objects.create_superuser(
        username=USERNAME,
        email=EMAIL,
        password=PASSWORD,
    )
    print("Superuser created successfully.")


if __name__ == "__main__":
    main()
