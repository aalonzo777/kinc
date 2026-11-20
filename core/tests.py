"""Tests de seguridad y validación de formatos de KINC.

Ejecutar con:   python manage.py test
"""
import io
import os
import tempfile

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .forms import (
    AddPatientForm, ChallengeForm, ChallengeSubmissionForm, ChatMessageForm,
    RewardForm, VideoForm,
)
from .models import (
    Challenge, ChallengeSubmission, Notification, Patient, PatientChallenge,
    PointHistory, Reward, RewardClaim, User, Video,
)
from .validators import extract_youtube_id, safe_int

MEDIA = tempfile.mkdtemp()
PASSWORD = 'Clave-Segura-2026'


def image_bytes(fmt='PNG'):
    buf = io.BytesIO()
    Image.new('RGB', (10, 10), 'red').save(buf, fmt)
    return buf.getvalue()


def png_file(name='foto.png'):
    return SimpleUploadedFile(name, image_bytes('PNG'), content_type='image/png')


def make_kin(email='kin@test.cl', username='kin'):
    return User.objects.create_user(
        username=username, email=email, password=PASSWORD,
        first_name='Carlos', last_name='Rojas', role='kinesiologo',
    )


def make_patient(kin, email='pac@test.cl', username='pac', must_change=False, points=0):
    user = User.objects.create_user(
        username=username, email=email, password=PASSWORD,
        first_name='Maria', last_name='Soto', role='paciente',
        must_change_password=must_change,
    )
    return Patient.objects.create(user=user, kinesiologo=kin, points=points)


# ─────────────────────────────────────────────────────────────
# FORMATOS: pacientes
# ─────────────────────────────────────────────────────────────
class PatientFormatTests(TestCase):
    VALID = dict(
        first_name='Juan', last_name="O'Higgins", email='Juan@Mail.cl',
        phone='+56 9 1234 5678', age=35, password='Contraseña-Larga-91',
    )

    def test_valid_data_is_normalized(self):
        form = AddPatientForm(self.VALID)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['email'], 'juan@mail.cl')
        self.assertEqual(form.cleaned_data['phone'], '+56912345678')

    def test_invalid_values_are_rejected(self):
        cases = [
            ('first_name', ''), ('first_name', 'J'), ('first_name', 'Juan123'),
            ('first_name', '<script>'), ('first_name', 'x' * 51),
            ('last_name', 'Pérez; DROP TABLE'), ('last_name', '1234'),
            ('email', 'no-es-correo'), ('email', 'a@b'), ('email', ''),
            ('phone', 'abc'), ('phone', '123'), ('phone', '+56 9 12'), ('phone', '1' * 30),
            ('age', 0), ('age', 121), ('age', -5), ('age', 'abc'),
            ('password', '1234'), ('password', 'corta'), ('password', '12345678'),
            ('password', 'a' * 129), ('password', ''),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                form = AddPatientForm(dict(self.VALID, **{field: value}))
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_duplicate_email_is_rejected_ignoring_case(self):
        make_kin(email='dup@test.cl', username='dup')
        form = AddPatientForm(dict(self.VALID, email='DUP@test.cl'))
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_email_is_unique_in_database(self):
        make_kin()
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username='otro', email='KIN@test.cl', password=PASSWORD)


