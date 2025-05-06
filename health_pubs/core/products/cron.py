from django.core.management import call_command


class CheckDraftProductsCronJob:
    @staticmethod
    def do():
        # your existing draft‑check command
        call_command("check_upcoming_drafts")


class PublishScheduledProductsCronJob:
    @staticmethod
    def do():
        # calls the management command that moves draft→live for today's publish_date
        call_command("publish_scheduled_products")
