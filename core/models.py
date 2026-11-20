import os
import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

from .validators import (
    extract_youtube_id,
    validate_person_name,
    validate_phone,
    validate_youtube_url,
)


def proof_upload_path(instance, filename):
    """Guarda las fotos con un nombre aleatorio (no se filtra el nombre original)."""
    ext = os.path.splitext(filename)[1].lower()
    return f"challenge_proofs/{uuid.uuid4().hex}{ext}"


class User(AbstractUser):
    ROLE_CHOICES = (
        ('kinesiologo', 'Kinesiólogo'),
        ('paciente', 'Paciente'),
    )
    first_name = models.CharField(
        'Nombre', max_length=50, blank=True, validators=[validate_person_name]
    )
    last_name = models.CharField(
        'Apellido', max_length=50, blank=True, validators=[validate_person_name]
    )
    email = models.EmailField('Correo electrónico', max_length=254, unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='paciente')
    phone = models.CharField(
        max_length=16, blank=True, null=True, verbose_name='Teléfono',
        validators=[validate_phone],
    )
    age = models.PositiveSmallIntegerField(
        blank=True, null=True, verbose_name='Edad',
        validators=[MinValueValidator(1), MaxValueValidator(120)],
    )
    must_change_password = models.BooleanField(
        default=False, verbose_name='Debe cambiar su contraseña'
    )

    def save(self, *args, **kwargs):
        # El correo se guarda siempre en minúsculas: evita duplicados "A@x.cl" / "a@x.cl"
        self.email = (self.email or '').strip().lower()
        super().save(*args, **kwargs)

    def is_kinesiologo(self):
        return self.role == 'kinesiologo'

    def is_paciente(self):
        return self.role == 'paciente'

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"


class Patient(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='patient_profile')
    kinesiologo = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='patients', limit_choices_to={'role': 'kinesiologo'}
    )
    notes = models.TextField(max_length=2000, blank=True, null=True, verbose_name='Notas clínicas')
    points = models.PositiveIntegerField(default=0, verbose_name='Puntos')
    created_at = models.DateTimeField(auto_now_add=True)
    last_session = models.DateTimeField(blank=True, null=True, verbose_name='Última sesión')

    def __str__(self):
        return f"Paciente: {self.user.get_full_name() or self.user.username}"

    def update_last_session(self):
        self.last_session = timezone.now()
        self.save(update_fields=['last_session'])


class Challenge(models.Model):
    TYPE_CHOICES = (
        ('diario', 'Diario'),
        ('semanal', 'Semanal'),
        ('mensual', 'Mensual'),
    )
    # Duración máxima según el tipo (días / semanas / meses)
    MAX_DURATION = {'diario': 365, 'semanal': 52, 'mensual': 24}

    kinesiologo = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='created_challenges', limit_choices_to={'role': 'kinesiologo'}
    )
    name = models.CharField(max_length=100, verbose_name='Nombre')
    description = models.TextField(max_length=500, verbose_name='Descripción')
    challenge_type = models.CharField(max_length=10, choices=TYPE_CHOICES, verbose_name='Tipo')
    duration = models.PositiveSmallIntegerField(
        verbose_name='Duración',
        validators=[MinValueValidator(1), MaxValueValidator(365)],
    )
    points = models.PositiveIntegerField(
        verbose_name='Puntos al completar',
        validators=[MinValueValidator(1), MaxValueValidator(10000)],
    )
    video = models.ForeignKey(
        'Video', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='challenges', verbose_name='Video asociado'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def clean(self):
        limit = self.MAX_DURATION.get(self.challenge_type)
        if limit and isinstance(self.duration, int) and self.duration > limit:
            raise ValidationError({
                'duration': f'Para un desafío {self.get_challenge_type_display().lower()} '
                            f'la duración máxima es {limit}.'
            })

    def get_duration_label(self):
        labels = {'diario': 'día(s)', 'semanal': 'semana(s)', 'mensual': 'mes(es)'}
        return f"{self.duration} {labels.get(self.challenge_type, '')}"

    def __str__(self):
        return f"{self.name} ({self.get_challenge_type_display()})"


class PatientChallenge(models.Model):
    STATUS_CHOICES = (
        ('pendiente', 'Pendiente'),
        ('activo', 'Activo'),
    )
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='challenges')
    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name='patient_challenges')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendiente')
    assigned_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        unique_together = ('patient', 'challenge')

    def total_approved(self):
        return self.submissions.filter(status='aprobado').count()

    def total_submissions(self):
        return self.submissions.count()

    def pending_count(self):
        return self.submissions.filter(status='pendiente').count()

    def last_submission(self):
        return self.submissions.first()

    def can_submit_today(self):
        """Verifica si puede subir una nueva entrega según el tipo de desafío."""
        last = self.submissions.filter(status__in=['pendiente', 'aprobado']).first()
        if not last:
            return True
        delta = timezone.now() - last.submitted_at
        t = self.challenge.challenge_type
        if t == 'diario':
            return delta.days >= 1
        elif t == 'semanal':
            return delta.days >= 7
        elif t == 'mensual':
            return delta.days >= 30
        return True

    def __str__(self):
        return f"{self.patient} - {self.challenge.name} [{self.get_status_display()}]"


