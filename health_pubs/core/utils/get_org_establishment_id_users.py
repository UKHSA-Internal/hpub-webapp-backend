import pandas as pd

# 1. Peek at the *first 10 rows* without a header so you can spot where your real header is:
raw = pd.read_excel("data_users_aps.xlsx", header=None, nrows=10)
print(raw.to_string(index=False))
# ← Look in the console for the row index where you see “user_id”, “organization_id”, etc.

# 2. Programmatically detect that header row (here we search for 'user_id')
header_idx = raw.apply(
    lambda row: row.astype(str).str.lower().str.contains("user_id").any(), axis=1
).idxmax()

# 3. Re-load the sheet with the correct header row
sheet2 = pd.read_excel("data_users_aps.xlsx", header=header_idx)
# 4. Clean up its column names
sheet2.columns = (
    sheet2.columns.str.strip().str.lower().str.replace(r"\s+", "_", regex=True)
)

# 5. Ensure you’ve got exactly the three columns you need
print("Found:", sheet2.columns.tolist())
sheet2 = sheet2[["user_id", "organization_id", "establishment_id"]]

# 6. Load your first sheet (and clean its column names the same way)
sheet1 = pd.read_excel("Users_Missing_Filtered_Data_02-05-2025.xlsx")
sheet1.columns = (
    sheet1.columns.str.strip().str.lower().str.replace(r"\s+", "_", regex=True)
)

# 7. Merge and fill
merged = sheet1.merge(sheet2, on="user_id", how="left", suffixes=("", "_from_sheet2"))
merged["organization_id"] = merged["organization_id"].fillna(
    merged["organization_id_from_sheet2"]
)
merged["establishment_id"] = merged["establishment_id"].fillna(
    merged["establishment_id_from_sheet2"]
)
merged = merged.drop(
    columns=["organization_id_from_sheet2", "establishment_id_from_sheet2"]
)

# 8. Save out
merged.to_excel("updated_sheet1.xlsx", index=False)
