import pandas as pd
from pathlib import Path

# ————— CONFIG —————
BASE_DIR = Path("files")
ORG_PATH = BASE_DIR / "Organizations.xlsx"
EST_PATH = BASE_DIR / "Establishments.xlsx"
UO_PATH = BASE_DIR / "user_original_data.xlsx"
USERS_PATH = BASE_DIR / "Users.xlsx"

OUT_UO = BASE_DIR / "user_original_data_with_ids.xlsx"
OUT_USERS = BASE_DIR / "Users_updated.xlsx"


def load_excel(path: Path) -> pd.DataFrame:
    """Load the first sheet of an Excel file into a DataFrame."""
    if not path.exists():
        raise FileNotFoundError(f"{path!r} not found")
    return pd.read_excel(path)


def find_combined_col(df: pd.DataFrame) -> str:
    """
    Find the single column whose name contains both
    'organization' and 'establishment' (case-insensitive).
    """
    hits = [
        c
        for c in df.columns
        if "organization" in c.lower() and "establishment" in c.lower()
    ]
    if len(hits) != 1:
        raise KeyError(f"Expected exactly one combined column, found {hits}")
    return hits[0]


def split_codes(val: str) -> tuple[str | None, str | None]:
    """
    Turn 'NH|GPS' → ('NH','GPS'), stripping whitespace.
    Non-strings or missing '|' → (None,None).
    """
    if not isinstance(val, str) or "|" not in val:
        return None, None
    a, b = val.split("|", 1)
    return a.strip() or None, b.strip() or None


def append_ids_to_user_original(
    uo: pd.DataFrame, org: pd.DataFrame, est: pd.DataFrame
) -> pd.DataFrame:
    """Split your combined code, map via external_key → id, and warn on any failures."""
    df = uo.copy()
    combined_col = find_combined_col(df)

    # 1) split
    splits = df[combined_col].apply(split_codes)
    df[["org_code", "est_code"]] = pd.DataFrame(splits.tolist(), index=df.index)

    # 2) lookup maps (external_key → id)
    org_map = org.set_index("external_key")["id"].to_dict()
    est_map = est.set_index("external_key")["id"].to_dict()

    # 3) map into nullable Int columns
    df["organization_id"] = df["org_code"].map(org_map).astype("Int64")
    df["establishment_id"] = df["est_code"].map(est_map).astype("Int64")

    # 4) warn if any really failed
    bad = df.loc[
        df["organization_id"].isna() | df["establishment_id"].isna(),
        ["org_code", "organization_id", "est_code", "establishment_id"],
    ].drop_duplicates()
    if not bad.empty:
        print("\n⚠️  Warning — unmapped codes in user_original_data:")
        print(bad.to_string(index=False))

    return df


def update_users_table(users: pd.DataFrame, uo: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize both side emails → lower/strip, then left-merge
    in the new IDs, filling only where users had NaN.
    """
    # 1) ensure both DataFrames have a clean 'email'
    for df in (users, uo):
        if "email" not in df.columns:
            raise KeyError(
                f"'email' column missing in DataFrame with columns {df.columns.tolist()}"
            )
        df["email"] = df["email"].astype(str).str.lower().str.strip()

    # 2) merge
    merged = users.merge(
        uo[["email", "organization_id", "establishment_id"]],
        on="email",
        how="left",
        suffixes=("_old", "_new"),
    )

    # 3) fill only where users lacked an ID
    for col in ("organization_id", "establishment_id"):
        old, new = f"{col}_old", f"{col}_new"
        merged[col] = merged[old].combine_first(merged[new])
        merged.drop([old, new], axis=1, inplace=True)

    # 4) debug-check: did we match any rows?
    matched = (
        merged["organization_id"].notna().sum()
        + merged["establishment_id"].notna().sum()
    )
    print(f"🔍  Matched IDs in Users table: {matched} non-null values total")

    return merged


def main():
    # — load —
    org_df = load_excel(ORG_PATH)
    est_df = load_excel(EST_PATH)
    uo_df = load_excel(UO_PATH)
    users_df = load_excel(USERS_PATH)

    # — enrich original_data —
    uo_enriched = append_ids_to_user_original(uo_df, org_df, est_df)
    uo_enriched.to_excel(OUT_UO, index=False)
    print(f"✅  Wrote {OUT_UO}")

    # — update users.xlsx —
    users_updated = update_users_table(users_df, uo_enriched)
    users_updated.to_excel(OUT_USERS, index=False)
    print(f"✅  Wrote {OUT_USERS}")


if __name__ == "__main__":
    main()
