import functools
import logging
import hashlib
import mimetypes
from xml.sax.saxutils import escape

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, F, Count
from django.http import FileResponse, Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    User, Patient, Challenge, PatientChallenge, ChallengeSubmission,
    Reward, RewardClaim, Video, Notification, Message, PointHistory
)
from .forms import (
    LoginForm, AddPatientForm, EditPatientForm,
    ChallengeForm, RewardForm, VideoForm, ChallengeSubmissionForm,
    ChatMessageForm, VerifyForm, SearchForm, ChangePasswordForm,
)
from .validators import safe_int


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def create_notification(recipient, notif_type, title, message, link=''):
    Notification.objects.create(
        recipient=recipient,
        notification_type=notif_type,
        title=title,
        message=message,
        link=link,
    )


logger = logging.getLogger(__name__)

LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 15 * 60


class ClaimError(Exception):
    """Error controlado al reclamar una recompensa (hace rollback de la transacción)."""


def form_errors_text(form):
    """Convierte los errores de un formulario en un texto legible para un mensaje."""
    parts = []
    for name, errors in form.errors.items():
        field = form.fields.get(name)
        label = field.label if field is not None and field.label else ''
        for error in errors:
            parts.append(f'{label}: {error}' if label else str(error))
    return ' '.join(parts)


def client_ip(request):
    return request.META.get('REMOTE_ADDR', '')


def login_cache_key(email, ip):
    raw = f'{email.lower()}|{ip}'.encode('utf-8')
    return 'loginfail:' + hashlib.sha256(raw).hexdigest()


