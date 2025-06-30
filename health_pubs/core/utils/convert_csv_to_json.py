import logging
import os
import re
import sys
import json
import secrets
import string
import pandas as pd
from math import ceil

# ─── CONFIG ────────────────────────────────────────────────────────────────────
XLSX_FILE = "user.xlsx"  # your input Excel
OUT_DIR = "batches"  # where batch JSONs go
TENANT = "REDACTED_AZURE_B2C_NAME"  # your B2C tenant domain
BATCH_SIZE = 20  # max sub-requests per batch
PASS_LENGTH = 12  # temp password length
# ────────────────────────────────────────────────────────────────────────────────

# ─── LOGGER SETUP ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
# ────────────────────────────────────────────────────────────────────────────────


def gen_password(length: int = PASS_LENGTH) -> str:
    """Return a random password with ≥1 upper, 1 lower, 1 digit, 1 symbol."""
    # 1 char from each required set
    uppers = secrets.choice(string.ascii_uppercase)
    lowers = secrets.choice(string.ascii_lowercase)
    digits = secrets.choice(string.digits)
    syms = secrets.choice("!@#$%^&*-_+=")

    # fill the rest
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_+="
    rest = [secrets.choice(alphabet) for _ in range(length - 4)]

    # combine and securely shuffle
    pwd_chars = [uppers, lowers, digits, syms] + rest
    # sample returns a new list in cryptographically secure random order
    shuffled = secrets.SystemRandom().sample(pwd_chars, k=len(pwd_chars))
    return "".join(shuffled)


def sanitize_nickname(raw: str, used: set) -> str:
    """Strip to alphanumeric, prefix 'u' if starts digit, ensure uniqueness."""
    nick = re.sub(r"[^A-Za-z0-9]", "", raw.lower())
    if not nick or nick[0].isdigit():
        nick = "u" + nick
    base, count = nick, 1
    while nick in used:
        count += 1
        nick = f"{base}{count}"
    used.add(nick)
    return nick


def main():
    # 0️⃣ Prep
    os.makedirs(OUT_DIR, exist_ok=True)
    if not os.path.exists(XLSX_FILE):
        logger.error(f"{XLSX_FILE} not found.")
        sys.exit(1)

    # 1️⃣ Load & dedupe
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
        logger.error(f"Missing columns: {missing}")
        sys.exit(1)

    # 3️⃣ Build Graph user objects
    graph_users = []
    used_nicks = set()

    for _, row in df.iterrows():
        first, last = str(row["first_name"]).strip(), str(row["last_name"]).strip()
        raw_name, email = str(row["username"]).strip(), str(row["email"]).strip()

        nick = sanitize_nickname(raw_name, used_nicks)
        temp_pwd = gen_password()

        graph_users.append(
            {
                "accountEnabled": True,
                "displayName": f"{first} {last}",
                "mailNickname": nick,
                "userPrincipalName": f"{nick}@{TENANT}",
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

    # 4️⃣ Chunk into batches & write JSON
    total = len(graph_users)
    num_batches = ceil(total / BATCH_SIZE)

    for idx in range(num_batches):
        start = idx * BATCH_SIZE
        end = start + BATCH_SIZE
        chunk = graph_users[start:end]

        payload = {"requests": []}
        for i, user_obj in enumerate(chunk, start=1):
            payload["requests"].append(
                {
                    "id": str(i),
                    "method": "POST",
                    "url": "/users",
                    "headers": {"Content-Type": "application/json"},
                    "body": user_obj,
                }
            )

        out_file = os.path.join(OUT_DIR, f"batch_{idx+1}.json")
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        logger.info(f"Wrote {len(chunk)} users → {out_file}")

    logger.info(f"Done: {total} users split into {num_batches} batches.")


if __name__ == "__main__":
    main()
