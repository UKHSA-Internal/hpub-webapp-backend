import json
import logging
import pandas as pd
import re
import secrets
import string
from math import ceil
from pathlib import Path
import sys

# ─── CONFIG ────────────────────────────────────────────────────────────────────
CONFIG = {
    "xlsx_file": Path("user.xlsx"),
    "out_dir": Path("batches"),
    "tenant": "${{ vars.AZURE_B2C_NAME }}",
    "batch_size": 20,
    "pass_length": 12,
}
# ────────────────────────────────────────────────────────────────────────────────

# ─── LOGGER SETUP ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
# ────────────────────────────────────────────────────────────────────────────────


def gen_password(length: int = CONFIG["pass_length"]) -> str:
    """Generate a random password with ≥1 upper, 1 lower, 1 digit, and 1 symbol."""
    choices = {
        "upper": secrets.choice(string.ascii_uppercase),
        "lower": secrets.choice(string.ascii_lowercase),
        "digit": secrets.choice(string.digits),
        "symbol": secrets.choice("!@#$%^&*-_+="),
    }
    # fill the rest
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_+="
    rest = [secrets.choice(alphabet) for _ in range(length - len(choices))]
    pwd = list(choices.values()) + rest

    # Fisher–Yates shuffle
    for i in reversed(range(1, len(pwd))):
        j = secrets.randbelow(i + 1)
        pwd[i], pwd[j] = pwd[j], pwd[i]
    return "".join(pwd)


def sanitize_nickname(raw: str, used: set[str]) -> str:
    """
    Strip non-alphanumerics, prefix with 'u' if needed, and ensure uniqueness.
    """
    nick = re.sub(r"[^A-Za-z0-9]", "", raw.lower())
    if not nick or nick[0].isdigit():
        nick = "u" + nick

    base = nick
    suffix = 1
    while nick in used:
        suffix += 1
        nick = f"{base}{suffix}"
    used.add(nick)
    return nick


def load_users(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, engine="openpyxl")
    deduped = df.drop_duplicates(subset=["username", "email"])
    return deduped


def validate_columns(df: pd.DataFrame, required: set[str]) -> None:
    missing = required - set(df.columns)
    if missing:
        logger.error("Missing required columns: %s", missing)
        sys.exit(1)


def build_graph_users(df: pd.DataFrame, tenant: str) -> list[dict]:
    users, used_nicks = [], set()
    for _, row in df.iterrows():
        first = str(row["first_name"]).strip()
        last = str(row["last_name"]).strip()
        username = str(row["username"]).strip()
        email = str(row["email"]).strip()

        nick = sanitize_nickname(username, used_nicks)
        pwd = gen_password()

        users.append(
            {
                "accountEnabled": True,
                "displayName": f"{first} {last}",
                "mailNickname": nick,
                "userPrincipalName": f"{nick}@{tenant}",
                "givenName": first,
                "surname": last,
                "passwordProfile": {
                    "forceChangePasswordNextSignIn": False,
                    "password": pwd,
                },
                "identities": [
                    {
                        "signInType": "emailAddress",
                        "issuer": tenant,
                        "issuerAssignedId": email,
                    }
                ],
            }
        )
    return users


def write_batches(users: list[dict], out_dir: Path, batch_size: int) -> None:
    out_dir.mkdir(exist_ok=True)
    total = len(users)
    batches = ceil(total / batch_size)

    for idx in range(batches):
        chunk = users[idx * batch_size : (idx + 1) * batch_size]
        payload = {
            "requests": [
                {
                    "id": str(i + 1),
                    "method": "POST",
                    "url": "/users",
                    "headers": {"Content-Type": "application/json"},
                    "body": user_obj,
                }
                for i, user_obj in enumerate(chunk)
            ]
        }
        file_path = out_dir / f"batch_{idx+1}.json"
        file_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Wrote %d users → %s", len(chunk), file_path)


def main():
    cfg = CONFIG

    if not cfg["xlsx_file"].exists():
        logger.error("Excel file %s not found.", cfg["xlsx_file"])
        sys.exit(1)

    df = load_users(cfg["xlsx_file"])
    required_cols = {
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
    validate_columns(df, required_cols)

    graph_users = build_graph_users(df, cfg["tenant"])
    write_batches(graph_users, cfg["out_dir"], cfg["batch_size"])

    logger.info(
        "Completed: %d users split into %d batches.",
        len(graph_users),
        ceil(len(graph_users) / cfg["batch_size"]),
    )


if __name__ == "__main__":
    main()