def kinesiologo_required(view_func):
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.is_kinesiologo():
            messages.error(request, 'Acceso restringido a kinesiólogos.')
            return redirect('patient_dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


def paciente_required(view_func):
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect('login')
        if not user.is_paciente():
            messages.error(request, 'Acceso restringido a pacientes.')
            return redirect('kin_dashboard')
        try:
            user.patient_profile
        except Patient.DoesNotExist:
            if user.is_staff:
                return redirect('/admin/')
            logout(request)
            messages.error(request, 'Tu cuenta no tiene perfil de paciente. Contacta a tu kinesiólogo.')
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return wrapper


# ─────────────────────────────────────────────
# AUTENTICACIÓN
# ─────────────────────────────────────────────

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Ingresa un correo válido y una contraseña (máximo 128 caracteres).')
        else:
            email = form.cleaned_data['username']
            password = form.cleaned_data['password']
            key = login_cache_key(email, client_ip(request))
            fails = cache.get(key, 0)
            if fails >= LOGIN_MAX_ATTEMPTS:
                messages.error(request, 'Demasiados intentos fallidos. Espera 15 minutos antes de volver a intentarlo.')
            else:
                user_obj = User.objects.filter(email__iexact=email).first()
                # Se llama a authenticate siempre (aunque el correo no exista) para que
                # el tiempo de respuesta no revele qué correos están registrados.
                user = authenticate(
                    request,
                    username=user_obj.username if user_obj else '__sin_usuario__',
                    password=password,
                )
                if user_obj is None:
                    user = None
                if user is not None:
                    cache.delete(key)
                    login(request, user)
                    if user.is_paciente():
                        patient = getattr(user, 'patient_profile', None)
                        if patient:
                            patient.update_last_session()
                    return redirect('dashboard')
                cache.set(key, fails + 1, LOGIN_LOCK_SECONDS)
                messages.error(request, 'Correo o contraseña incorrectos.')
    return render(request, 'core/login.html', {'form': LoginForm()})


@login_required
def dashboard_redirect(request):
    if request.user.is_kinesiologo():
        return redirect('kin_dashboard')
    return redirect('patient_dashboard')


@require_POST
def logout_view(request):
    logout(request)
    return redirect('login')


# ─────────────────────────────────────────────
# PANEL KINESIÓLOGO
# ─────────────────────────────────────────────

@kinesiologo_required
def kin_dashboard(request):
    patients = Patient.objects.filter(kinesiologo=request.user).select_related('user').order_by('-last_session')
    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    # Entregas pendientes de revisar
    pending_submissions = ChallengeSubmission.objects.filter(
        patient_challenge__challenge__kinesiologo=request.user,
        status='pendiente'
    ).select_related('patient_challenge__patient__user', 'patient_challenge__challenge').order_by('-submitted_at')[:5]
    context = {
        'patients': patients,
        'total_patients': patients.count(),
        'unread_count': unread_count,
        'pending_submissions': pending_submissions,
        'pending_count': ChallengeSubmission.objects.filter(
            patient_challenge__challenge__kinesiologo=request.user, status='pendiente'
        ).count(),
    }
    return render(request, 'core/kin_dashboard.html', context)


# ─── PACIENTES CRUD ───

@kinesiologo_required
def patient_list(request):
    search = SearchForm(request.GET)
    q = ''
    if search.is_valid():
        q = search.cleaned_data['q']
    else:
        messages.warning(request, 'La búsqueda admite como máximo 100 caracteres.')
    patients = Patient.objects.filter(kinesiologo=request.user).select_related('user')
    if q:
        patients = patients.filter(
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(user__email__icontains=q)
        )
    return render(request, 'core/patients/list.html', {'patients': patients, 'q': q})


@kinesiologo_required
def patient_add(request):
    if request.method == 'POST':
        form = AddPatientForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            with transaction.atomic():
                user = User.objects.create_user(
                    username=d['email'][:150],
                    email=d['email'],
                    password=d['password'],
                    first_name=d['first_name'],
                    last_name=d['last_name'],
                    phone=d.get('phone') or '',
                    age=d.get('age'),
                    role='paciente',
                    must_change_password=True,   # contraseña temporal: la cambia al ingresar
                )
                Patient.objects.create(
                    user=user,
                    kinesiologo=request.user,
                    last_session=timezone.now(),
                )
            messages.success(request, f'Paciente {user.get_full_name()} agregado correctamente.')
            return redirect('patient_list')
    else:
        form = AddPatientForm()
    return render(request, 'core/patients/add.html', {'form': form})


@kinesiologo_required
def patient_detail(request, pk):
    patient = get_object_or_404(Patient, pk=pk, kinesiologo=request.user)
    assigned = patient.challenges.select_related('challenge').order_by('-assigned_at')
    approved = ChallengeSubmission.objects.filter(
        patient_challenge__patient=patient, status='aprobado'
    ).select_related('patient_challenge__challenge').order_by('-reviewed_at')
    reward_claims = patient.reward_claims.select_related('reward').order_by('-claimed_at')
    available_challenges = Challenge.objects.filter(
        kinesiologo=request.user, is_active=True
    ).exclude(patient_challenges__patient=patient)
    context = {
        'patient': patient,
        'active_challenges': assigned,
        'approved_submissions': approved[:20],
        'approved_count': approved.count(),
        'reward_claims': reward_claims,
        'available_challenges': available_challenges,
    }
    return render(request, 'core/patients/detail.html', context)


@kinesiologo_required
def patient_edit(request, pk):
    patient = get_object_or_404(Patient, pk=pk, kinesiologo=request.user)
    if request.method == 'POST':
        form = EditPatientForm(request.POST, instance=patient)
        if form.is_valid():
            form.save()
            messages.success(request, 'Paciente actualizado correctamente.')
            return redirect('patient_detail', pk=pk)
    else:
        form = EditPatientForm(instance=patient)
    return render(request, 'core/patients/edit.html', {'form': form, 'patient': patient})


@kinesiologo_required
def patient_delete(request, pk):
    patient = get_object_or_404(Patient, pk=pk, kinesiologo=request.user)
    if request.method == 'POST':
        name = patient.user.get_full_name()
        patient.user.delete()
        messages.success(request, f'Paciente {name} eliminado.')
        return redirect('patient_list')
    return render(request, 'core/patients/confirm_delete.html', {'patient': patient})


@kinesiologo_required
@require_POST
def assign_challenge(request, patient_pk):
    patient = get_object_or_404(Patient, pk=patient_pk, kinesiologo=request.user)
    challenge_id = safe_int(request.POST.get('challenge_id'))
    if challenge_id is None:
        messages.error(request, 'Selecciona un desafío válido.')
        return redirect('patient_detail', pk=patient_pk)
    challenge = get_object_or_404(Challenge, pk=challenge_id, kinesiologo=request.user, is_active=True)
    pc, created = PatientChallenge.objects.get_or_create(
        patient=patient, challenge=challenge,
        defaults={'status': 'pendiente'}
    )
    if created:
        create_notification(
            patient.user,
            'desafio_asignado',
            '¡Nuevo desafío asignado!',
            f'Tu kinesiólogo te asignó el desafío: {challenge.name}',
            link='/paciente/desafios/'
        )
        messages.success(request, f'Desafío "{challenge.name}" asignado a {patient.user.get_full_name()}.')
    else:
        messages.warning(request, 'Este desafío ya fue asignado al paciente.')
    return redirect('patient_detail', pk=patient_pk)


# ─── DESAFÍOS CRUD ───

@kinesiologo_required
def challenge_list(request):
    challenges = Challenge.objects.filter(kinesiologo=request.user).order_by('-created_at')
    return render(request, 'core/challenges/list.html', {'challenges': challenges})


@kinesiologo_required
def challenge_add(request):
    if request.method == 'POST':
        form = ChallengeForm(request.POST, user=request.user)
        if form.is_valid():
            ch = form.save(commit=False)
            ch.kinesiologo = request.user
            ch.save()
            messages.success(request, f'Desafío "{ch.name}" creado.')
            return redirect('challenge_list')
    else:
        form = ChallengeForm(user=request.user)
    return render(request, 'core/challenges/form.html', {'form': form, 'action': 'Crear'})


@kinesiologo_required
def challenge_edit(request, pk):
    challenge = get_object_or_404(Challenge, pk=pk, kinesiologo=request.user)
    if request.method == 'POST':
        form = ChallengeForm(request.POST, instance=challenge, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Desafío actualizado.')
            return redirect('challenge_list')
    else:
        form = ChallengeForm(instance=challenge, user=request.user)
    return render(request, 'core/challenges/form.html', {'form': form, 'action': 'Editar', 'challenge': challenge})


@kinesiologo_required
def challenge_delete(request, pk):
    challenge = get_object_or_404(Challenge, pk=pk, kinesiologo=request.user)
    if request.method == 'POST':
        challenge.delete()
        messages.success(request, 'Desafío eliminado.')
        return redirect('challenge_list')
    return render(request, 'core/challenges/confirm_delete.html', {'challenge': challenge})


@kinesiologo_required
@require_POST
def challenge_verify(request, pc_pk):
    """Aprobar o rechazar una entrega específica (una sola vez, sin duplicar puntos)."""
    pc = get_object_or_404(
        PatientChallenge.objects.select_related('patient__user', 'challenge'),
        pk=pc_pk, challenge__kinesiologo=request.user,
    )
    form = VerifyForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Datos inválidos. ' + form_errors_text(form))
        return redirect('patient_challenge_detail', pc_pk=pc.pk)

    action = form.cleaned_data['action']
    feedback = form.cleaned_data['feedback']
    points = pc.challenge.points

    with transaction.atomic():
        submission = get_object_or_404(
            ChallengeSubmission.objects.select_for_update(),
            pk=form.cleaned_data['submission_pk'], patient_challenge=pc,
        )
        if submission.status != 'pendiente':
            messages.warning(request, 'Esta entrega ya fue revisada.')
            return redirect('patient_challenge_detail', pc_pk=pc.pk)

        submission.reviewed_at = timezone.now()
        submission.kin_feedback = feedback
        if action == 'approve':
            submission.status = 'aprobado'
            submission.points_awarded = True
            submission.save()
            # F() hace la suma en la base de datos: no se pierden puntos si hay dos acciones a la vez
            Patient.objects.filter(pk=pc.patient_id).update(points=F('points') + points)
            PointHistory.objects.create(
                patient=pc.patient, points=points,
                reason=f"Entrega aprobada: {pc.challenge.name}"[:200],
            )
        else:
            submission.status = 'rechazado'
            submission.save()
            PointHistory.objects.create(
                patient=pc.patient, points=0,
                reason=f"Entrega rechazada: {pc.challenge.name}"[:200],
            )

    if action == 'approve':
        create_notification(
            pc.patient.user, 'desafio_completado', '¡Entrega aprobada!',
            f'Tu entrega del desafío "{pc.challenge.name}" fue aprobada. Ganaste {points} puntos.',
            link='/paciente/desafios/'
        )
        messages.success(request, f'Entrega aprobada. +{points} pts al paciente.')
    else:
        create_notification(
            pc.patient.user, 'desafio_completado', 'Entrega rechazada',
            f'Tu entrega del desafío "{pc.challenge.name}" fue rechazada. Intenta nuevamente.',
            link='/paciente/desafios/'
        )
        messages.warning(request, 'Entrega rechazada. El paciente puede volver a intentarlo.')
    return redirect('patient_challenge_detail', pc_pk=pc.pk)


# ─── RECOMPENSAS CRUD ───

@kinesiologo_required
def reward_list(request):
    rewards = Reward.objects.filter(kinesiologo=request.user).order_by('-created_at')
    pending_claims = RewardClaim.objects.filter(
        reward__kinesiologo=request.user, status='pendiente'
    ).select_related('patient__user', 'reward')
    return render(request, 'core/rewards/list.html', {
        'rewards': rewards,
        'pending_claims': pending_claims,
    })


@kinesiologo_required
def reward_add(request):
    if request.method == 'POST':
        form = RewardForm(request.POST)
        if form.is_valid():
            r = form.save(commit=False)
            r.kinesiologo = request.user
            r.save()
            messages.success(request, f'Recompensa "{r.name}" creada.')
            return redirect('reward_list')
    else:
        form = RewardForm()
    return render(request, 'core/rewards/form.html', {'form': form, 'action': 'Crear'})


@kinesiologo_required
def reward_edit(request, pk):
    reward = get_object_or_404(Reward, pk=pk, kinesiologo=request.user)
    if request.method == 'POST':
        form = RewardForm(request.POST, instance=reward)
        if form.is_valid():
            form.save()
            messages.success(request, 'Recompensa actualizada.')
            return redirect('reward_list')
    else:
        form = RewardForm(instance=reward)
    return render(request, 'core/rewards/form.html', {'form': form, 'action': 'Editar', 'reward': reward})


@kinesiologo_required
def reward_delete(request, pk):
    reward = get_object_or_404(Reward, pk=pk, kinesiologo=request.user)
    if request.method == 'POST':
        reward.delete()
        messages.success(request, 'Recompensa eliminada.')
        return redirect('reward_list')
    return render(request, 'core/rewards/confirm_delete.html', {'reward': reward})


@kinesiologo_required
@require_POST
def reward_claim_action(request, claim_pk):
    action = request.POST.get('action')
    if action not in ('approve', 'reject'):
        messages.error(request, 'Acción no válida.')
        return redirect('reward_list')

    with transaction.atomic():
        claim = get_object_or_404(
            RewardClaim.objects.select_for_update(),
            pk=claim_pk, reward__kinesiologo=request.user,
        )
        if claim.status != 'pendiente':
            messages.warning(request, 'Este reclamo ya fue resuelto.')
            return redirect('reward_list')

        if action == 'approve':
            claim.status = 'aprobado'
            claim.save(update_fields=['status'])
            create_notification(
                claim.patient.user, 'recompensa_aprobada', '¡Recompensa aprobada!',
                f'Tu recompensa "{claim.reward.name}" fue aprobada por tu kinesiólogo.',
                link='/paciente/recompensas/'
            )
            messages.success(request, 'Recompensa aprobada.')
        else:
            claim.status = 'rechazado'
            claim.save(update_fields=['status'])
            # Se devuelven los puntos y el stock, y queda registrado en el historial
            Patient.objects.filter(pk=claim.patient_id).update(points=F('points') + claim.points_spent)
            Reward.objects.filter(pk=claim.reward_id).update(stock=F('stock') + 1)
            PointHistory.objects.create(
                patient=claim.patient, points=claim.points_spent,
                reason=f"Recompensa rechazada (puntos devueltos): {claim.reward.name}"[:200],
            )
            create_notification(
                claim.patient.user, 'recompensa_rechazada', 'Recompensa rechazada',
                f'Tu reclamo de "{claim.reward.name}" fue rechazado. Se devolvieron tus puntos.',
                link='/paciente/recompensas/'
            )
            messages.warning(request, 'Recompensa rechazada. Puntos devueltos al paciente.')
    return redirect('reward_list')


# ─── VIDEOS CRUD ───

@kinesiologo_required
def video_list(request):
    videos = Video.objects.filter(kinesiologo=request.user).annotate(
        n_challenges=Count('challenges')
    ).order_by('-created_at')
    return render(request, 'core/videos/list.html', {'videos': videos})


@kinesiologo_required
def video_add(request):
    if request.method == 'POST':
        form = VideoForm(request.POST)
        if form.is_valid():
            v = form.save(commit=False)
            v.kinesiologo = request.user
            v.save()
            messages.success(request, f'Video "{v.title}" agregado.')
            return redirect('video_list')
    else:
        form = VideoForm()
    return render(request, 'core/videos/form.html', {'form': form, 'action': 'Agregar'})


@kinesiologo_required
def video_edit(request, pk):
    video = get_object_or_404(Video, pk=pk, kinesiologo=request.user)
    if request.method == 'POST':
        form = VideoForm(request.POST, instance=video)
        if form.is_valid():
            form.save()
            messages.success(request, 'Video actualizado.')
            return redirect('video_list')
    else:
        form = VideoForm(instance=video)
    return render(request, 'core/videos/form.html', {'form': form, 'action': 'Editar', 'video': video})


@kinesiologo_required
def video_delete(request, pk):
    video = get_object_or_404(Video, pk=pk, kinesiologo=request.user)
    if request.method == 'POST':
        video.delete()
        messages.success(request, 'Video eliminado.')
        return redirect('video_list')
    return render(request, 'core/videos/confirm_delete.html', {'video': video})


# ─── NOTIFICACIONES ───

@kinesiologo_required
def notifications(request):
    notifs = Notification.objects.filter(recipient=request.user).order_by('-created_at')
    notifs.filter(is_read=False).update(is_read=True)
    return render(request, 'core/notifications.html', {'notifications': notifs})




# ─────────────────────────────────────────────
# GESTIÓN DE DESAFÍOS ASIGNADOS A PACIENTE
# ─────────────────────────────────────────────

@kinesiologo_required
def patient_challenge_detail(request, pc_pk):
    """Ver detalle de un desafío asignado con todas sus entregas."""
    pc = get_object_or_404(PatientChallenge, pk=pc_pk, challenge__kinesiologo=request.user)
    submissions = pc.submissions.order_by('-submitted_at')
    pending_count  = submissions.filter(status='pendiente').count()
    rejected_count = submissions.filter(status='rechazado').count()
    total_points_given = pc.challenge.points * pc.total_approved()
    return render(request, 'core/patients/challenge_detail.html', {
        'pc': pc,
        'submissions': submissions,
        'pending_count': pending_count,
        'rejected_count': rejected_count,
        'total_points_given': total_points_given,
    })


@kinesiologo_required
def patient_challenge_remove(request, pc_pk):
    """Quitar (eliminar) un desafío ya asignado a un paciente."""
    pc = get_object_or_404(PatientChallenge, pk=pc_pk, challenge__kinesiologo=request.user)
    patient_pk = pc.patient.pk
    if request.method == 'POST':
        challenge_name = pc.challenge.name
        pc.delete()
        messages.success(request, f'Desafío "{challenge_name}" quitado al paciente.')
        return redirect('patient_detail', pk=patient_pk)
    return render(request, 'core/patients/challenge_remove_confirm.html', {'pc': pc})


@kinesiologo_required
def patient_challenge_edit(request, pc_pk):
    """Cambiar el desafío asignado a un paciente (reinicia su progreso en ese desafío)."""
    pc = get_object_or_404(PatientChallenge, pk=pc_pk, challenge__kinesiologo=request.user)
    available = Challenge.objects.filter(
        kinesiologo=request.user, is_active=True
    ).exclude(pk=pc.challenge_id)
    if request.method == 'POST':
        new_id = safe_int(request.POST.get('challenge_id'))
        new_ch = available.filter(pk=new_id).first() if new_id else None
        if new_ch is None:
            messages.error(request, 'Selecciona un desafío válido.')
        elif PatientChallenge.objects.filter(patient=pc.patient, challenge=new_ch).exists():
            messages.warning(request, 'Este desafío ya está asignado al paciente.')
        else:
            with transaction.atomic():
                pc.submissions.all().delete()   # también borra las fotos del disco
                pc.challenge = new_ch
                pc.status = 'pendiente'
                pc.accepted_at = None
                pc.save()
            messages.success(request, f'Desafío actualizado a "{new_ch.name}".')
            return redirect('patient_detail', pk=pc.patient.pk)
    return render(request, 'core/patients/challenge_edit_assigned.html', {
        'pc': pc, 'available': available
    })


# ─────────────────────────────────────────────
# PANEL PACIENTE
# ─────────────────────────────────────────────

@paciente_required
def patient_dashboard(request):
    profile = request.user.patient_profile
    active = profile.challenges.count()
    completed = ChallengeSubmission.objects.filter(
        patient_challenge__patient=profile, status='aprobado'
    ).count()
    unread = Notification.objects.filter(recipient=request.user, is_read=False).count()
    context = {
        'profile': profile,
        'active_count': active,
        'completed_count': completed,
        'unread_count': unread,
    }
    return render(request, 'core/patient/dashboard.html', context)


@paciente_required
def patient_challenges(request):
    profile = request.user.patient_profile
    my_challenges = profile.challenges.select_related('challenge').order_by('-assigned_at')
    return render(request, 'core/patient/challenges.html', {
        'profile': profile,
        'my_challenges': my_challenges,
    })


@paciente_required
def accept_challenge(request, pc_pk):
    pc = get_object_or_404(PatientChallenge, pk=pc_pk, patient=request.user.patient_profile)
    if pc.status == 'pendiente':
        pc.status = 'activo'
        pc.accepted_at = timezone.now()
        pc.save()
        messages.success(request, f'¡Desafío "{pc.challenge.name}" aceptado!')
    return redirect('patient_challenges')


@paciente_required
@require_POST
def submit_proof(request, pc_pk):
    profile = request.user.patient_profile
    pc = get_object_or_404(
        PatientChallenge.objects.select_related('challenge'), pk=pc_pk, patient=profile
    )
    if pc.status != 'activo':
        messages.error(request, 'Primero debes aceptar el desafío para poder enviar una entrega.')
        return redirect('patient_challenges')

    with transaction.atomic():
        if not pc.can_submit_today():
            msgs_map = {
                'diario': 'Ya enviaste una entrega hoy. Vuelve mañana.',
                'semanal': 'Ya enviaste una entrega esta semana.',
                'mensual': 'Ya enviaste una entrega este mes.',
            }
            messages.warning(request, msgs_map.get(pc.challenge.challenge_type, 'Ya enviaste una entrega reciente.'))
            return redirect('patient_challenges')
        form = ChallengeSubmissionForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, 'No se pudo enviar la entrega. ' + form_errors_text(form))
            return redirect('patient_challenges')
        submission = form.save(commit=False)
        submission.patient_challenge = pc
        submission.save()

    kin = profile.kinesiologo
    if kin:
        create_notification(
            kin,
            'desafio_completado',
            f'{request.user.get_full_name()} envió una entrega',
            f'Nueva entrega del desafío: {pc.challenge.name}. Requiere verificación.',
            link=f'/kin/desafio-paciente/{pc.pk}/detalle/'
        )
    messages.success(request, '¡Entrega enviada! Tu kinesiólogo la revisará.')
    return redirect('patient_challenges')


@paciente_required
def patient_rewards(request):
    profile = request.user.patient_profile
    rewards = Reward.objects.filter(kinesiologo=profile.kinesiologo, is_active=True)
    my_claims = profile.reward_claims.select_related('reward').order_by('-claimed_at')
    return render(request, 'core/patient/rewards.html', {
        'profile': profile,
        'rewards': rewards,
        'my_claims': my_claims,
    })


@paciente_required
@require_POST
def claim_reward(request, pk):
    profile = request.user.patient_profile
    reward = get_object_or_404(Reward, pk=pk, kinesiologo=profile.kinesiologo, is_active=True)
    try:
        with transaction.atomic():
            # UPDATE condicionales: la base de datos descuenta stock/puntos de forma atómica,
            # así un doble clic (o dos pestañas) nunca deja stock ni puntos en negativo.
            if not Reward.objects.filter(pk=reward.pk, stock__gt=0).update(stock=F('stock') - 1):
                raise ClaimError('No hay stock disponible.')
            if not Patient.objects.filter(pk=profile.pk, points__gte=reward.points_cost).update(
                points=F('points') - reward.points_cost
            ):
                raise ClaimError('No tienes suficientes puntos.')
            PointHistory.objects.create(
                patient=profile, points=-reward.points_cost,
                reason=f"Recompensa canjeada: {reward.name}"[:200],
            )
            RewardClaim.objects.create(
                patient=profile, reward=reward, points_spent=reward.points_cost,
            )
    except ClaimError as exc:
        messages.error(request, str(exc))
        return redirect('patient_rewards')

    kin = profile.kinesiologo
    if kin:
        create_notification(
            kin, 'recompensa_reclamada',
            f'{request.user.get_full_name()} reclamó una recompensa',
            f'El paciente reclamó: {reward.name} por {reward.points_cost} puntos.',
            link='/kin/recompensas/'
        )
    messages.success(request, f'¡Recompensa "{reward.name}" reclamada!')
    return redirect('patient_rewards')


@paciente_required
def patient_profile(request):
    profile = request.user.patient_profile
    return render(request, 'core/patient/profile.html', {'profile': profile})


@paciente_required
def patient_notifications(request):
    notifs = Notification.objects.filter(recipient=request.user).order_by('-created_at')
    notifs.filter(is_read=False).update(is_read=True)
    return render(request, 'core/patient/notifications.html', {'notifications': notifs})


# ─────────────────────────────────────────────
# ESTADÍSTICAS GENERALES (KINESIÓLOGO)
# ─────────────────────────────────────────────

@kinesiologo_required
def kin_stats(request):
    patients = Patient.objects.filter(kinesiologo=request.user)
    total_patients = patients.count()

    total_assigned = PatientChallenge.objects.filter(challenge__kinesiologo=request.user).count()

    subs = ChallengeSubmission.objects.filter(patient_challenge__challenge__kinesiologo=request.user)
    total_completed = subs.filter(status='aprobado').count()
    total_pending = subs.filter(status='pendiente').count()
    total_rejected = subs.filter(status='rechazado').count()
    total_reviewed = total_completed + total_rejected

    all_rewards = RewardClaim.objects.filter(reward__kinesiologo=request.user)
    total_claims = all_rewards.count()
    total_approved = all_rewards.filter(status='aprobado').count()

    top_patients = patients.select_related('user').order_by('-points')[:5]

    top_challenges = (
        Challenge.objects.filter(kinesiologo=request.user)
        .annotate(completions=Count(
            'patient_challenges__submissions',
            filter=Q(patient_challenges__submissions__status='aprobado'),
        ))
        .order_by('-completions')[:5]
    )

    context = {
        'total_patients': total_patients,
        'total_assigned': total_assigned,
        'total_completed': total_completed,
        'total_pending': total_pending,
        'total_rejected': total_rejected,
        'total_claims': total_claims,
        'total_approved': total_approved,
        'top_patients': top_patients,
        'top_challenges': top_challenges,
        'completion_rate': round(total_completed / total_reviewed * 100) if total_reviewed else 0,
    }
    return render(request, 'core/stats.html', context)


# ─────────────────────────────────────────────
# CHAT / MENSAJERÍA
# ─────────────────────────────────────────────


@kinesiologo_required
def kin_chat_list(request):
    """Lista de todos los pacientes con acceso rápido al chat."""
    from .models import Message
    patients = Patient.objects.filter(kinesiologo=request.user).select_related('user')
    # Para cada paciente, contar mensajes no leídos
    patient_data = []
    for p in patients:
        unread = Message.objects.filter(
            patient=p, recipient=request.user, is_read=False
        ).count()
        last_msg = Message.objects.filter(patient=p).order_by('-created_at').first()
        patient_data.append({
            'patient': p,
            'unread': unread,
            'last_msg': last_msg,
        })
    # Ordenar: primero los que tienen mensajes no leídos, luego por último mensaje
    patient_data.sort(key=lambda x: (-(x['unread'] > 0), -(x['last_msg'].created_at.timestamp() if x['last_msg'] else 0)))
    return render(request, 'core/chat_list.html', {'patient_data': patient_data})

@kinesiologo_required
def kin_chat(request, patient_pk):
    patient = get_object_or_404(Patient, pk=patient_pk, kinesiologo=request.user)
    if request.method == 'POST':
        form = ChatMessageForm(request.POST)
        if form.is_valid():
            Message.objects.create(
                sender=request.user,
                recipient=patient.user,
                patient=patient,
                body=form.cleaned_data['body'],
            )
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':  # ← NUEVO
                return JsonResponse({'ok': True})                             # ← NUEVO
        else:
            messages.error(request, 'Mensaje no válido. ' + form_errors_text(form))
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':  # ← NUEVO
                return JsonResponse({'ok': False}, status=400)                # ← NUEVO
        return redirect('kin_chat', patient_pk=patient_pk)
    Message.objects.filter(patient=patient, recipient=request.user, is_read=False).update(is_read=True)
    msgs = Message.objects.filter(patient=patient)
    return render(request, 'core/chat.html', {'patient': patient, 'msgs': msgs, 'is_kin': True})


@paciente_required
def patient_chat(request):
    profile = request.user.patient_profile
    kin = profile.kinesiologo
    if not kin:
        messages.error(request, 'No tienes kinesiólogo asignado.')
        return redirect('patient_dashboard')
    if request.method == 'POST':
        form = ChatMessageForm(request.POST)
        if form.is_valid():
            Message.objects.create(
                sender=request.user,
                recipient=kin,
                patient=profile,
                body=form.cleaned_data['body'],
            )
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':  
                return JsonResponse({'ok': True})                             
        else:
            messages.error(request, 'Mensaje no válido. ' + form_errors_text(form))
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':  
                return JsonResponse({'ok': False}, status=400)                
        return redirect('patient_chat')
    Message.objects.filter(patient=profile, recipient=request.user, is_read=False).update(is_read=True)
    msgs = Message.objects.filter(patient=profile)
    return render(request, 'core/chat.html', {'patient': profile, 'msgs': msgs, 'is_kin': False, 'kin': kin})

@login_required
def chat_poll(request, patient_pk):
    """
    Endpoint de polling: devuelve los mensajes nuevos desde 'since' (ID).
    Usado por el chat para actualizar en tiempo real sin recargar.
    GET /kin/chat/<patient_pk>/poll/?since=<last_message_id>
    """
    # Verificar que el usuario tiene acceso a este chat
    patient = get_object_or_404(Patient, pk=patient_pk)
    is_kin = hasattr(request.user, 'kinesiologo_profile') or (
        hasattr(patient, 'kinesiologo') and patient.kinesiologo == request.user
    )
    is_patient = hasattr(request.user, 'patient_profile') and request.user.patient_profile == patient

    if not (is_kin or is_patient):
        return JsonResponse({'error': 'forbidden'}, status=403)

    since_id = request.GET.get('since', 0)
    try:
        since_id = int(since_id)
    except (ValueError, TypeError):
        since_id = 0

    new_msgs = Message.objects.filter(
        patient=patient,
        id__gt=since_id,
    ).select_related('sender').order_by('id')

    # Marcar como leídos los mensajes recibidos
    new_msgs.filter(recipient=request.user, is_read=False).update(is_read=True)

    data = []
    for m in new_msgs:
        data.append({
            'id':        m.id,
            'body':      m.body,
            'sender_id': m.sender.id,
            'sender':    m.sender.get_full_name(),
            'mine':      m.sender == request.user,
            'time':      m.created_at.strftime('%d/%m %H:%M'),
        })

    return JsonResponse({'messages': data})



# ─────────────────────────────────────────────
# GRÁFICO DE PROGRESO DE PUNTOS (paciente)
# ─────────────────────────────────────────────

@kinesiologo_required
def patient_progress_chart(request, pk):
    from .models import PointHistory
    patient = get_object_or_404(Patient, pk=pk, kinesiologo=request.user)
    history = patient.point_history.order_by('created_at')

    labels = [h.created_at.strftime('%d/%m/%Y') for h in history]
    # Acumulado
    acumulado = []
    total = 0
    for h in history:
        total += h.points
        acumulado.append(total)

    context = {
        'patient': patient,
        'labels': labels,
        'acumulado': acumulado,
        'history': history,
    }
    return render(request, 'core/patient_progress.html', context)


@paciente_required
def my_progress_chart(request):
    from .models import PointHistory
    profile = request.user.patient_profile
    history = profile.point_history.order_by('created_at')

    labels = [h.created_at.strftime('%d/%m/%Y') for h in history]
    acumulado = []
    total = 0
    for h in history:
        total += h.points
        acumulado.append(total)

    context = {
        'profile': profile,
        'labels': labels,
        'acumulado': acumulado,
        'history': history,
    }
    return render(request, 'core/patient/progress.html', context)


# ─────────────────────────────────────────────
# EXPORTAR PDF FICHA PACIENTE
# ─────────────────────────────────────────────

@kinesiologo_required
def export_patient_pdf(request, pk):
    from django.http import HttpResponse
    import io, textwrap
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.units import cm
        HAS_REPORTLAB = True
    except ImportError:
        HAS_REPORTLAB = False

    patient = get_object_or_404(Patient, pk=pk, kinesiologo=request.user)

    if not HAS_REPORTLAB:
        # Fallback: exportar como TXT
        lines = [
            "=" * 60,
            f"  FICHA PACIENTE — KINC",
            "=" * 60,
            f"Nombre:         {patient.user.get_full_name()}",
            f"Correo:         {patient.user.email}",
            f"Teléfono:       {patient.user.phone or '—'}",
            f"Edad:           {patient.user.age or '—'} años",
            f"Puntos:         {patient.points}",
            f"Última sesión:  {patient.last_session.strftime('%d/%m/%Y %H:%M') if patient.last_session else '—'}",
            f"Kinesiólogo:    {patient.kinesiologo.get_full_name() if patient.kinesiologo else '—'}",
            "",
            "NOTAS CLÍNICAS",
            "-" * 40,
            patient.notes or "(sin notas)",
            "",
            "DESAFÍOS",
            "-" * 40,
        ]
        for pc in patient.challenges.select_related('challenge').all():
            lines.append(f"  • {pc.challenge.name} [{pc.get_status_display()}] — {pc.challenge.points} pts")
        lines += ["", "RECOMPENSAS RECLAMADAS", "-" * 40]
        for rc in patient.reward_claims.select_related('reward').all():
            lines.append(f"  • {rc.reward.name} [{rc.get_status_display()}] — {rc.points_spent} pts")
        content = "\n".join(lines)
        response = HttpResponse(content, content_type='text/plain; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="ficha_paciente_{patient.pk}.txt"'
        return response

    # ── PDF con ReportLab ──
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    PRIMARY = colors.HexColor('#1565C0')
    LIGHT   = colors.HexColor('#E3F2FD')

    title_style = ParagraphStyle('title', parent=styles['Title'],
                                 textColor=PRIMARY, fontSize=20, spaceAfter=4)
    h2_style = ParagraphStyle('h2', parent=styles['Heading2'],
                              textColor=PRIMARY, fontSize=13, spaceBefore=14, spaceAfter=4)
    normal = styles['Normal']
    normal.fontSize = 10

    story = []

    # Encabezado
    story.append(Paragraph("🏥 KINC — Ficha de Paciente", title_style))
    story.append(HRFlowable(width="100%", thickness=2, color=PRIMARY))
    story.append(Spacer(1, 0.3*cm))

    # Datos personales
    story.append(Paragraph("Datos personales", h2_style))
    data = [
        ['Nombre',        patient.user.get_full_name()],
        ['Correo',        patient.user.email],
        ['Teléfono',      patient.user.phone or '—'],
        ['Edad',          f"{patient.user.age} años" if patient.user.age else '—'],
        ['Puntos',        str(patient.points)],
        ['Kinesiólogo',   patient.kinesiologo.get_full_name() if patient.kinesiologo else '—'],
        ['Última sesión', patient.last_session.strftime('%d/%m/%Y %H:%M') if patient.last_session else '—'],
    ]
    t = Table(data, colWidths=[4*cm, 12*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), LIGHT),
        ('TEXTCOLOR',  (0,0), (0,-1), PRIMARY),
        ('FONTNAME',   (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 10),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, colors.HexColor('#F5F9FF')]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E0')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t)

    # Notas clínicas
    if patient.notes:
        story.append(Paragraph("Notas clínicas", h2_style))
        story.append(Paragraph(escape(patient.notes).replace('\n', '<br/>'), normal))

    # Desafíos
    story.append(Paragraph("Desafíos", h2_style))
    ch_data = [['Desafío', 'Tipo', 'Estado', 'Puntos']]
    for pc in patient.challenges.select_related('challenge').all():
        ch_data.append([
            pc.challenge.name,
            pc.challenge.get_challenge_type_display(),
            pc.get_status_display(),
            str(pc.challenge.points),
        ])
    if len(ch_data) > 1:
        ct = Table(ch_data, colWidths=[7*cm, 3*cm, 3.5*cm, 2.5*cm])
        ct.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), PRIMARY),
            ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
            ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,-1), 9),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F5F9FF')]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E0')),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(ct)
    else:
        story.append(Paragraph("Sin desafíos asignados.", normal))

    # Recompensas
    story.append(Paragraph("Recompensas reclamadas", h2_style))
    rw_data = [['Recompensa', 'Fecha', 'Estado', 'Puntos gastados']]
    for rc in patient.reward_claims.select_related('reward').all():
        rw_data.append([
            rc.reward.name,
            rc.claimed_at.strftime('%d/%m/%Y'),
            rc.get_status_display(),
            str(rc.points_spent),
        ])
    if len(rw_data) > 1:
        rt = Table(rw_data, colWidths=[7*cm, 3*cm, 3.5*cm, 2.5*cm])
        rt.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), PRIMARY),
            ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
            ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,-1), 9),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F5F9FF')]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E0')),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(rt)
    else:
        story.append(Paragraph("Sin recompensas reclamadas.", normal))

    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E0')))
    story.append(Paragraph(
        f"Generado por KINC · {timezone.now().strftime('%d/%m/%Y %H:%M')}",
        ParagraphStyle('footer', parent=normal, textColor=colors.grey, fontSize=8)
    ))

    doc.build(story)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="ficha_paciente_{patient.pk}.pdf"'
    return response


