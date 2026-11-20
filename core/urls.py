from django.urls import path, register_converter
from . import views


class SafeIdConverter:
    """IDs de hasta 9 dígitos: un ID absurdo (ej. 99999999999999999999) da 404 y no error 500."""
    regex = '[0-9]{1,9}'

    def to_python(self, value):
        return int(value)

    def to_url(self, value):
        return str(value)


register_converter(SafeIdConverter, 'id')

urlpatterns = [
    # Auth
    path('', views.login_view, name='login'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('cuenta/cambiar-contrasena/', views.change_password, name='change_password'),
    path('entrega/<id:sub_pk>/foto/', views.proof_image, name='proof_image'),
    path('dashboard/', views.dashboard_redirect, name='dashboard'),

    # Panel Kinesiólogo
    path('kin/', views.kin_dashboard, name='kin_dashboard'),
    path('kin/notificaciones/', views.notifications, name='kin_notifications'),
    path('kin/estadisticas/', views.kin_stats, name='kin_stats'),

    # Pacientes CRUD
    path('kin/pacientes/', views.patient_list, name='patient_list'),
    path('kin/pacientes/agregar/', views.patient_add, name='patient_add'),
    path('kin/pacientes/<id:pk>/', views.patient_detail, name='patient_detail'),
    path('kin/pacientes/<id:pk>/editar/', views.patient_edit, name='patient_edit'),
    path('kin/pacientes/<id:pk>/eliminar/', views.patient_delete, name='patient_delete'),
    path('kin/pacientes/<id:pk>/progreso/', views.patient_progress_chart, name='patient_progress_chart'),
    path('kin/pacientes/<id:pk>/pdf/', views.export_patient_pdf, name='export_patient_pdf'),
    path('kin/pacientes/<id:patient_pk>/asignar-desafio/', views.assign_challenge, name='assign_challenge'),
    path('kin/desafio-paciente/<id:pc_pk>/verificar/', views.challenge_verify, name='challenge_verify'),
    path('kin/desafio-paciente/<id:pc_pk>/detalle/', views.patient_challenge_detail, name='patient_challenge_detail'),
    path('kin/desafio-paciente/<id:pc_pk>/quitar/', views.patient_challenge_remove, name='patient_challenge_remove'),
    path('kin/desafio-paciente/<id:pc_pk>/editar/', views.patient_challenge_edit, name='patient_challenge_edit'),

    # Chat
    path('kin/chat/', views.kin_chat_list, name='kin_chat_list'),
    path('kin/chat/<id:patient_pk>/', views.kin_chat, name='kin_chat'),
    path('paciente/chat/', views.patient_chat, name='patient_chat'),

    # Desafíos CRUD
    path('kin/desafios/', views.challenge_list, name='challenge_list'),
    path('kin/desafios/agregar/', views.challenge_add, name='challenge_add'),
    path('kin/desafios/<id:pk>/editar/', views.challenge_edit, name='challenge_edit'),
    path('kin/desafios/<id:pk>/eliminar/', views.challenge_delete, name='challenge_delete'),
    path('kin/desafios/<id:pk>/detalle/', views.challenge_detail, name='challenge_detail'),
    path('kin/desafios/<id:pk>/asignar/', views.challenge_assign_patients, name='challenge_assign_patients'),

    # Recompensas CRUD
    path('kin/recompensas/', views.reward_list, name='reward_list'),
    path('kin/recompensas/agregar/', views.reward_add, name='reward_add'),
    path('kin/recompensas/<id:pk>/editar/', views.reward_edit, name='reward_edit'),
    path('kin/recompensas/<id:pk>/eliminar/', views.reward_delete, name='reward_delete'),
    path('kin/reclamo/<id:claim_pk>/accion/', views.reward_claim_action, name='reward_claim_action'),

    # Videos CRUD
    path('kin/videos/', views.video_list, name='video_list'),
    path('kin/videos/agregar/', views.video_add, name='video_add'),
    path('kin/videos/<id:pk>/editar/', views.video_edit, name='video_edit'),
    path('kin/videos/<id:pk>/eliminar/', views.video_delete, name='video_delete'),

    # Panel Paciente
    path('paciente/', views.patient_dashboard, name='patient_dashboard'),
    path('paciente/desafios/', views.patient_challenges, name='patient_challenges'),
    path('paciente/desafio/<id:pc_pk>/aceptar/', views.accept_challenge, name='accept_challenge'),
    path('paciente/desafio/<id:pc_pk>/prueba/', views.submit_proof, name='submit_proof'),
    path('paciente/recompensas/', views.patient_rewards, name='patient_rewards'),
    path('paciente/recompensas/<id:pk>/reclamar/', views.claim_reward, name='claim_reward'),
    path('paciente/perfil/', views.patient_profile, name='patient_profile'),
    path('paciente/notificaciones/', views.patient_notifications, name='patient_notifications'),
    path('paciente/progreso/', views.my_progress_chart, name='my_progress_chart'),
]
