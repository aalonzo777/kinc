from django import forms
from django.conf import settings
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import User, Patient, Challenge, Reward, Video, ChallengeSubmission
from .validators import (
    validate_person_name,
    validate_phone,
    normalize_phone,
    extract_youtube_id,
    canonical_youtube_url,
)

CTRL = {'class': 'form-control'}


def _name_field(label, placeholder=''):
    return forms.CharField(
        label=label, min_length=2, max_length=50,
        validators=[validate_person_name],
        widget=forms.TextInput(attrs={**CTRL, 'placeholder': placeholder, 'autocomplete': 'off'}),
    )


# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────

class LoginForm(forms.Form):
    username = forms.EmailField(label='Correo electrónico', max_length=254)
    password = forms.CharField(
        label='Contraseña', max_length=128, strip=False, widget=forms.PasswordInput
    )


# ─────────────────────────────────────────────
# PACIENTES
# ─────────────────────────────────────────────

class PatientFieldsMixin:
    """Reglas compartidas por 'Agregar' y 'Editar' paciente."""

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        qs = User.objects.filter(email__iexact=email)
        current_user_id = getattr(getattr(self, 'instance', None), 'user_id', None)
        if current_user_id:
            qs = qs.exclude(pk=current_user_id)
        if qs.exists():
            raise ValidationError('Ya existe un usuario con este correo.')
        return email

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data.get('phone') or '')
        if phone:
            validate_phone(phone)
        return phone


class AddPatientForm(PatientFieldsMixin, forms.Form):
    first_name = _name_field('Nombre', 'Juan')
    last_name = _name_field('Apellido', 'Pérez')
    email = forms.EmailField(
        label='Correo electrónico', max_length=150,
        widget=forms.EmailInput(attrs={**CTRL, 'placeholder': 'paciente@correo.com'}),
    )
    phone = forms.CharField(
        label='Teléfono', max_length=20, required=False,
        widget=forms.TextInput(attrs={**CTRL, 'placeholder': '+56 9 1234 5678', 'inputmode': 'tel'}),
    )
    age = forms.IntegerField(
        label='Edad', min_value=1, max_value=120, required=False,
        widget=forms.NumberInput(attrs={**CTRL, 'placeholder': '35'}),
    )
    password = forms.CharField(
        label='Contraseña para el paciente', max_length=128, strip=False,
        widget=forms.PasswordInput(attrs={**CTRL, 'placeholder': 'Mínimo 8 caracteres', 'autocomplete': 'new-password'}),
        help_text='El paciente deberá cambiarla en su primer inicio de sesión.',
    )

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        if password:
            # Se compara con los datos del paciente (que no se parezca al nombre/correo)
            candidate = User(
                username=cleaned.get('email') or '',
                email=cleaned.get('email') or '',
                first_name=cleaned.get('first_name') or '',
                last_name=cleaned.get('last_name') or '',
            )
            try:
                validate_password(password, user=candidate)
            except ValidationError as exc:
                self.add_error('password', exc)
        return cleaned


