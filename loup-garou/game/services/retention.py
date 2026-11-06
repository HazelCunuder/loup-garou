"""Durée de conservation des parties (RGPD, art. 5.1.e).

Une partie est effacée ``GAME_RETENTION_DAYS`` jours après sa dernière
activité. Joueurs, messages, votes, actions de nuit et journaux IA sont
supprimés en cascade avec elle.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db.models.functions import Greatest
from django.utils import timezone

from game.models import Game


def expired_games(days=None, now=None):
    """Parties sans activité depuis plus de ``days`` jours."""
    days = settings.GAME_RETENTION_DAYS if days is None else days
    cutoff = (now or timezone.now()) - timedelta(days=days)
    # Les transitions passent par update(), qui ne touche pas updated_at :
    # phase_started_at date le dernier changement de phase.
    return Game.objects.annotate(
        last_activity=Greatest("updated_at", "phase_started_at")
    ).filter(last_activity__lt=cutoff)


def purge_expired_games(days=None, now=None):
    """Efface les parties expirées et les sessions périmées ; renvoie le nombre de parties."""
    ids = list(expired_games(days, now).values_list("pk", flat=True))
    if ids:
        Game.objects.filter(pk__in=ids).delete()
    Session.objects.filter(expire_date__lt=now or timezone.now()).delete()
    return len(ids)
