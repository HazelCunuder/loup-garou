import random

from django.test import SimpleTestCase

from game.ai.personas import PERSONAS, FallbackKind, get_persona
from game.engine.rules import AI_NAMES
from game.models import Personality


class PersonaCatalogTests(SimpleTestCase):
    def test_one_persona_per_personality(self):
        self.assertEqual(set(PERSONAS), set(Personality.values))
        for key, persona in PERSONAS.items():
            with self.subTest(key=key):
                self.assertEqual(persona.key, key)

    def test_labels_match_the_model_choices(self):
        for key, persona in PERSONAS.items():
            with self.subTest(key=key):
                self.assertEqual(persona.label, Personality(key).label)

    def test_every_text_field_is_filled(self):
        fields = ("traits", "speech_style", "vote_tendency", "as_wolf", "example_line")
        for persona in PERSONAS.values():
            for field in fields:
                with self.subTest(persona=persona.key, field=field):
                    self.assertTrue(getattr(persona, field).strip())

    def test_generation_settings_are_in_range(self):
        for persona in PERSONAS.values():
            with self.subTest(persona=persona.key):
                self.assertGreaterEqual(persona.temperature, 0.0)
                self.assertLessEqual(persona.temperature, 1.0)
                self.assertGreaterEqual(persona.abstain_rate, 0.0)
                self.assertLessEqual(persona.abstain_rate, 1.0)

    def test_strategist_is_the_coolest_and_impulsive_the_hottest(self):
        temperatures = {key: p.temperature for key, p in PERSONAS.items()}
        self.assertEqual(min(temperatures, key=temperatures.get), Personality.STRATEGE)
        self.assertEqual(max(temperatures, key=temperatures.get), Personality.IMPULSIF)

    def test_diplomat_always_abstains_on_fallback_vote(self):
        self.assertEqual(PERSONAS[Personality.DIPLOMATE].abstain_rate, 1.0)

    def test_get_persona_accepts_a_raw_value(self):
        self.assertIs(get_persona("CYNIQUE"), PERSONAS[Personality.CYNIQUE])

    def test_catalog_is_read_only(self):
        with self.assertRaises(TypeError):
            PERSONAS[Personality.CYNIQUE] = None
        with self.assertRaises(TypeError):
            PERSONAS[Personality.CYNIQUE].fallback_lines[FallbackKind.CHAT] = ()


class FallbackLineTests(SimpleTestCase):
    def test_every_persona_has_lines_for_every_situation(self):
        for persona in PERSONAS.values():
            for kind in FallbackKind:
                with self.subTest(persona=persona.key, kind=kind):
                    lines = persona.fallback_lines[kind]
                    self.assertGreaterEqual(len(lines), 3)
                    self.assertTrue(all(line.strip() for line in lines))

    def test_fallback_lines_are_unique_across_personas(self):
        seen = {}
        for persona in PERSONAS.values():
            for kind in FallbackKind:
                for line in persona.fallback_lines[kind]:
                    with self.subTest(line=line):
                        self.assertNotIn(line, seen, f"déjà utilisée par {seen.get(line)}")
                        seen[line] = persona.key

    def test_fallback_lines_contain_no_angle_brackets(self):
        for persona in PERSONAS.values():
            for kind in FallbackKind:
                for line in persona.fallback_lines[kind]:
                    self.assertNotIn("<", line)
                    self.assertNotIn(">", line)

    def test_fallback_line_is_drawn_from_the_right_list(self):
        persona = PERSONAS[Personality.IMPULSIF]
        rng = random.Random(0)
        for kind in FallbackKind:
            with self.subTest(kind=kind):
                self.assertIn(persona.fallback_line(kind, rng), persona.fallback_lines[kind])

    def test_fallback_line_accepts_a_raw_kind(self):
        persona = PERSONAS[Personality.CYNIQUE]
        self.assertIn(persona.fallback_line("vote"), persona.fallback_lines[FallbackKind.VOTE])

    def test_same_seed_gives_same_line(self):
        persona = PERSONAS[Personality.STRATEGE]
        self.assertEqual(
            persona.fallback_line(FallbackKind.CHAT, random.Random(3)),
            persona.fallback_line(FallbackKind.CHAT, random.Random(3)),
        )


class PromptBlockTests(SimpleTestCase):
    def test_prompt_blocks_are_all_different(self):
        blocks = [p.prompt_block() for p in PERSONAS.values()]
        self.assertEqual(len(set(blocks)), 6)

    def test_prompt_block_contains_the_whole_character(self):
        persona = PERSONAS[Personality.PARANOIAQUE]
        block = persona.prompt_block()
        for text in (
            persona.label,
            persona.traits,
            persona.speech_style,
            persona.vote_tendency,
            persona.as_wolf,
            persona.example_line,
        ):
            self.assertIn(text, block)

    def test_examples_never_name_a_real_player(self):
        # Un exemple qui cite un nom tiré pour une IA pousserait le modèle à
        # accuser ce joueur sans raison.
        for persona in PERSONAS.values():
            for name in AI_NAMES:
                with self.subTest(persona=persona.key, name=name):
                    self.assertNotIn(name, persona.prompt_block())

    def test_prompt_block_does_not_leak_fallback_lines(self):
        for persona in PERSONAS.values():
            block = persona.prompt_block()
            for kind in FallbackKind:
                for line in persona.fallback_lines[kind]:
                    self.assertNotIn(line, block)
