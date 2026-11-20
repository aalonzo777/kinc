from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Si el usuario tiene una contraseña temporal (la creó el kinesiólogo),
    solo puede ir a 'Cambiar contraseña' o 'Cerrar sesión' hasta que la cambie."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and getattr(user, 'must_change_password', False):
            allowed = {reverse('change_password'), reverse('logout')}
            if request.path not in allowed and not request.path.startswith('/static/'):
                return redirect('change_password')
        return self.get_response(request)
