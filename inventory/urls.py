from django.urls import path
from . import views

urlpatterns = [
    path('', views.allocation_list, name='allocation_list'),
    path('run/', views.run_allocation, name='run_allocation'),
    path('dispatch/', views.supplier_dispatch, name='supplier_dispatch'),
    path('dispatch/', views.supplier_dispatch, name='warehouse_dispatch'),
]
