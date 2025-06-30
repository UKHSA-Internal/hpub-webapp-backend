from venv import logger
import pandas as pd
import json
import os
import re
import sys
import secrets
import string
from math import ceil
import logging

logger = logging.getLogger(__name__)

# ─── CONFIG ────────────────────────────────────────────────────────────────────
XLSX_FILE = "user.xlsx"  # your input Excel
OUT_DIR = "batches"  # where batch JSONs go
TENANT = "REDACTED_AZURE_B2C_NAME"  # your B2C tenant domain
BATCH_SIZE = 20  # max sub-requests per batch
PASS_LENGTH = 12  # temp password length
# ────────────────────────────────────────────────────────────────────────────────


# Helpers


def gen_password(length=12):
    """Return a random password with ≥1 upper, 1 lower, 1 digit, 1 symbol."""
    # Generate one character from each category
    uppers = secrets.choice(string.ascii_uppercase)
    lowers = secrets.choice(string.ascii_lowercase)
    digits = secrets.choice(string.digits)
    syms = secrets.choice("!@#$%^&*-_+=")

    # Fill the rest of the password length with random choices
    rest = "".join(
        secrets.choice(string.ascii_letters + string.digits + "!@#$%^&*-_+=")
        for _ in range(length - 4)
    )

    # Combine the parts and shuffle securely
    pwd = [uppers, lowers, digits, syms] + list(rest)

    # Use secrets.SystemRandom().shuffle() securely by using random.sample for shuffling
    shuffled_pwd = "".join(
        secrets.SystemRandom().sample(pwd, len(pwd))
    )  # Secure shuffle

    return shuffled_pwd


# Example usage
print(gen_password())


def sanitize_nickname(raw, used):
    """Strip to alphanumeric, prefix 'u' if starts digit, ensure uniqueness."""
    nick = re.sub(r"[^A-Za-z0-9]", "", raw.lower())
    if not nick or nick[0].isdigit():
        nick = "u" + nick
    base = nick
    cnt = 1
    while nick in used:
        cnt += 1
        nick = f"{base}{cnt}"
    used.add(nick)
    return nick


# 0️⃣ Prep
os.makedirs(OUT_DIR, exist_ok=True)
if not os.path.exists(XLSX_FILE):
    logger.info(f"Error: {XLSX_FILE} not found.", file=sys.stderr)
    sys.exit(1)

# 1️⃣ Load & dedupe on username+email to avoid UPN conflicts
df = pd.read_excel(XLSX_FILE, engine="openpyxl")
df = df.drop_duplicates(subset=["username", "email"])

# 2️⃣ Check required columns
required = {
    "user_id",
    "first_name",
    "last_name",
    "username",
    "password",
    "email",
    "user_region",
    "role_id",
    "created_at",
    "email_verified",
    "is_authorized",
    "user_status",
    "reason",
    "last_login",
    "last_order_date",
    "organization_id",
    "establishment_id",
}
missing = required - set(df.columns)
if missing:
    logger.info(f"Error: Missing columns: {missing}", file=sys.stderr)
    sys.exit(1)

# 3️⃣ Build Graph user objects using sanitized UPNs and mailNicknames
graph_users = []
used_nicks = set()
for _, row in df.iterrows():
    first = str(row["first_name"]).strip()
    last = str(row["last_name"]).strip()
    raw_name = str(row["username"]).strip()
    email = str(row["email"]).strip()

    # Create a valid mailNickname and use it for UPN local part
    nick = sanitize_nickname(raw_name, used_nicks)
    upn_local = nick  # already lowercase, alphanumeric
    temp_pwd = gen_password()

    graph_users.append(
        {
            "accountEnabled": True,
            "displayName": f"{first} {last}",
            "mailNickname": nick,
            "userPrincipalName": f"{upn_local}@{TENANT}",
            "givenName": first,
            "surname": last,
            "passwordProfile": {
                "forceChangePasswordNextSignIn": False,
                "password": temp_pwd,
            },
            "identities": [
                {
                    "signInType": "emailAddress",
                    "issuer": TENANT,
                    "issuerAssignedId": email,
                }
            ],
        }
    )

# 4️⃣ Chunk into batches of 20, add per-request headers, write JSON files
total = len(graph_users)
num_batches = ceil(total / BATCH_SIZE)

for idx in range(num_batches):
    start = idx * BATCH_SIZE
    end = start + BATCH_SIZE
    chunk = graph_users[start:end]

    payload = {"requests": []}
    for i, obj in enumerate(chunk, start=1):
        payload["requests"].append(
            {
                "id": str(i),
                "method": "POST",
                "url": "/users",
                "headers": {"Content-Type": "application/json"},
                "body": obj,
            }
        )

    out_file = os.path.join(OUT_DIR, f"batch_{idx+1}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    logger.info(f"Wrote {len(chunk)} users → {out_file}")

logger.info(f"\n✅ Done: {total} users split into {num_batches} batches.")
