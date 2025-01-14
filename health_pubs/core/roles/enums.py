from enum import Enum


class PersonaPermission(Enum):
    ADMIN = [
        "publish_publication",
        "order_on_behalf",
        "autogenerate_product_codes",
        "view_all_publications",
        "manage_publication_links",
        "search_and_filter_publications",
        "view_publication_info",
        "control_publication_access",
        "remove_publication",
        "manage_stock_inventory",
        "manage_establishments",
        "manage_addresses",
        "log_events",
        "manage_user_orders",
        "add_roles",
        "update_roles",
        "delete_roles",
        "manage_user_profiles",
    ]
    REGISTERED_USER = [
        "view_all_publications",
        "view_publication_info",
        "search_and_filter_publications",
        "order_publication",
        "view_orders",
        "manage_addresses",
        "send_feedback",
        "send_contact_message",
        "create_user_profile",
    ]
    GUEST = [
        "view_all_publications",
        "view_publication_info",
        "search_and_filter_publications",
        "order_publication",
        "view_orders",
        "manage_addresses",
        "create_user_profile",
        "send_feedback",
        "send_contact_message",
    ]
