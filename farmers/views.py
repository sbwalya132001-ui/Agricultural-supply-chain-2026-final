from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView
from .models import Farmer
from .forms import FarmerForm
from accounts.decorators import (
    ROLE_DISTRICT,
    ROLE_MINISTRY,
    RoleRequiredMixin,
    get_user_district,
    role_required,
)


class FarmerListView(RoleRequiredMixin, ListView):
    allowed_roles = (ROLE_MINISTRY, ROLE_DISTRICT)
    model = Farmer
    template_name = 'farmers/farmer_list.html'
    context_object_name = 'farmers'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset()
        district = get_user_district(self.request.user)
        return queryset.filter(district__iexact=district) if district else queryset

class FarmerCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = (ROLE_MINISTRY, ROLE_DISTRICT)
    model = Farmer
    form_class = FarmerForm
    template_name = 'farmers/farmer_form.html'
    success_url = reverse_lazy('farmer_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        district = get_user_district(self.request.user)
        if district:
            kwargs['district_scope'] = district
        return kwargs