import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "MATKA.settings")
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

USERNAME = "Shiv_Shakti_Matka"
EMAIL = "Shiv_Shakti_Matka@gmail.com"
PASSWORD = "[$h!v$h@kt!]"


def main():
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