# ─────────────────────────────────────────────────────────────
# FORMATOS: desafíos, recompensas, videos, chat
# ─────────────────────────────────────────────────────────────
class ContentFormatTests(TestCase):
    def setUp(self):
        self.kin = make_kin()
        self.other = make_kin(email='otro@test.cl', username='otro')

    def challenge_data(self, **extra):
        data = dict(name='Caminar', description='30 minutos', challenge_type='diario',
                    duration=10, points=100, video='')
        data.update(extra)
        return data

    def test_valid_challenge(self):
        self.assertTrue(ChallengeForm(self.challenge_data(), user=self.kin).is_valid())
        self.assertTrue(ChallengeForm(self.challenge_data(challenge_type='semanal', duration=52), user=self.kin).is_valid())

    def test_invalid_challenge_values(self):
        cases = [
            ('duration', 0, {}), ('duration', 'abc', {}), ('duration', 366, {}),
            ('duration', 53, {'challenge_type': 'semanal'}),
            ('duration', 25, {'challenge_type': 'mensual'}),
            ('points', 0, {}), ('points', 10001, {}), ('points', 'mucho', {}),
            ('name', 'x' * 101, {}), ('name', '', {}),
            ('description', 'x' * 501, {}),
            ('challenge_type', 'anual', {}),
        ]
        for field, value, extra in cases:
            with self.subTest(field=field, value=value, extra=extra):
                form = ChallengeForm(self.challenge_data(**{field: value}, **extra), user=self.kin)
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_cannot_attach_video_of_another_kinesiologist(self):
        foreign = Video.objects.create(
            kinesiologo=self.other, title='Ajeno', category='x',
            youtube_url='https://youtu.be/dQw4w9WgXcQ')
        form = ChallengeForm(self.challenge_data(video=foreign.pk), user=self.kin)
        self.assertFalse(form.is_valid())
        self.assertIn('video', form.errors)

    def test_reward_limits(self):
        base = dict(name='Premio', description='desc', points_cost=10, stock=0)
        self.assertTrue(RewardForm(base).is_valid())
        for field, value in [('points_cost', 0), ('points_cost', 100001), ('stock', -1),
                             ('stock', 10001), ('name', 'x' * 101), ('stock', 'abc')]:
            with self.subTest(field=field, value=value):
                form = RewardForm(dict(base, **{field: value}))
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_youtube_links(self):
        base = dict(title='Video', description='', category='rehabilitacion')
        valid = ['https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'www.youtube.com/watch?v=dQw4w9WgXcQ',
                 'youtube.com/watch?v=dQw4w9WgXcQ', 'https://youtu.be/dQw4w9WgXcQ',
                 'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s']
        invalid = ['https://vimeo.com/123456', 'javascript:alert(1)',
                   'https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ',
                   'https://www.youtube.com/watch?v=corto', 'ftp://youtube.com/watch?v=dQw4w9WgXcQ',
                   'hyoutube.com/watch?v=dQw4w9WgXcQ']
        for url in valid:
            with self.subTest(url=url):
                form = VideoForm(dict(base, youtube_url=url))
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data['youtube_url'], 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        for url in invalid:
            with self.subTest(url=url):
                form = VideoForm(dict(base, youtube_url=url))
                self.assertFalse(form.is_valid())
                self.assertIn('youtube_url', form.errors)
        self.assertFalse(VideoForm(dict(base, youtube_url=valid[0], title='x' * 101)).is_valid())
        self.assertFalse(VideoForm(dict(base, youtube_url=valid[0], category='inventada')).is_valid())

    def test_chat_message_limits(self):
        self.assertTrue(ChatMessageForm({'body': 'Hola'}).is_valid())
        self.assertTrue(ChatMessageForm({'body': 'a' * 1000}).is_valid())
        for body in ['', '   ', 'a' * 1001]:
            with self.subTest(length=len(body)):
                self.assertFalse(ChatMessageForm({'body': body}).is_valid())

    def test_helpers(self):
        self.assertEqual(extract_youtube_id('https://youtu.be/dQw4w9WgXcQ'), 'dQw4w9WgXcQ')
        self.assertIsNone(extract_youtube_id('https://evil.com/watch?v=dQw4w9WgXcQ'))
        self.assertEqual(safe_int('12'), 12)
        for bad in ['abc', '', None, '1; DROP TABLE', '99999999999999999999', '-3', '0']:
            self.assertIsNone(safe_int(bad))


