from django.urls import path
from . import views

urlpatterns = [
    path('', views.forecast_list, name='forecast_list'),
    path('upload/', views.upload_demand_data, name='upload_demand_data'),
    path('run/', views.run_forecast, name='run_forecast'),
]