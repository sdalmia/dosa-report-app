"""Today's insight cards use the latest sales week and plain wording."""

import unittest

from app import create_app
from app.chat.licences import home_card
from app.chat.wizard_a import growth_text, trend_cards

_EXCLUDED = ("rosedale", "faridabad", "chattarpur", "gk1", "gk 1")


class InsightCardTests(unittest.TestCase):
    def test_cards_use_the_week_ending_12_nov_and_plain_wording(self):
        cards = trend_cards()
        self.assertTrue(cards)
        self.assertLessEqual(len(cards), 3)
        first = cards[0]
        self.assertNotIn("Trend", first["title"])
        self.assertNotIn("Trend", first["line"])
        self.assertNotIn("-₹", first["line"])
        self.assertNotIn("(02/", first["title"])
        self.assertNotIn("Dosa Coffee", first["title"])
        self.assertIn("6–12 Nov", first["line"])
        self.assertIn("30 Oct–5 Nov", first["line"])
        self.assertIn("9, 10, 11 Nov not in the file", first["line"])
        self.assertIn("Sales", first["line"])
        self.assertTrue(first["question"].startswith("Why are "))
        blob = " ".join(card["title"] for card in cards).casefold()
        for name in _EXCLUDED:
            self.assertNotIn(name, blob)

    def test_growth_uses_the_same_window(self):
        text = growth_text()
        self.assertIn("6–12 Nov vs 30 Oct–5 Nov", text)
        self.assertNotIn("2026-11-02–2026-11-08", text)
        self.assertIn("down ₹", text)
        self.assertNotIn("-₹", text)

    def test_licence_card_wording(self):
        card = home_card("owner")
        self.assertEqual(card["title"], "Licences")
        self.assertEqual(card["line"], "9 licences expired, 3 expire in 30 days")

    def test_home_renders_tappable_cards(self):
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user"] = {"name": "Siddhant", "email": "siddhant@dalgreenfoods.com"}
            sess["user_email"] = "siddhant@dalgreenfoods.com"
        html = client.get("/dashboard").get_data(as_text=True)
        self.assertIn('class="cc-today"', html)
        self.assertIn('class="cc-insight"', html)
        self.assertIn("Why are Connaught Place sales down versus the week before?", html)
        self.assertIn("9 licences expired, 3 expire in 30 days", html)
        self.assertNotIn("Trend Connaught", html)
        self.assertNotIn("-₹", html)
        self.assertLessEqual(html.count('class="cc-insight"'), 3)


if __name__ == "__main__":
    unittest.main()