class ChallengeSubmission(models.Model):
    STATUS_CHOICES = (
        ('pendiente', 'Pendiente'),
        ('aprobado', 'Aprobado'),
        ('rechazado', 'Rechazado'),
    )
    patient_challenge = models.ForeignKey(
        PatientChallenge, on_delete=models.CASCADE, related_name='submissions'
    )
    proof_photo = models.ImageField(
        upload_to=proof_upload_path, blank=True, null=True,
        verbose_name='Foto de prueba',
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp'])],
    )
    proof_message = models.TextField(max_length=500, blank=True, null=True, verbose_name='Mensaje')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendiente')
    points_awarded = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)
    kin_feedback = models.TextField(max_length=500, blank=True, null=True, verbose_name='Feedback del kinesiólogo')

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f"Entrega #{self.pk} — {self.patient_challenge} [{self.get_status_display()}]"

    def can_award_points(self):
        return self.status == 'aprobado' and not self.points_awarded


@receiver(post_delete, sender=ChallengeSubmission)
def delete_proof_file(sender, instance, **kwargs):
    """Al borrar una entrega (o su paciente/desafío) se borra también la foto del disco."""
    if instance.proof_photo:
        instance.proof_photo.delete(save=False)


class Reward(models.Model):
    kinesiologo = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='rewards', limit_choices_to={'role': 'kinesiologo'}
    )
    name = models.CharField(max_length=100, verbose_name='Nombre')
    description = models.TextField(max_length=500, verbose_name='Descripción')
    points_cost = models.PositiveIntegerField(
        verbose_name='Costo en puntos',
        validators=[MinValueValidator(1), MaxValueValidator(100000)],
    )
    stock = models.PositiveIntegerField(
        verbose_name='Stock', validators=[MaxValueValidator(10000)],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.points_cost} pts)"

    def has_stock(self):
        return self.stock > 0


class RewardClaim(models.Model):
    STATUS_CHOICES = (
        ('pendiente', 'Pendiente'),
        ('aprobado', 'Aprobado'),
        ('rechazado', 'Rechazado'),
    )
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='reward_claims')
    reward = models.ForeignKey(Reward, on_delete=models.CASCADE, related_name='claims')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendiente')
    claimed_at = models.DateTimeField(auto_now_add=True)
    points_spent = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.patient} reclamó {self.reward.name}"


class Video(models.Model):
    CATEGORY_CHOICES = (
        ('rehabilitacion', 'Rehabilitación'),
        ('fortalecimiento', 'Fortalecimiento'),
        ('estiramiento', 'Estiramiento y flexibilidad'),
        ('movilidad', 'Movilidad articular'),
        ('equilibrio', 'Equilibrio y coordinación'),
        ('postura', 'Postura y espalda'),
        ('respiracion', 'Respiración y relajación'),
        ('calentamiento', 'Calentamiento'),
        ('otro', 'Otro'),
    )
    kinesiologo = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='videos', limit_choices_to={'role': 'kinesiologo'}
    )
    title = models.CharField(max_length=100, verbose_name='Título')
    youtube_url = models.URLField(
        max_length=200, verbose_name='Link de YouTube', validators=[validate_youtube_url]
    )
    description = models.TextField(max_length=500, blank=True, verbose_name='Descripción')
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, verbose_name='Categoría')
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def get_youtube_id(self):
        return extract_youtube_id(self.youtube_url)

    def get_thumbnail(self):
        vid_id = self.get_youtube_id()
        if vid_id:
            return f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"
        return None

    def __str__(self):
        return self.title


class Notification(models.Model):
    TYPE_CHOICES = (
        ('desafio_completado', 'Desafío Completado'),
        ('recompensa_reclamada', 'Recompensa Reclamada'),
        ('desafio_asignado', 'Desafío Asignado'),
        ('recompensa_aprobada', 'Recompensa Aprobada'),
        ('recompensa_rechazada', 'Recompensa Rechazada'),
    )
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200)
    message = models.TextField(max_length=500)
    is_read = models.BooleanField(default=False)
    link = models.CharField(max_length=300, blank=True, default='', verbose_name='Enlace')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} → {self.recipient.username}"


class Message(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages')
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name='messages'
    )
    body = models.TextField(max_length=1000, verbose_name='Mensaje')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender} → {self.recipient}: {self.body[:40]}"


class PointHistory(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='point_history')
    points = models.IntegerField(verbose_name='Puntos')
    reason = models.CharField(max_length=200, verbose_name='Motivo')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.patient} {'+' if self.points > 0 else ''}{self.points} — {self.reason}"
