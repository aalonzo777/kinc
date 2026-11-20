from .models import ChallengeSubmission, Message, Notification, PatientChallenge, RewardClaim


def nav_badges(request):
    """Indica qué ítems del menú tienen novedades (para mostrar el puntito rojo)."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    badges = {
        'chat': Message.objects.filter(recipient=user, is_read=False).exists(),
        'notifications': Notification.objects.filter(recipient=user, is_read=False).exists(),
    }
    if user.is_kinesiologo():
        # entregas de pacientes esperando revisión y recompensas esperando aprobación
        badges['challenges'] = ChallengeSubmission.objects.filter(
            patient_challenge__challenge__kinesiologo=user, status='pendiente').exists()
        badges['rewards'] = RewardClaim.objects.filter(
            reward__kinesiologo=user, status='pendiente').exists()
    elif user.is_paciente():
        # desafíos nuevos que aún no ha aceptado
        badges['challenges'] = PatientChallenge.objects.filter(
            patient__user=user, status='pendiente').exists()
    badges['any'] = any(badges.values())
    return {'nav_badges': badges}
