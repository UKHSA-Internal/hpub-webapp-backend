#!/usr/bin/env python3
import pandas as pd


def extract_program_names(
    prog_dis_path: str, programmes_path: str, vaccinations_path: str, output_path: str
):
    """
    Reads programme–vaccination links, programme definitions, and vaccinations list,
    then writes out the vaccinations sheet with a `program_names` column showing
    comma-separated programme names per vaccination.
    """
    # 1) Load input files
    prog_dis = pd.read_excel(prog_dis_path)  # columns: programme_id, vaccination_ids
    programmes = pd.read_excel(programmes_path)  # columns: programme_id, programme_name
    vaccinations = pd.read_excel(
        vaccinations_path
    )  # columns including ID, optional program_names

    # Drop any existing program_names to avoid conflicts
    vaccinations = vaccinations.drop(columns=["program_names"], errors="ignore")

    # 2) Expand vaccination_ids into one row per programme–vaccination link
    links = prog_dis.assign(
        vaccination_ids_list=prog_dis["vaccination_ids"]
        .astype(str)
        .str.strip("[]")
        .str.split(",")
    ).explode("vaccination_ids_list")

    # 3) Clean & convert to numeric, drop invalid
    links = (
        links.assign(
            vaccination_id=pd.to_numeric(
                links["vaccination_ids_list"].str.strip(), errors="coerce"
            )
        )
        .dropna(subset=["vaccination_id"])
        .assign(vaccination_id=lambda df: df["vaccination_id"].astype(int))
    )

    # 4) Merge in programme_name
    links = links.merge(
        programmes[["programme_id", "programme_name"]],
        on="programme_id",
        how="left",
        validate="many_to_one",
    )

    # 5) Aggregate multiple programmes per vaccination
    mapping = (
        links.groupby("vaccination_id")["programme_name"]
        .agg(lambda names: ",".join(sorted({n for n in names if pd.notna(n)})))
        .reset_index()
        .rename(columns={"programme_name": "program_names"})
    )

    # 6) Merge those names back onto your vaccinations sheet with validation
    result = vaccinations.merge(
        mapping,
        left_on="ID",
        right_on="vaccination_id",
        how="left",
        validate="one_to_one",
    )

    # 7) Drop helper merge column
    result = result.drop(columns=["vaccination_id"], errors="ignore")

    # 8) Save out
    result.to_excel(output_path, index=False)
    print(f"✔ Done – saved: {output_path}")


if __name__ == "__main__":
    extract_program_names(
        prog_dis_path="files/Programmes-Vaccinations.xlsx",
        programmes_path="files/Programmes.xlsx",
        vaccinations_path="files/Vaccinations.xlsx",
        output_path="Vaccinations_with_program_names.xlsx",
    )
