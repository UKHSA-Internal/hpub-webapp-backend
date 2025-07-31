import pandas as pd


def remap_user_ids(
    address_file,
    duplicate_users_file,
    non_duplicate_users_file,
    output_file,
    log_file="unmapped_user_ids_log.csv",
):
    # Load all Excel files
    addresses_df = pd.read_excel(address_file)
    duplicate_users_df = pd.read_excel(duplicate_users_file)
    non_duplicate_users_df = pd.read_excel(non_duplicate_users_file)

    # Create lookup maps
    duplicate_userid_to_email = duplicate_users_df.set_index("user_id")[
        "email"
    ].to_dict()
    email_to_correct_userid = non_duplicate_users_df.set_index("email")[
        "user_id"
    ].to_dict()

    # Tracking for unmapped user IDs and emails
    unmapped_records = []

    # Function to remap each user_id in address data
    def remap_user_id(old_user_id):
        email = duplicate_userid_to_email.get(old_user_id)
        if not email:
            unmapped_records.append(
                {
                    "original_user_id": old_user_id,
                    "issue": "Email not found for duplicate user ID",
                }
            )
            return old_user_id

        new_user_id = email_to_correct_userid.get(email)
        if not new_user_id:
            unmapped_records.append(
                {
                    "original_user_id": old_user_id,
                    "email": email,
                    "issue": "Email not found in non-duplicate user list",
                }
            )
            return old_user_id

        return new_user_id

    # Apply remapping
    addresses_df["user_id"] = addresses_df["user_id"].apply(remap_user_id)

    # Save updated addresses
    addresses_df.to_excel(output_file, index=False)
    print(f"✅ Updated addresses saved to: {output_file}")

    # Save unmapped issues if any
    if unmapped_records:
        log_df = pd.DataFrame(unmapped_records)
        log_df.to_csv(log_file, index=False)
        print(f"⚠️  {len(unmapped_records)} unmapped entries logged to: {log_file}")
    else:
        print("✅ All user_ids successfully remapped.")


# Example usage
if __name__ == "__main__":
    remap_user_ids(
        address_file="address_with_user_id_from_duplicate_users_data.xlsx",
        duplicate_users_file="users_with_duplicated.xlsx",
        non_duplicate_users_file="users_without_duplicate.xlsx",
        output_file="address_with_user_id_from_non_duplicate_users_data.xlsx",
    )
