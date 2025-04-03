# enums.py
from enum import Enum


class client(Enum):
    client_name = "UK Health Security Agency"


class invoicing_client(Enum):
    invoice_client = "UK Health Security Agency"


class product_group(Enum):
    product_group_name = "Immunisations (HPISD-I)"


class required_event_fields_draft(Enum):
    product_code = "product_code"
    product_title = "product_title"
    status = "status"
    unit_of_measure = "unit_of_measure"
    run_to_zero = "run_to_zero"


class required_event_fields_live(Enum):
    product_code = "product_code"
    product_title = "product_title"
    status = "status"
    unit_of_measure = "unit_of_measure"
    order_limits = "order_limits"
    run_to_zero = "run_to_zero"
    minimum_stock_level = "minimum_stock_level"
    cost_centre = "cost_centre"
    local_code = "local_code"
    stock_owner_email_address = "stock_owner_email_address"
    order_referral_email_address = "order_referral_email_address"
    file_url = "file_url"


class required_event_fields_withdrawn(Enum):
    product_code = "product_code"
    status = "status"


class required_event_fields_archived(Enum):
    product_code = "product_code"
    status = "status"