# ─────────────────────────────────────────────────────────────
# FORMATOS: foto de la entrega
# ─────────────────────────────────────────────────────────────
@override_settings(MEDIA_ROOT=MEDIA)
class SubmissionFormTests(TestCase):
    def test_valid_png(self):
        form = ChallengeSubmissionForm({'proof_message': 'Listo'}, {'proof_photo': png_file()})
        self.assertTrue(form.is_valid(), form.errors)

    def test_photo_is_required(self):
        self.assertFalse(ChallengeSubmissionForm({'proof_message': 'sin foto'}, {}).is_valid())

    def test_fake_image_is_rejected(self):
        fake = SimpleUploadedFile('virus.png', b'esto no es una imagen', content_type='image/png')
        self.assertFalse(ChallengeSubmissionForm({}, {'proof_photo': fake}).is_valid())

    def test_gif_is_rejected(self):
        gif = SimpleUploadedFile('a.gif', image_bytes('GIF'), content_type='image/gif')
        self.assertFalse(ChallengeSubmissionForm({}, {'proof_photo': gif}).is_valid())

    @override_settings(MAX_UPLOAD_SIZE=40)
    def test_heavy_photo_is_rejected(self):
        form = ChallengeSubmissionForm({}, {'proof_photo': png_file()})
        self.assertFalse(form.is_valid())
        self.assertIn('proof_photo', form.errors)

    def test_message_too_long(self):
        form = ChallengeSubmissionForm({'proof_message': 'x' * 501}, {'proof_photo': png_file()})
        self.assertFalse(form.is_valid())
        self.assertIn('proof_message', form.errors)


