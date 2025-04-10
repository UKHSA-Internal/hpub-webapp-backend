from enum import Enum


class ErrorCode(Enum):
    MISSING_REQUIRED_FIELDS = "MISSING_REQUIRED_FIELDS"
    MISSING_FIELD = "MISSING_FIELD"
    INVALID_QUERY_PARAM = "INVALID_QUERY_PARAM"
    AWS_ERROR = "AWS_ERROR"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"
    INVALID_DATA = "INVALID_DATA"
    DATABASE_ERROR = "DATABASE_ERROR"
    PROGRAM_NOT_FOUND = "PROGRAM_NOT_FOUND"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    NOT_FOUND = "NOT_FOUND"
    ESTABLISHMENT_NOT_FOUND = "ESTABLISHMENT_NOT_FOUND"
    PRODUCT_UPDATE_NOT_FOUND = "PRODUCT_UPDATE_NOT_FOUND"
    ORGANIZATION_NOT_FOUND = "ORGANIZATION_NOT_FOUND"
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
    USER_CREATION_ERROR = "USER_CREATION_ERROR"
    ADDRESS_CREATION_ERROR = "ADDRESS_CREATION_ERROR"
    ORDER_CREATION_ERROR = "ORDER_CREATION_ERROR"
    ORDER_DELETION_ERROR = "ORDER_DELETION_ERROR"
    BULK_UPLOAD_ERROR = "BULK_UPLOAD_ERROR"
    S3_UPLOAD_FAILED = "S3_UPLOAD_FAILED"
    S3_BUCKET_NOT_FOUND = "S3_BUCKET_NOT_FOUND"
    USER_AUTHENTICATION_ERROR = "USER_AUTHENTICATION_ERROR"
    NO_ADDRESSES_FOUND = "NO_ADDRESSES_FOUND"
    INVALID_STATUS = "INVALID_STATUS"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    ADDRESS_NOT_FOUND = "ADDRESS_NOT_FOUND"
    USER_DATA_INVALID = "USER_DATA_INVALID"
    PRODUCT_WITH_PRODUCT_CODE_NOT_FOUND = "PRODUCT_WITH_PRODUCT_CODE_NOT_FOUND"
    ORDER_LIMIT_EXCEEDED = "ORDER_LIMIT_EXCEEDED"
    PRODUCT_NOT_LIVE = "PRODUCT_NOT_LIVE"
    USER_REF_REQUIRED = "USER_REF_REQUIRED"
    PAGE_CREATION_ERROR = "PAGE_CREATION_ERROR"
    USER_INFO_REQUIRED = "USER_INFO_REQUIRED"
    MISSING_ORDER_FROM_DATE = "MISSING_ORDER_FROM_DATE"
    ATTRIBUTE_ERROR = "An attribute error occured."
    DUPLICATE_STATUS = "DUPLICATE_STATUS"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
    LANGUAGE_ID_DOES_NOT_EXIST = "LANGUAGE_ID_DOES_NOT_EXIST"

    def __str__(self):
        return self.value


class ErrorMessage(Enum):
    MISSING_FIELD = "A required field is missing."
    INVALID_DATA = "The provided data is invalid."
    AWS_ERROR = "An error occurred while interacting with AWS."
    S3_UPLOAD_FAILED = "Failed to retrieve file from S3."
    S3_BUCKET_NOT_FOUND = "The specified S3 bucket was not found."
    INVALID_QUERY_PARAM = "Invalid query parameter provided."
    TIMEOUT_ERROR = "A timeout error occurred."
    DATABASE_ERROR = "A database error occurred."
    PROGRAM_NOT_FOUND = "The specified program does not exist."
    PRODUCT_NOT_FOUND = "The specified product does not exist."
    PRODUCT_UPDATE_NOT_FOUND = "The product update data cannot be found."
    USER_NOT_FOUND = "The specified user does not exist."
    INTERNAL_SERVER_ERROR = "An internal server error occurred."
    NOT_FOUND = "The requested resource was not found."
    ESTABLISHMENT_NOT_FOUND = "No establishment found with the provided name."
    ORGANIZATION_NOT_FOUND = "No organization found with the provided name."
    PRODUCT_WITH_PRODUCT_CODE_NOT_FOUND = (
        "Product with the provided code does not exist."
    )
    USER_CREATION_ERROR = "An error occurred while creating the user."
    ADDRESS_CREATION_ERROR = "An error occurred while creating the address."
    ORDER_CREATION_ERROR = "An error occurred while creating the order."
    ORDER_DELETION_ERROR = "An error occurred while deleting the order."
    BULK_UPLOAD_ERROR = "An error occurred during bulk upload."
    USER_AUTHENTICATION_ERROR = "User Authentication required."
    NO_ADDRESSES_FOUND = "No addresses found for the user."
    INVALID_STATUS = "The status value is invalid."
    INVALID_TRANSITION = "The status transition is invalid."
    ADDRESS_NOT_FOUND = "Address not found."
    USER_DATA_INVALID = "User data is not provided or invalid."
    ORDER_LIMIT_EXCEEDED = "Order limit exceeded for this product."
    USER_REF_REQUIRED = "The logged-in user's reference is required."
    PAGE_CREATION_ERROR = (
        "An error occurred while creating or retrieving the parent page."
    )
    USER_INFO_REQUIRED = "User delivery information is required."
    MISSING_ORDER_FROM_DATE = "order_from_date must be provided when available_from_choice is 'specific_date'."
    ATTRIBUTE_ERROR = (
        "An error occurred while processing the update. Please check the data provided."
    )

    LANGUAGE_ID_DOES_NOT_EXIST = "Language ID does not exist."
    PROGRAM_NAME_DOES_NOT_EXIST = "Program name does not exist."
    INVALID_PROGRAM_OR_LANGUAGE = "Invalid program or language."

    @staticmethod
    def product_not_live(product_code):
        return f"Product with code {product_code} is not live yet."

    # PRODUCT_NOT_LIVE = "Product with this product_code not live yet."
    def __str__(self):
        return self.value