# ─────────────────────────────────────────────
# CUENTA Y ARCHIVOS PROTEGIDOS
# ─────────────────────────────────────────────

@login_required
def change_password(request):
    """Cambio de contraseña (obligatorio en el primer ingreso si la creó el kinesiólogo)."""
    forced = request.user.must_change_password
    if request.method == 'POST':
        form = ChangePasswordForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            user.must_change_password = False
            user.save(update_fields=['must_change_password'])
            update_session_auth_hash(request, user)   # no cierra la sesión actual
            messages.success(request, 'Contraseña actualizada correctamente.')
            return redirect('dashboard')
    else:
        form = ChangePasswordForm(request.user)
    return render(request, 'core/change_password.html', {'form': form, 'forced': forced})


@login_required
def proof_image(request, sub_pk):
    """Entrega la foto de una entrega SOLO al paciente dueño o a su kinesiólogo."""
    sub = get_object_or_404(
        ChallengeSubmission.objects.select_related(
            'patient_challenge__challenge', 'patient_challenge__patient'
        ),
        pk=sub_pk,
    )
    pc = sub.patient_challenge
    user = request.user
    allowed = (
        (user.is_kinesiologo() and pc.challenge.kinesiologo_id == user.id)
        or (user.is_paciente() and pc.patient.user_id == user.id)
    )
    if not allowed or not sub.proof_photo:
        raise Http404()
    content_type = mimetypes.guess_type(sub.proof_photo.name)[0] or 'application/octet-stream'
    try:
        response = FileResponse(sub.proof_photo.open('rb'), content_type=content_type)
    except Exception:   # archivo ausente en disco o en el bucket remoto
        logger.exception('No se pudo abrir la foto de la entrega %s', sub_pk)
        raise Http404()
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


