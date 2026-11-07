from django.urls import path

from . import views


urlpatterns = [
    path('', views.route_list, name='route_list'),
    path('dealer/', views.dealer_portal, name='dealer_portal'),
    path('dealer/stock-receipt/<int:dispatch_id>/', views.dealer_confirm_stock_receipt, name='dealer_confirm_stock_receipt'),
    path('dealer/farmer-collection/<int:allocation_id>/', views.dealer_confirm_farmer_collection, name='dealer_confirm_farmer_collection'),
    path('dealer/confirm/<int:stop_id>/', views.dealer_confirm_delivery, name='dealer_confirm_delivery'),
    path('run/', views.run_route, name='run_route'),
]
