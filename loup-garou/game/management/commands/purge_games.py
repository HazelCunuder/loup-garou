"""Efface les parties expirées (RGPD : durée de conservation limitée).

    python manage.py purge_games              # GAME_RETENTION_DAYS (30 par défaut)
    python manage.py purge_games --days 7
    python manage.py purge_games --dry-run    # compte sans rien effacer

La purge a aussi lieu à chaque nouvelle partie ; cette commande sert à la
lancer à la main ou depuis une tâche planifiée.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from game.services.retention import expired_games, purge_expired_games


class Command(BaseCommand):
    help = "Efface les parties sans activité depuis plus de GAME_RETENTION_DAYS jours."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None, help="Durée de conservation en jours.")
        parser.add_argument("--dry-run", action="store_true", help="Compte sans effacer.")

    def handle(self, *args, days, dry_run, **options):
        days = settings.GAME_RETENTION_DAYS if days is None else days
        if days < 0:
            self.stderr.write("--days doit être positif.")
            return
        if dry_run:
            count = expired_games(days).count()
            self.stdout.write(f"{count} partie(s) de plus de {days} jours seraient effacées.")
            return
        count = purge_expired_games(days)
        self.stdout.write(self.style.SUCCESS(f"{count} partie(s) de plus de {days} jours effacées."))