# ─── DETALLE DE UN DESAFÍO (a qué pacientes está asignado) ───

@kinesiologo_required
def challenge_detail(request, pk):
    challenge = get_object_or_404(
        Challenge.objects.select_related('video'), pk=pk, kinesiologo=request.user
    )
    assignments = challenge.patient_challenges.select_related('patient__user').order_by(
        'patient__user__first_name', 'patient__user__last_name'
    )
    assigned_ids = list(assignments.values_list('patient_id', flat=True))
    unassigned = Patient.objects.filter(kinesiologo=request.user).exclude(
        pk__in=assigned_ids
    ).select_related('user').order_by('user__first_name', 'user__last_name')
    subs = ChallengeSubmission.objects.filter(patient_challenge__challenge=challenge)
    return render(request, 'core/challenges/detail.html', {
        'challenge': challenge,
        'assignments': assignments,
        'unassigned': unassigned,
        'total_subs': subs.count(),
        'approved_subs': subs.filter(status='aprobado').count(),
        'pending_subs': subs.filter(status='pendiente').count(),
        'rejected_subs': subs.filter(status='rechazado').count(),
    })


@kinesiologo_required
@require_POST
def challenge_assign_patients(request, pk):
    """Asignar este desafío a uno o varios pacientes del kinesiólogo."""
    challenge = get_object_or_404(Challenge, pk=pk, kinesiologo=request.user, is_active=True)
    ids = {safe_int(raw) for raw in request.POST.getlist('patient_ids')}
    ids.discard(None)
    if not ids:
        messages.error(request, 'Selecciona al menos un paciente.')
        return redirect('challenge_detail', pk=pk)
    created = 0
    with transaction.atomic():
        for patient in Patient.objects.filter(pk__in=ids, kinesiologo=request.user).select_related('user'):
            _, was_created = PatientChallenge.objects.get_or_create(
                patient=patient, challenge=challenge, defaults={'status': 'pendiente'}
            )
            if was_created:
                created += 1
                create_notification(
                    patient.user, 'desafio_asignado', '¡Nuevo desafío asignado!',
                    f'Tu kinesiólogo te asignó el desafío: {challenge.name}',
                    link='/paciente/desafios/'
                )
    if created:
        messages.success(request, f'Desafío asignado a {created} paciente{"s" if created != 1 else ""}.')
    else:
        messages.warning(request, 'No se asignó a nadie (los pacientes ya lo tenían o no son válidos).')
    return redirect('challenge_detail', pk=pk)
