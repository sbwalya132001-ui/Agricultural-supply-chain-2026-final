from .decorators import get_user_role


def stakeholder_role(request):
    return {'stakeholder_role': get_user_role(request.user)}