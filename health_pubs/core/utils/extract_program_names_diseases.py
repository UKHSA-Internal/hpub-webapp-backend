#!/usr/bin/env python3
import pandas as pd


def extract_program_names(
    prog_dis_path: str, programmes_path: str, diseases_path: str, output_path: str
):
    # 1) Load your files
    prog_dis = pd.read_excel(
        prog_dis_path
    )  # programme_id, disease_ids (e.g. "1,2,3" or "[1,2]")
    programmes = pd.read_excel(programmes_path)  # programme_id, programme_name, …
    diseases = pd.read_excel(diseases_path)  # ID, …, program_names (empty/NaN)

    # 2) Split & explode the disease_ids into one row per programme_id–disease_id
    prog_dis = prog_dis.copy()
    prog_dis["disease_ids_list"] = (
        prog_dis["disease_ids"]
        .astype(str)
        .str.strip("[]")  # remove any stray brackets
        .str.split(",")  # split into lists
    )
    exploded = prog_dis.explode("disease_ids_list")

    # 3) Clean & convert to numeric, dropping anything that isn’t a valid integer
    exploded["disease_id"] = pd.to_numeric(
        exploded["disease_ids_list"].str.strip(),
        errors="coerce",  # convert invalid entries to NaN
    )
    exploded = exploded.dropna(subset=["disease_id"])
    exploded["disease_id"] = exploded["disease_id"].astype(int)

    # 4) Merge in programme_name
    exploded = exploded.merge(
        programmes[["programme_id", "programme_name"]], on="programme_id", how="left"
    )

    # 5) Aggregate multiple programmes per disease
    mapping = (
        exploded.groupby("disease_id")["programme_name"]
        .agg(lambda names: ",".join(sorted(set(names.dropna()))))
        .reset_index()
        .rename(columns={"programme_name": "program_names"})
    )

    # 6) Merge those names back onto your diseases sheet
    result = diseases.merge(mapping, left_on="ID", right_on="disease_id", how="left")
    # If your column in Diseases.xlsx is called something else (e.g. 'Programe_names'), adjust the next line:
    result["program_names"] = result["program_names"]

    # 7) (Optional) Drop the helper column after merge
    if "disease_id" in result.columns:
        result = result.drop(columns=["disease_id"])

    # 8) Save out
    result.to_excel(output_path, index=False)
    print(f"✔ Done – saved: {output_path}")


if __name__ == "__main__":
    extract_program_names(
        prog_dis_path="files/Programmes-Diseases.xlsx",
        programmes_path="files/Programmes.xlsx",
        diseases_path="files/Diseases.xlsx",
        output_path="Diseases_with_program_names.xlsx",
    )
