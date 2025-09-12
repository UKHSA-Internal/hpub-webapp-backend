import pandas as pd


def filter_unique_emails(file_path: str, output_path: str = "filtered_users.xlsx"):
    """
    Reads a .xlsx file of user data and saves a new file with only unique email rows,
    keeping the first occurrence of each unique email.

    :param file_path: Path to the input Excel file
    :param output_path: Path to save the filtered Excel file
    """
    try:
        # Read the Excel file
        df = pd.read_excel(file_path)

        # Check if the 'email' column exists
        if "email" not in df.columns:
            raise ValueError("No 'email' column found in the Excel file.")

        # Drop duplicate emails, keeping the first occurrence
        filtered_df = df.drop_duplicates(subset="email", keep="first")

        # Save to a new Excel file
        filtered_df.to_excel(output_path, index=False)

        print(f"Filtered file with unique emails saved to '{output_path}'")
        return filtered_df

    except Exception as e:
        print(f"Error: {e}")


# Example usage
if __name__ == "__main__":
    input_file = "users.xlsx"  # Replace with your input filename
    output_file = "unique_users.xlsx"
    result_df = filter_unique_emails(input_file, output_file)
