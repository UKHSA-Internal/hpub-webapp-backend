from rest_framework.pagination import PageNumberPagination

class ListResponse(PageNumberPagination):
    from django.conf import settings

    page_size = getattr(
        settings, "USERS_LIST_PAGE_SIZE", 10
    )  # Set pagination to 10 items per page

    def get_paginated_response(self, data, status_code=200):
        response = Response(
            {
                "metadata": {
                    "total_count": self.page.paginator.count,
                    "page_size": self.page_size,
                    "page_number": self.page.number,
                    "next_page": self.get_next_link(),
                    "previous_page": self.get_previous_link(),
                },
                "data": data,
            },
            status=status_code,
        )
        return response
