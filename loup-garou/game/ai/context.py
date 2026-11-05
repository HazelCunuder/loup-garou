"""Mémoire d'un agent IA, construite à partir de sa vue autorisée.

L'IA ne reçoit que ``player_view(game, ia)`` : la même vue que celle servie à
un humain dans son rôle. Ce qu'elle n'a pas le droit de savoir n'entre jamais
dans son contexte (la directive du prompt n'est qu'une seconde protection).

Tout texte venant d'un joueur (messages, noms, pensée précédente) passe par
``escape_human_message`` : un joueur ne peut pas fermer une balise
``<chat_message>`` pour injecter des instructions.
"""

from game.models import Channel, MessageKind
from game.services.mistral_client import escape_human_message as esc

CHAT_WINDOW = 8
WOLF_CHAT_WINDOW = 6
ANNOUNCEMENT_WINDOW = 3

DEATH_CAUSES = {
    "WOLVES": "dévoré par les loups",
    "WITCH": "empoisonné",
    "VOTE": "éliminé par le village",
}


def _chat_block(messages):
    return "\n".join(
        f'<chat_message auteur="{esc(m["author_name"])}">{esc(m["content"])}</chat_message>'
        for m in messages
    )


def _private_block(view):
    me, private = view["me"], view["private"]
    lines = [f"Ton nom : {esc(me['name'])}. Ton rôle secret : {me['role_label']}."]
    for partner in private.get("wolf_partners", []):
        state = "vivant" if partner["is_alive"] else "mort"
        lines.append(f"Ton compère loup-garou : {esc(partner['name'])} ({state}).")
    if "inspections" in private:
        if private["inspections"]:
            visions = "; ".join(
                f"nuit {i['night']} : {esc(i['target_name'])} est {i['role_label']}"
                for i in private["inspections"]
            )
            lines.append(f"Tes visions : {visions}.")
        else:
            lines.append("Tu n'as encore sondé personne.")
    if "potions" in private:
        potions = private["potions"]
        lines.append(
            "Tes potions : vie "
            + ("disponible" if potions["life"] else "utilisée")
            + ", mort "
            + ("disponible" if potions["death"] else "utilisée")
            + "."
        )
        victim = private.get("wolf_victim")
        if victim:
            lines.append(f"Victime désignée par les loups cette nuit : {esc(victim['name'])}.")
    if private.get("last_thought"):
        lines.append(f"Ta pensée au tour précédent : {esc(private['last_thought'])}")
    return "\n".join(lines)


def _state_block(view):
    game = view["game"]
    alive = [esc(p["name"]) for p in view["players"] if p["is_alive"] and not p["is_me"]]
    dead = [
        f"{esc(p['name'])} ({p['role_label']}, {DEATH_CAUSES.get(p['death_cause'], 'mort')} "
        f"le jour {p['died_on_day']})"
        for p in view["players"]
        if not p["is_alive"]
    ]
    lines = [
        f"Jour {game['day']} · phase : {game['phase_label']}.",
        f"Autres joueurs vivants : {', '.join(alive) or 'aucun'}.",
        f"Morts : {'; '.join(dead) or 'aucun'}.",
    ]
    if not view["votes"]:
        lines.append("Votes : aucun vote n'a encore eu lieu.")
    else:
        by_day = {}
        for v in view["votes"]:
            target = esc(v["target_name"]) if v["target_name"] else "blanc"
            by_day.setdefault(v["day"], []).append(f"{esc(v['voter_name'])} → {target}")
        for day, votes in sorted(by_day.items()):
            lines.append(f"Votes du jour {day} : {', '.join(votes)}.")
    announcements = [
        m["content"] for m in view["messages"] if m["kind"] == MessageKind.ANNOUNCEMENT
    ][-ANNOUNCEMENT_WINDOW:]
    if announcements:
        lines.append("Dernières annonces du Maître du Jeu : " + " / ".join(esc(a) for a in announcements))
    return "\n".join(lines)


def build_context(view):
    """Texte du message utilisateur envoyé à Mistral pour le joueur de ``view``."""
    chats = [m for m in view["messages"] if m["kind"] == MessageKind.CHAT]
    public = [m for m in chats if m["channel"] == Channel.PUBLIC][-CHAT_WINDOW:]
    wolves = [m for m in chats if m["channel"] == Channel.WOLVES][-WOLF_CHAT_WINDOW:]

    sections = [
        f"<memoire_privee>\n{_private_block(view)}\n</memoire_privee>",
        f"<etat_partie>\n{_state_block(view)}\n</etat_partie>",
    ]
    if view["private"].get("wolf_partners") is not None:
        sections.append(f"<canal_loups>\n{_chat_block(wolves) or '(silence)'}\n</canal_loups>")
    sections.append(f"<discussion>\n{_chat_block(public) or '(personne n’a encore parlé)'}\n</discussion>")
    return "\n\n".join(sections)
