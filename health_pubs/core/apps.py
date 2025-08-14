from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        pass

        # Import signal handlers here to ensure they're registered
