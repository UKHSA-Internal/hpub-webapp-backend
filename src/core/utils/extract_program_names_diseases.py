#!/usr/bin/env python3
import pandas as pd


def extract_program_names(
    prog_dis_path: str, programmes_path: str, diseases_path: str, output_path: str
):
    """
    Reads programme–disease links, programme definitions, and diseases list,
    then writes out the diseases sheet with a `program_names` column showing
    comma-separated programme names per disease.
    """
    # 1) Load input files
    prog_dis = pd.read_excel(prog_dis_path)  # columns: programme_id, disease_ids
    programmes = pd.read_excel(programmes_path)  # columns: programme_id, programme_name
    diseases = pd.read_excel(
        diseases_path
    )  # columns including ID, optional program_names

    # Drop any existing program_names to avoid conflicts on merge
    diseases = diseases.drop(columns=["program_names"], errors="ignore")

    # 2) Expand disease_ids into one row per programme–disease link
    links = prog_dis.assign(
        disease_ids_list=prog_dis["disease_ids"]
        .astype(str)
        .str.strip("[]")
        .str.split(",")
    ).explode("disease_ids_list")

    # 3) Clean IDs, drop invalid
    links = (
        links.assign(
            disease_id=pd.to_numeric(
                links["disease_ids_list"].str.strip(), errors="coerce"
            )
        )
        .dropna(subset=["disease_id"])
        .assign(disease_id=lambda df: df["disease_id"].astype(int))
    )

    # 4) Attach programme names
    links = links.merge(
        programmes[["programme_id", "programme_name"]],
        on="programme_id",
        how="left",
        validate="many_to_one",
    )

    # 5) Aggregate names per disease
    mapping = (
        links.groupby("disease_id")["programme_name"]
        .agg(lambda names: ",".join(sorted({n for n in names if pd.notna(n)})))
        .reset_index()
        .rename(columns={"programme_name": "program_names"})
    )

    # 6) Merge back onto diseases, validating one-to-one
    result = diseases.merge(
        mapping, left_on="ID", right_on="disease_id", how="left", validate="one_to_one"
    )

    # 7) Drop helper merge column
    if "disease_id" in result.columns:
        result = result.drop(columns=["disease_id"])

    # 8) Write output
    result.to_excel(output_path, index=False)
    print(f"✔ Done – saved: {output_path}")


if __name__ == "__main__":
    extract_program_names(
        prog_dis_path="files/Programmes-Diseases.xlsx",
        programmes_path="files/Programmes.xlsx",
        diseases_path="files/Diseases.xlsx",
        output_path="Diseases_with_program_names.xlsx",
    )
