from django.urls import path

from . import review_views

handler400 = review_views.bad_request
handler403 = review_views.permission_denied
handler404 = review_views.page_not_found
handler500 = review_views.server_error


urlpatterns = [
    path("kavita-sync/ready/", review_views.readiness, name="kavita_sync_ready"),
    path("kavita-sync/health/", review_views.health, name="kavita_sync_health"),
    path("kavita-sync/", review_views.index, name="kavita_sync_review"),
    path(
        "kavita-sync/<int:chapter_id>/approve/",
        review_views.approve,
        name="kavita_sync_approve",
    ),
    path(
        "kavita-sync/<int:chapter_id>/manual/",
        review_views.manual,
        name="kavita_sync_manual",
    ),
    path(
        "kavita-sync/<int:chapter_id>/ignore/",
        review_views.ignore_item,
        name="kavita_sync_ignore",
    ),
    path(
        "kavita-sync/<int:chapter_id>/reconsider/",
        review_views.reconsider_item,
        name="kavita_sync_reconsider",
    ),
]
