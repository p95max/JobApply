from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("statistics/", views.statistics, name="statistics"),
    path("export/<str:fmt>/", views.export_report, name="export"),
    path("import/", views.import_view, name="import"),
]