class EditPatientForm(PatientFieldsMixin, forms.ModelForm):
    first_name = _name_field('Nombre')
    last_name = _name_field('Apellido')
    email = forms.EmailField(
        label='Correo electrónico', max_length=150,
        widget=forms.EmailInput(attrs=CTRL),
    )
    phone = forms.CharField(
        label='Teléfono', max_length=20, required=False,
        widget=forms.TextInput(attrs={**CTRL, 'inputmode': 'tel'}),
    )
    age = forms.IntegerField(
        label='Edad', required=False, min_value=1, max_value=120,
        widget=forms.NumberInput(attrs=CTRL),
    )

    class Meta:
        model = Patient
        fields = ['notes']
        labels = {'notes': 'Notas clínicas'}
        widgets = {'notes': forms.Textarea(attrs={**CTRL, 'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            user = self.instance.user
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            self.fields['email'].initial = user.email
            self.fields['phone'].initial = user.phone
            self.fields['age'].initial = user.age

    def save(self, commit=True):
        patient = super().save(commit=False)
        user = patient.user
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.email = self.cleaned_data['email']
        user.phone = self.cleaned_data.get('phone') or ''
        user.age = self.cleaned_data.get('age')
        if commit:
            user.save()
            patient.save()
        return patient


# ─────────────────────────────────────────────
# DESAFÍOS / RECOMPENSAS / VIDEOS
# ─────────────────────────────────────────────

class ChallengeForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo se pueden asociar videos del propio kinesiólogo (no los de otros)
        videos = Video.objects.filter(kinesiologo=user) if user is not None else Video.objects.none()
        self.fields['video'].queryset = videos
        self.fields['video'].required = False
        self.fields['video'].empty_label = '— Sin video —'
        self.fields['video'].label_from_instance = lambda v: f'{v.title} · {v.get_category_display()}'

    class Meta:
        model = Challenge
        fields = ['name', 'description', 'challenge_type', 'duration', 'points', 'video']
        labels = {
            'name': 'Nombre del desafío',
            'description': 'Descripción',
            'challenge_type': 'Tipo de desafío',
            'duration': 'Duración',
            'points': 'Puntos al completar',
            'video': 'Video asociado (opcional)',
        }
        widgets = {
            'name': forms.TextInput(attrs={**CTRL, 'placeholder': 'Ej: Caminar 30 minutos'}),
            'description': forms.Textarea(attrs={**CTRL, 'rows': 3, 'placeholder': 'Describe el desafío...'}),
            'challenge_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_challenge_type'}),
            'duration': forms.NumberInput(attrs={**CTRL, 'min': 1, 'max': 365, 'id': 'id_duration'}),
            'points': forms.NumberInput(attrs={**CTRL, 'min': 1, 'max': 10000, 'placeholder': 'Ej: 100'}),
            'video': forms.Select(attrs={'class': 'form-select'}),
        }


class RewardForm(forms.ModelForm):
    class Meta:
        model = Reward
        fields = ['name', 'description', 'points_cost', 'stock']
        labels = {
            'name': 'Nombre de la recompensa',
            'description': 'Descripción',
            'points_cost': 'Costo en puntos',
            'stock': 'Stock disponible',
        }
        widgets = {
            'name': forms.TextInput(attrs={**CTRL, 'placeholder': 'Ej: Sesión gratuita'}),
            'description': forms.Textarea(attrs={**CTRL, 'rows': 3}),
            'points_cost': forms.NumberInput(attrs={**CTRL, 'min': 1, 'max': 100000}),
            'stock': forms.NumberInput(attrs={**CTRL, 'min': 0, 'max': 10000}),
        }


class VideoForm(forms.ModelForm):
    # Se acepta con o sin https:// y con o sin www.; se guarda siempre en formato estándar
    youtube_url = forms.CharField(
        label='Link de YouTube', max_length=300,
        widget=forms.TextInput(attrs={**CTRL, 'placeholder': 'youtube.com/watch?v=...', 'inputmode': 'url', 'autocomplete': 'off'}),
        help_text='Puedes pegarlo con o sin https:// y con o sin www.',
    )

    class Meta:
        model = Video
        fields = ['title', 'youtube_url', 'description', 'category']
        labels = {
            'title': 'Título del video',
            'description': 'Descripción',
            'category': 'Categoría',
        }
        widgets = {
            'title': forms.TextInput(attrs={**CTRL, 'placeholder': 'Ej: Ejercicios de rodilla'}),
            'description': forms.Textarea(attrs={**CTRL, 'rows': 3}),
            'category': forms.Select(attrs={'class': 'form-select'}),
        }

    def clean_youtube_url(self):
        video_id = extract_youtube_id(self.cleaned_data['youtube_url'])
        if not video_id:
            raise ValidationError('Ingresa un link válido de YouTube (youtube.com/watch?v=... o youtu.be/...).')
        return canonical_youtube_url(video_id)


# ─────────────────────────────────────────────
# ENTREGAS (foto + mensaje)
# ─────────────────────────────────────────────

class ChallengeSubmissionForm(forms.ModelForm):
    class Meta:
        model = ChallengeSubmission
        fields = ['proof_photo', 'proof_message']
        labels = {
            'proof_photo': 'Foto de evidencia',
            'proof_message': 'Mensaje (opcional)',
        }
        widgets = {
            'proof_photo': forms.FileInput(attrs={**CTRL, 'accept': 'image/jpeg,image/png,image/webp'}),
            'proof_message': forms.Textarea(attrs={
                **CTRL, 'rows': 3, 'placeholder': 'Cuéntale a tu kinesiólogo cómo te fue...',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['proof_photo'].required = True  # la foto es la evidencia: obligatoria

    def clean_proof_photo(self):
        photo = self.cleaned_data.get('proof_photo')
        if not photo:
            raise ValidationError('Debes adjuntar una foto.')
        max_bytes = getattr(settings, 'MAX_UPLOAD_SIZE', 4 * 1024 * 1024)
        if photo.size > max_bytes:
            raise ValidationError(f'La foto pesa demasiado (máximo {max_bytes // (1024 * 1024)} MB).')
        # forms.ImageField ya verificó con Pillow que es una imagen real; aquí validamos el formato
        image_format = getattr(getattr(photo, 'image', None), 'format', None)
        if image_format not in ('JPEG', 'PNG', 'WEBP'):
            raise ValidationError('Formato no permitido. Usa una foto JPG, PNG o WEBP.')
        return photo


# ─────────────────────────────────────────────
# CHAT, VERIFICACIÓN, BÚSQUEDA
# ─────────────────────────────────────────────

class ChatMessageForm(forms.Form):
    body = forms.CharField(label='Mensaje', max_length=1000, strip=True)


class VerifyForm(forms.Form):
    ACTIONS = (('approve', 'Aprobar'), ('reject', 'Rechazar'))
    submission_pk = forms.IntegerField(label='Entrega', min_value=1, max_value=999_999_999)
    action = forms.ChoiceField(label='Acción', choices=ACTIONS)
    feedback = forms.CharField(label='Feedback', max_length=500, required=False, strip=True)


class SearchForm(forms.Form):
    q = forms.CharField(label='Búsqueda', max_length=100, required=False, strip=True)


# ─────────────────────────────────────────────
# CONTRASEÑA
# ─────────────────────────────────────────────

class ChangePasswordForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control form-control-lg', 'maxlength': 128})

    def clean(self):
        cleaned = super().clean()
        old, new = cleaned.get('old_password'), cleaned.get('new_password1')
        if old and new and old == new:
            self.add_error('new_password1', 'La nueva contraseña debe ser distinta de la actual.')
        return cleaned
