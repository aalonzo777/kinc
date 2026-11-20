from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from .models import User, Patient, Challenge, PatientChallenge, ChallengeSubmission, Reward, RewardClaim, Video, Notification


class KincUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'role')


class KincUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = KincUserCreationForm
    form = KincUserChangeForm
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_active')
    list_filter = ('role', 'is_active')
    fieldsets = BaseUserAdmin.fieldsets + (
        ('KINC', {'fields': ('role', 'phone', 'age', 'must_change_password')}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('KINC', {'fields': ('role', 'phone', 'age', 'email', 'first_name', 'last_name')}),
    )


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('user', 'kinesiologo', 'points', 'last_session')
    list_filter = ('kinesiologo',)


@admin.register(Challenge)
class ChallengeAdmin(admin.ModelAdmin):
    list_display = ('name', 'kinesiologo', 'challenge_type', 'duration', 'points', 'is_active')
    list_filter = ('challenge_type', 'is_active')


@admin.register(PatientChallenge)
class PatientChallengeAdmin(admin.ModelAdmin):
    list_display = ('patient', 'challenge', 'status', 'assigned_at', 'accepted_at')
    list_filter = ('status',)


@admin.register(Reward)
class RewardAdmin(admin.ModelAdmin):
    list_display = ('name', 'kinesiologo', 'points_cost', 'stock', 'is_active')


@admin.register(RewardClaim)
class RewardClaimAdmin(admin.ModelAdmin):
    list_display = ('patient', 'reward', 'status', 'claimed_at', 'points_spent')
    list_filter = ('status',)


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ('title', 'kinesiologo', 'category', 'created_at', 'is_active')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'recipient', 'notification_type', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read')


@admin.register(ChallengeSubmission)
class ChallengeSubmissionAdmin(admin.ModelAdmin):
    list_display = ('patient_challenge', 'status', 'points_awarded', 'submitted_at', 'reviewed_at')
    list_filter = ('status', 'points_awarded')
