from django.urls import path
from . import views

urlpatterns = [
    path('', views.FarmerListView.as_view(), name='farmer_list'),
    path('add/', views.FarmerCreateView.as_view(), name='farmer_create'),
]