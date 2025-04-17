CRONJOBS = [
    (
        "0 0 * * *",
        "products.cron.CheckDraftProductsCronJob.do",
    )  # Runs at midnight every day
]
