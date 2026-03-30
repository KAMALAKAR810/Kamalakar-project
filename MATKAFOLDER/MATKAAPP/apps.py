from django.apps import AppConfig


class MatkaappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'MATKAAPP'

    def ready(self):
        # FIX: Import signals so they are registered on app startup
        import MATKAAPP.signals  # noqa
