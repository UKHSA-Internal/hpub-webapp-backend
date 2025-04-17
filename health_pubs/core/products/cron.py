CRONJOBS = [
    (
        "0 7 * * *",
        "products.cron.CheckDraftProductsCronJob.do",
    )  # Runs at 7 AM Europe/London each day
]
