#!/usr/bin/env python3
import re
import pandas as pd


def clean_col_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Strip, lowercase, and replace whitespace in all column names with underscores.
    """
    return df.rename(columns=lambda col: re.sub(r"\s+", "_", col.strip().lower()))


def extract_and_merge_users(raw_path: str, sheet1_path: str, output_path: str):
    # 1. Peek at the first 10 rows without a header
    raw = pd.read_excel(raw_path, header=None, nrows=10)
    print(raw.to_string(index=False))
    # — check the console for the row index with "user_id", etc.

    # 2. Detect that header row
    header_idx = raw.apply(
        lambda row: row.astype(str).str.lower().str.contains("user_id").any(), axis=1
    ).idxmax()

    # 3. Load sheet2 with that header, clean columns, select needed cols
    sheet2 = pd.read_excel(raw_path, header=header_idx).pipe(clean_col_names)[
        ["user_id", "organization_id", "establishment_id"]
    ]

    # 4. Load sheet1 and clean columns
    sheet1 = pd.read_excel(sheet1_path).pipe(clean_col_names)

    # 5. Merge with validation
    merged = (
        sheet1.merge(
            sheet2,
            on="user_id",
            how="left",
            suffixes=("", "_from_sheet2"),
            validate="one_to_one",
        )
        # 6. Fill in missing IDs, drop the helper cols
        .assign(
            organization_id=lambda df: df.organization_id.fillna(
                df.organization_id_from_sheet2
            ),
            establishment_id=lambda df: df.establishment_id.fillna(
                df.establishment_id_from_sheet2
            ),
        ).drop(columns=["organization_id_from_sheet2", "establishment_id_from_sheet2"])
    )

    # 7. Save out
    merged.to_excel(output_path, index=False)
    print(f"✔ Done – saved: {output_path}")


if __name__ == "__main__":
    extract_and_merge_users(
        raw_path="data_users_aps.xlsx",
        sheet1_path="Users_Missing_Filtered_Data_02-05-2025.xlsx",
        output_path="updated_sheet1.xlsx",
    )
