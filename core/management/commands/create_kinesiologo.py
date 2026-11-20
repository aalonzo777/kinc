from getpass import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from core.models import User
from core.validators import validate_person_name


class Command(BaseCommand):
    help = 'Crea un usuario kinesiólogo (la contraseña se pide por teclado y se valida).'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument('--nombre', required=True)
        parser.add_argument('--apellido', required=True)

    def handle(self, *args, **options):
        email = options['email'].strip().lower()
        try:
            for value in (options['nombre'], options['apellido']):
                validate_person_name(value)
        except ValidationError as exc:
            raise CommandError('; '.join(exc.messages))
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError('Ya existe un usuario con ese correo.')

        password = getpass('Contraseña: ')
        if password != getpass('Repite la contraseña: '):
            raise CommandError('Las contraseñas no coinciden.')
        user = User(username=email[:150], email=email,
                    first_name=options['nombre'].strip(), last_name=options['apellido'].strip(),
                    role='kinesiologo')
        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            raise CommandError(' '.join(exc.messages))
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f'Kinesiólogo creado: {email}'))
