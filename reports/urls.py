from django.urls import path

from . import views


urlpatterns = [
    path('', views.report_export, name='report_export'),
    path('farmers.csv', views.export_farmers, name='export_farmers'),
    path('forecasts.csv', views.export_forecasts, name='export_forecasts'),
    path('allocations.csv', views.export_allocations, name='export_allocations'),
    path('routes.csv', views.export_routes, name='export_routes'),
]
