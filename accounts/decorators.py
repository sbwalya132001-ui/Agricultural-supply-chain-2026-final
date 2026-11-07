from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.contrib.auth.mixins import AccessMixin


ROLE_MINISTRY = 'Ministry of Agriculture'
ROLE_DISTRICT = 'District Agricultural Officer'
ROLE_SUPPLIER = 'Supplier'
LEGACY_ROLE_WAREHOUSE = 'Warehouse Manager'
ROLE_DEALER = 'Agro-Dealer'

STAFF_ROLES = {
    ROLE_MINISTRY,
    ROLE_DISTRICT,
    ROLE_SUPPLIER,
    LEGACY_ROLE_WAREHOUSE,
    ROLE_DEALER,
}


def get_user_role(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return ROLE_MINISTRY
    role_names = set(user.groups.values_list('name', flat=True))
    for role_name in (ROLE_MINISTRY, ROLE_DISTRICT, ROLE_SUPPLIER, LEGACY_ROLE_WAREHOUSE, ROLE_DEALER):
        if role_name in role_names:
            return ROLE_SUPPLIER if role_name == LEGACY_ROLE_WAREHOUSE else role_name
    return None


def get_user_district(user):
    if get_user_role(user) not in (ROLE_DISTRICT, ROLE_SUPPLIER, ROLE_DEALER):
        return None
    if hasattr(user, 'agrodealer_profile'):
        district = getattr(user.agrodealer_profile, 'district', '')
        return district.strip() if district else None
    try:
        return user.profile.district.strip()
    except AttributeError:
        return None


def role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
            if get_user_role(request.user) in allowed_roles:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied

        return wrapped_view

    return decorator


class RoleRequiredMixin(AccessMixin):
    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        role = get_user_role(request.user)
        if role in self.allowed_roles:
            return super().dispatch(request, *args, **kwargs)
        raise PermissionDenied


def operational_access_required(view_func):
    """Require an authenticated operational stakeholder account."""
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        return view_func(request, *args, **kwargs)

    return wrapped_view