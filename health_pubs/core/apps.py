from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        # from core.orders import signals
        # from core.products import signals

        # Import signal handlers here to ensure they're registered
        pass
