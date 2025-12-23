from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("statistics/", views.statistics, name="statistics"),
    path("export/<str:fmt>/", views.export_report, name="export"),
    path("import/", views.import_view, name="import"),

    path("drive/", views.drive_backups, name="drive_backups"),
    path("drive/export/<str:fmt>/", views.drive_export, name="drive_export"),
    path("drive/restore/<str:file_id>/", views.drive_restore, name="drive_restore"),
    path("drive/disconnect/", views.drive_disconnect, name="drive_disconnect"),
    path("drive/connect/", views.drive_connect, name="drive_connect"),

]
