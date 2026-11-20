from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from core.models import User, Patient, Challenge, Reward, Video


class Command(BaseCommand):
    help = 'Crea datos de prueba iniciales para KINC'

    def handle(self, *args, **kwargs):
        if not settings.DEBUG:
            raise CommandError('seed_data crea usuarios con contraseñas conocidas: solo se permite con KINC_DEBUG=True.')
        self.stdout.write(self.style.MIGRATE_HEADING('\n🏥 Creando datos iniciales de KINC...\n'))

        # ── KINESIÓLOGO ──────────────────────────────────────
        if not User.objects.filter(email='kin@kinc.cl').exists():
            kin = User.objects.create_user(
                username='kinesiologo',
                email='kin@kinc.cl',
                password='kinc1234',
                first_name='Carlos',
                last_name='Rodríguez',
                role='kinesiologo',
                phone='+56991234567',
            )
            self.stdout.write(self.style.SUCCESS('✅ Kinesiólogo creado: kin@kinc.cl / kinc1234'))
        else:
            kin = User.objects.get(email='kin@kinc.cl')
            self.stdout.write('⚠️  Kinesiólogo ya existe.')

        # ── PACIENTE ─────────────────────────────────────────
        if not User.objects.filter(email='paciente@kinc.cl').exists():
            pac_user = User.objects.create_user(
                username='paciente1',
                email='paciente@kinc.cl',
                password='kinc1234',
                first_name='María',
                last_name='González',
                role='paciente',
                phone='+56987654321',
                age=35,
            )
            Patient.objects.create(
                user=pac_user,
                kinesiologo=kin,
                notes='Paciente con dolor lumbar crónico. Inicio de rehabilitación.',
                points=150,
                last_session=timezone.now(),
            )
            self.stdout.write(self.style.SUCCESS('✅ Paciente creado: paciente@kinc.cl / kinc1234'))
        else:
            self.stdout.write('⚠️  Paciente ya existe.')

        # ── DESAFÍOS ─────────────────────────────────────────
        challenges_data = [
            {
                'name': 'Caminata diaria',
                'description': 'Caminar al menos 30 minutos al día en un ritmo moderado.',
                'challenge_type': 'diario',
                'duration': 7,
                'points': 100,
            },
            {
                'name': 'Ejercicios de fortalecimiento lumbar',
                'description': 'Realizar la rutina de 5 ejercicios lumbares indicados, 3 series de 10 repeticiones.',
                'challenge_type': 'semanal',
                'duration': 4,
                'points': 250,
            },
            {
                'name': 'Estiramiento matutino',
                'description': 'Realizar 10 minutos de estiramiento cada mañana al despertar.',
                'challenge_type': 'diario',
                'duration': 14,
                'points': 150,
            },
        ]
        for ch_data in challenges_data:
            ch, created = Challenge.objects.get_or_create(
                name=ch_data['name'],
                kinesiologo=kin,
                defaults=ch_data,
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'✅ Desafío creado: {ch.name}'))

        # ── RECOMPENSAS ───────────────────────────────────────
        rewards_data = [
            {
                'name': 'Sesión de masaje gratuita',
                'description': 'Una sesión de 30 minutos de masaje terapéutico sin costo.',
                'points_cost': 500,
                'stock': 5,
            },
            {
                'name': 'Descuento 20% próxima sesión',
                'description': '20% de descuento en tu próxima sesión de kinesiología.',
                'points_cost': 300,
                'stock': 10,
            },
            {
                'name': 'Guía de ejercicios personalizada',
                'description': 'PDF con rutina personalizada según tu condición.',
                'points_cost': 200,
                'stock': 20,
            },
        ]
        for rw_data in rewards_data:
            rw, created = Reward.objects.get_or_create(
                name=rw_data['name'],
                kinesiologo=kin,
                defaults=rw_data,
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'✅ Recompensa creada: {rw.name}'))

        # ── VIDEOS ────────────────────────────────────────────
        videos_data = [
            {
                'title': 'Ejercicios para el dolor lumbar',
                'youtube_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                'description': 'Rutina completa de 5 ejercicios para aliviar el dolor de espalda baja.',
                'category': 'rehabilitacion',
            },
            {
                'title': 'Estiramiento de cadena posterior',
                'youtube_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                'description': 'Secuencia de estiramientos para la cadena muscular posterior.',
                'category': 'estiramiento',
            },
        ]
        for vd_data in videos_data:
            vd, created = Video.objects.get_or_create(
                title=vd_data['title'],
                kinesiologo=kin,
                defaults=vd_data,
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'✅ Video creado: {vd.title}'))

        self.stdout.write(self.style.SUCCESS('\n🎉 ¡Datos iniciales creados exitosamente!\n'))
        for ch_name, vid_title in [
            ('Ejercicios de fortalecimiento lumbar', 'Ejercicios para el dolor lumbar'),
            ('Estiramiento matutino', 'Estiramiento de cadena posterior'),
        ]:
            Challenge.objects.filter(name=ch_name, kinesiologo=kin, video__isnull=True).update(
                video=Video.objects.get(title=vid_title, kinesiologo=kin))

        self.stdout.write(self.style.WARNING('Credenciales de acceso:'))
        self.stdout.write('  Kinesiólogo → kin@kinc.cl       / kinc1234')
        self.stdout.write('  Paciente    → paciente@kinc.cl  / kinc1234\n')