# ─────────────────────────────────────────────────────────────
# ACCESO, PERMISOS, INYECCIONES
# ─────────────────────────────────────────────────────────────
@override_settings(MEDIA_ROOT=MEDIA)
class AccessControlTests(TestCase):
    def setUp(self):
        cache.clear()
        self.kin = make_kin()
        self.kin2 = make_kin(email='kin2@test.cl', username='kin2')
        self.patient = make_patient(self.kin)
        self.patient2 = make_patient(self.kin, email='pac2@test.cl', username='pac2')
        self.challenge = Challenge.objects.create(
            kinesiologo=self.kin, name='Caminar', description='d',
            challenge_type='diario', duration=7, points=50)
        self.pc = PatientChallenge.objects.create(
            patient=self.patient, challenge=self.challenge, status='activo')
        self.sub = ChallengeSubmission.objects.create(
            patient_challenge=self.pc, proof_photo=png_file())

    def login(self, user):
        self.assertTrue(self.client.login(username=user.username, password=PASSWORD))

    def fetch_photo(self):
        return self.client.get(reverse('proof_image', args=[self.sub.pk]))

    def test_photo_requires_login(self):
        self.assertEqual(self.fetch_photo().status_code, 302)

    def test_photo_visible_to_owner_and_own_kinesiologist(self):
        for user in (self.patient.user, self.kin):
            with self.subTest(user=user.username):
                self.client.logout()
                self.login(user)
                response = self.fetch_photo()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'], 'image/png')
                self.assertIn('no-store', response['Cache-Control'])
                response.close()

    def test_photo_hidden_from_other_users(self):
        for user in (self.kin2, self.patient2.user):
            with self.subTest(user=user.username):
                self.client.logout()
                self.login(user)
                self.assertEqual(self.fetch_photo().status_code, 404)

    def test_media_folder_is_not_public(self):
        self.login(self.kin)
        self.assertEqual(self.client.get('/media/' + self.sub.proof_photo.name).status_code, 404)

    def test_logout_requires_post(self):
        self.login(self.kin)
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        self.assertEqual(self.client.post(reverse('logout')).status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_roles_are_separated(self):
        self.login(self.patient.user)
        self.assertEqual(self.client.get(reverse('kin_dashboard')).status_code, 302)
        self.client.logout()
        self.login(self.kin)
        self.assertEqual(self.client.get(reverse('patient_dashboard')).status_code, 302)

    def test_other_kinesiologist_cannot_access_data(self):
        self.login(self.kin2)
        self.assertEqual(self.client.get(reverse('patient_detail', args=[self.patient.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('patient_challenge_detail', args=[self.pc.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('kin_chat', args=[self.patient.pk])).status_code, 404)
        response = self.client.post(reverse('challenge_verify', args=[self.pc.pk]),
                                    {'submission_pk': self.sub.pk, 'action': 'approve'})
        self.assertEqual(response.status_code, 404)

    def test_absurd_ids_give_404_not_500(self):
        self.login(self.kin)
        self.assertEqual(self.client.get('/kin/pacientes/99999999999999999999/').status_code, 404)

    def test_sql_injection_in_search_is_harmless(self):
        self.login(self.kin)
        for payload in ["' OR 1=1 --", "'; DROP TABLE core_user; --", '" OR ""="']:
            with self.subTest(payload=payload):
                response = self.client.get(reverse('patient_list'), {'q': payload})
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'pac@test.cl')
        self.assertTrue(User.objects.filter(username='pac').exists())
        long_query = self.client.get(reverse('patient_list'), {'q': 'a' * 101})
        self.assertEqual(long_query.status_code, 200)

    def test_garbage_ids_in_posts_do_not_crash(self):
        self.login(self.kin)
        r1 = self.client.post(reverse('assign_challenge', args=[self.patient.pk]), {'challenge_id': 'abc'})
        r2 = self.client.post(reverse('challenge_assign_patients', args=[self.challenge.pk]),
                              {'patient_ids': ['abc', '1; DROP TABLE x', '99999999999999999999']})
        r3 = self.client.post(reverse('challenge_verify', args=[self.pc.pk]),
                              {'submission_pk': 'abc', 'action': 'hack'})
        self.assertEqual((r1.status_code, r2.status_code, r3.status_code), (302, 302, 302))

    def _video(self):
        return Video.objects.create(kinesiologo=self.kin, title='V', category='c',
                                    youtube_url='https://youtu.be/dQw4w9WgXcQ')

    def test_chat_escapes_html(self):
        self.login(self.patient.user)
        self.client.post(reverse('patient_chat'), {'body': '<script>alert(1)</script>'})
        self.client.logout()
        self.login(self.kin)
        response = self.client.get(reverse('kin_chat', args=[self.patient.pk]))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;')

    def test_patient_detail_challenges_are_clickable(self):
        self.login(self.kin)
        response = self.client.get(reverse('patient_detail', args=[self.patient.pk]))
        self.assertContains(response, reverse('patient_challenge_detail', args=[self.pc.pk]))

    def test_deleting_submission_removes_photo_file(self):
        path = self.sub.proof_photo.path
        self.assertTrue(os.path.exists(path))
        self.sub.delete()
        self.assertFalse(os.path.exists(path))


# ─────────────────────────────────────────────────────────────
# LOGIN Y CONTRASEÑAS
# ─────────────────────────────────────────────────────────────
class LoginSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.kin = make_kin()
        self.patient = make_patient(self.kin, must_change=True)

    def post_login(self, email, password):
        return self.client.post(reverse('login'), {'username': email, 'password': password})

    def test_brute_force_lockout(self):
        for _ in range(5):
            self.post_login('pac@test.cl', 'incorrecta')
        self.post_login('pac@test.cl', PASSWORD)  # correcta, pero ya está bloqueado
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_ignores_email_case(self):
        response = self.post_login('PAC@TEST.CL', PASSWORD)
        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_wrong_credentials_and_malformed_input(self):
        for email, password in [('nadie@test.cl', 'x'), ('no-es-correo', 'x'), ('', ''), ('a@b.cl', 'p' * 200)]:
            with self.subTest(email=email):
                self.assertEqual(self.post_login(email, password).status_code, 200)
                self.assertNotIn('_auth_user_id', self.client.session)

    def test_temporary_password_must_be_changed(self):
        self.post_login('pac@test.cl', PASSWORD)
        response = self.client.get(reverse('patient_dashboard'))
        self.assertRedirects(response, reverse('change_password'), fetch_redirect_response=False)

        weak = self.client.post(reverse('change_password'), {
            'old_password': PASSWORD, 'new_password1': '12345678', 'new_password2': '12345678'})
        self.assertEqual(weak.status_code, 200)
        self.patient.user.refresh_from_db()
        self.assertTrue(self.patient.user.must_change_password)

        good = self.client.post(reverse('change_password'), {
            'old_password': PASSWORD, 'new_password1': 'Otra-Clave-Larga-77',
            'new_password2': 'Otra-Clave-Larga-77'})
        self.assertEqual(good.status_code, 302)
        self.patient.user.refresh_from_db()
        self.assertFalse(self.patient.user.must_change_password)
        self.assertEqual(self.client.get(reverse('patient_dashboard')).status_code, 200)


# ─────────────────────────────────────────────────────────────
# REGLAS DE NEGOCIO (puntos, stock, entregas)
# ─────────────────────────────────────────────────────────────
@override_settings(MEDIA_ROOT=MEDIA)
class BusinessRuleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.kin = make_kin()
        self.patient = make_patient(self.kin, points=20)
        self.challenge = Challenge.objects.create(
            kinesiologo=self.kin, name='Caminar', description='d',
            challenge_type='diario', duration=7, points=50)
        self.pc = PatientChallenge.objects.create(patient=self.patient, challenge=self.challenge, status='activo')

    def login(self, user):
        self.assertTrue(self.client.login(username=user.username, password=PASSWORD))

    def test_points_are_awarded_only_once(self):
        sub = ChallengeSubmission.objects.create(patient_challenge=self.pc, proof_photo=png_file())
        self.login(self.kin)
        data = {'submission_pk': sub.pk, 'action': 'approve', 'feedback': 'Bien'}
        self.client.post(reverse('challenge_verify', args=[self.pc.pk]), data)
        self.client.post(reverse('challenge_verify', args=[self.pc.pk]), data)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.points, 20 + 50)

    def test_cannot_claim_without_enough_points(self):
        reward = Reward.objects.create(kinesiologo=self.kin, name='Premio', description='d', points_cost=100, stock=3)
        self.login(self.patient.user)
        self.client.post(reverse('claim_reward', args=[reward.pk]))
        reward.refresh_from_db(); self.patient.refresh_from_db()
        self.assertEqual((reward.stock, self.patient.points, RewardClaim.objects.count()), (3, 20, 0))

    def test_claim_and_stock_never_negative(self):
        reward = Reward.objects.create(kinesiologo=self.kin, name='Premio', description='d', points_cost=10, stock=1)
        self.login(self.patient.user)
        self.client.post(reverse('claim_reward', args=[reward.pk]))
        self.client.post(reverse('claim_reward', args=[reward.pk]))  # doble clic
        reward.refresh_from_db(); self.patient.refresh_from_db()
        self.assertEqual((reward.stock, self.patient.points, RewardClaim.objects.count()), (0, 10, 1))

    def test_cannot_submit_before_accepting_challenge(self):
        self.pc.status = 'pendiente'
        self.pc.save()
        self.login(self.patient.user)
        self.client.post(reverse('submit_proof', args=[self.pc.pk]), {'proof_photo': png_file()})
        self.assertEqual(ChallengeSubmission.objects.count(), 0)

    def test_daily_challenge_allows_one_submission_per_day(self):
        self.login(self.patient.user)
        url = reverse('submit_proof', args=[self.pc.pk])
        self.client.post(url, {'proof_photo': png_file(), 'proof_message': 'hoy'})
        self.client.post(url, {'proof_photo': png_file('otra.png')})
        self.assertEqual(ChallengeSubmission.objects.count(), 1)

    def test_submission_without_photo_is_not_saved(self):
        self.login(self.patient.user)
        self.client.post(reverse('submit_proof', args=[self.pc.pk]), {'proof_message': 'sin foto'})
        self.assertEqual(ChallengeSubmission.objects.count(), 0)


# ─────────────────────────────────────────────────────────────
# MEJORAS v6 (los 9 puntos pedidos)
# ─────────────────────────────────────────────────────────────
@override_settings(MEDIA_ROOT=MEDIA)
class FeatureTests(TestCase):
    def setUp(self):
        cache.clear()
        self.kin = make_kin()
        self.kin2 = make_kin(email='kin2@test.cl', username='kin2')
        self.patient = make_patient(self.kin, points=100)
        self.patient2 = make_patient(self.kin, email='pac2@test.cl', username='pac2')
        self.challenge = Challenge.objects.create(
            kinesiologo=self.kin, name='Caminar', description='d',
            challenge_type='diario', duration=7, points=50)
        self.pc = PatientChallenge.objects.create(
            patient=self.patient, challenge=self.challenge, status='activo')
        self.sub = ChallengeSubmission.objects.create(patient_challenge=self.pc, proof_photo=png_file())

    def login(self, user):
        self.client.logout()
        self.assertTrue(self.client.login(username=user.username, password=PASSWORD))

    def test_1_rejected_submission_is_logged_with_zero_points(self):
        self.login(self.kin)
        self.client.post(reverse('challenge_verify', args=[self.pc.pk]),
                         {'submission_pk': self.sub.pk, 'action': 'reject', 'feedback': ''})
        entry = PointHistory.objects.get(patient=self.patient)
        self.assertTrue(entry.reason.startswith('Entrega rechazada'))
        self.assertEqual(entry.points, 0)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.points, 100)

    def test_1_rejected_reward_refunds_with_clear_text(self):
        reward = Reward.objects.create(kinesiologo=self.kin, name='Premio', description='d', points_cost=30, stock=2)
        claim = RewardClaim.objects.create(patient=self.patient, reward=reward, points_spent=30)
        self.login(self.kin)
        self.client.post(reverse('reward_claim_action', args=[claim.pk]), {'action': 'reject'})
        entry = PointHistory.objects.get(patient=self.patient)
        self.assertTrue(entry.reason.startswith('Recompensa rechazada'))
        self.assertEqual(entry.points, 30)
        reward.refresh_from_db(); self.patient.refresh_from_db()
        self.assertEqual((reward.stock, self.patient.points), (3, 130))

    def test_2_videos_in_kinesiologist_menu_only(self):
        self.login(self.kin)
        self.assertContains(self.client.get(reverse('kin_dashboard')), reverse('video_list'))
        self.login(self.patient.user)
        self.assertNotContains(self.client.get(reverse('patient_dashboard')), reverse('video_list'))

    def test_3_video_category_is_a_fixed_list(self):
        base = dict(title='V', youtube_url='youtube.com/watch?v=dQw4w9WgXcQ', description='')
        self.assertTrue(VideoForm(dict(base, category='postura')).is_valid())
        self.assertFalse(VideoForm(dict(base, category='inventada')).is_valid())
        self.assertFalse(VideoForm(dict(base, category='')).is_valid())

    def test_4_back_button_only_outside_dashboards(self):
        self.login(self.kin)
        self.assertNotContains(self.client.get(reverse('kin_dashboard')), 'id="kincBack"')
        self.assertContains(self.client.get(reverse('patient_list')), 'id="kincBack"')

    def test_5_patient_detail_links_to_progress_chat_and_pdf(self):
        self.login(self.kin)
        response = self.client.get(reverse('patient_detail', args=[self.patient.pk]))
        for name in ('patient_progress_chart', 'kin_chat', 'export_patient_pdf'):
            self.assertContains(response, reverse(name, args=[self.patient.pk]))
        self.assertEqual(self.client.get(reverse('patient_progress_chart', args=[self.patient.pk])).status_code, 200)

    def test_6_red_dots_appear_only_when_there_is_news(self):
        self.login(self.kin)  # hay una entrega pendiente de revisar
        self.assertContains(self.client.get(reverse('kin_dashboard')), 'class="nav-dot"')
        ChallengeSubmission.objects.all().update(status='aprobado')
        self.assertNotContains(self.client.get(reverse('kin_dashboard')), 'class="nav-dot"')
        self.login(self.patient.user)  # sin mensajes, sin notificaciones, desafío ya aceptado
        self.assertNotContains(self.client.get(reverse('patient_dashboard')), 'class="nav-dot"')
        PatientChallenge.objects.filter(pk=self.pc.pk).update(status='pendiente')
        self.assertContains(self.client.get(reverse('patient_dashboard')), 'class="nav-dot"')

    def test_6_chat_dot_disappears_after_reading(self):
        self.login(self.patient.user)
        self.client.post(reverse('patient_chat'), {'body': 'Hola'})
        self.login(self.kin)
        self.assertContains(self.client.get(reverse('kin_dashboard')), 'class="nav-dot"')
        self.client.get(reverse('kin_chat', args=[self.patient.pk]))   # lo lee
        ChallengeSubmission.objects.all().update(status='aprobado')
        self.assertNotContains(self.client.get(reverse('kin_dashboard')), 'class="nav-dot"')

    def test_7_youtube_link_formats_are_normalized(self):
        for raw in ('https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'www.youtube.com/watch?v=dQw4w9WgXcQ',
                    'youtube.com/watch?v=dQw4w9WgXcQ'):
            with self.subTest(raw=raw):
                form = VideoForm(dict(title='V', youtube_url=raw, description='', category='otro'))
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data['youtube_url'], 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')

    def test_8_videos_are_attached_to_challenges_not_patients(self):
        video = Video.objects.create(kinesiologo=self.kin, title='Mi video', category='otro',
                                     youtube_url='https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        self.challenge.video = video
        self.challenge.save()
        self.login(self.kin)
        response = self.client.get(reverse('video_list'))
        self.assertContains(response, 'Mi video')
        self.assertNotContains(response, 'Asignar a pacientes')
        self.assertEqual(self.client.get('/kin/videos/%d/asignar/' % video.pk).status_code, 404)
        self.login(self.patient.user)
        self.assertEqual(self.client.get('/paciente/videos/').status_code, 404)
        self.assertContains(self.client.get(reverse('patient_challenges')), 'Mi video')

    def test_9_challenge_detail_page_and_assignment(self):
        self.login(self.kin)
        response = self.client.get(reverse('challenge_detail', args=[self.challenge.pk]))
        self.assertContains(response, 'Maria Soto')
        self.client.post(reverse('challenge_assign_patients', args=[self.challenge.pk]),
                         {'patient_ids': [self.patient2.pk, 'abc']})
        self.assertTrue(PatientChallenge.objects.filter(patient=self.patient2, challenge=self.challenge).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.patient2.user).exists())

    def test_9_challenge_detail_is_private_to_its_owner(self):
        self.login(self.kin2)
        self.assertEqual(self.client.get(reverse('challenge_detail', args=[self.challenge.pk])).status_code, 404)
        foreign_patient = make_patient(self.kin2, email='x@test.cl', username='x')
        r = self.client.post(reverse('challenge_assign_patients', args=[self.challenge.pk]),
                             {'patient_ids': [foreign_patient.pk]})
        self.assertEqual(r.status_code, 404)


# ─────────────────────────────────────────────────────────────
# DESPLIEGUE EN VERCEL
# ─────────────────────────────────────────────────────────────
@override_settings(MEDIA_ROOT=MEDIA)
class DeploymentTests(TestCase):
    def test_upload_limit_fits_vercel_request_limit(self):
        from django.conf import settings
        self.assertLessEqual(settings.MAX_UPLOAD_SIZE, int(4.5 * 1024 * 1024))

    def test_missing_photo_file_gives_404_not_500(self):
        kin = make_kin()
        patient = make_patient(kin)
        challenge = Challenge.objects.create(kinesiologo=kin, name='C', description='d',
                                             challenge_type='diario', duration=1, points=10)
        pc = PatientChallenge.objects.create(patient=patient, challenge=challenge, status='activo')
        sub = ChallengeSubmission.objects.create(patient_challenge=pc, proof_photo=png_file())
        os.remove(sub.proof_photo.path)          # el archivo desaparece (disco o bucket)
        self.client.login(username=kin.username, password=PASSWORD)
        self.assertEqual(self.client.get(reverse('proof_image', args=[sub.pk])).status_code, 404)
