"""Matcher tests on hand-written listing titles in the style sellers use.

The titles are invented for testing (not copied from real listings) but
follow the patterns seen across the hobby: item numbers with and without
padding, maker nicknames, missing scale, shouty caps, emoji, colour
shorthand, lots and loose cars, chase variants, and near-identical models
that differ only by colour, year, race number or film.
"""

import unittest
from pathlib import Path

from diecast_tracker import catalogue
from diecast_tracker.matcher import Matcher, detect_flags
from diecast_tracker import normalize as N

CATALOGUE = Path(__file__).resolve().parent.parent / "data" / "catalogue.json"
MATCHER = Matcher(catalogue.load(CATALOGUE))

# (title, expected status, expected model id or None)
CASES = [
    # --- item numbers, in all the ways people type them ---------------------
    ("Mini GT MGT00745 Cadillac V-Series.R #31 Sebring 2023 Winner 1:64", "matched", "MGT00745"),
    ("MINIGT 1/64 #745 CADILLAC V SERIES R WHELEN 12H SEBRING", "matched", "MGT00745"),
    ("mini gt mgt 745 cadillac whelen", "matched", "MGT00745"),
    ("Mini-GT No. 736 Cadillac V-Series.R #311 Le Mans 2023 Action Express", "matched", "MGT00736"),
    ("Tarmac Works T64G-TL021-WH Pagani Zonda Cinque Bianco Benny 1/64", "matched", "T64G-TL021-WH"),
    ("TARMAC TL021-WH Zonda Cinque white/black Global64", "matched", "T64G-TL021-WH"),
    ("Pop Race PR640127 Pandem Civic EG6 Blue", "matched", "PR640127"),
    ("BM Creations 64B0283 Range Rover Classic Camel Trophy 1:64 RHD", "matched", "64B0283"),
    ("OttOmobile OT1173 BMW 3.0 CSL Reyn Speed Shop 1:18 Jonsibal", "matched", "OT1173"),
    ("GT Spirit GT507 BMW M5 G90 Marina Bay Blue 1/18 Resin", "matched", "GT507"),
    ("Kaido House KHMG217 BMW M3 Larry Chen 7-Eleven V1 Mini GT 1:64", "matched", "KHMG217"),
    ("Inno64 IN64-R34TS-WHI Nissan Skyline GT-R R34 Top Secret White", "matched", "IN64-R34TS-WHI"),
    ("Mini GT MGT00908 Jaguar XKR 007 Die Another Day Green", "matched", "MGT00908-007E"),
    # item number wins even when a sibling's title is nearly identical
    ("Mini GT MGT00901-007E 1-64 ASTON MARTIN DB5 RHD BIRCH SILVER METALLIC NEW", "matched", "MGT00901-007E"),

    # --- no item number: casting + colour has to carry it -------------------
    ("Mini GT 1/64 Lamborghini Revuelto Giallo Yellow NEW", "matched", "MGT00886"),
    ("MINI GT LAMBO REVUELTO YELLOW 🔥🔥 1:64 SEALED", "matched", "MGT00886"),
    ("Mini GT 1964 Porsche 911 Slate Grey 1:64 Limited", "matched", "MGT00717"),
    ("Mini GT 1963 Porsche 901 Signal Red", "matched", "MGT00695"),
    ("Tarmac Works Koenigsegg Jesko Attack Blue Metallic 1:64", "matched", "T64G-TL052-BL"),
    ("Tarmac Koenigsegg Agera RS Black Carbon Red 1/64 Global64", "matched", "T64G-TL005-BCF"),
    ("Mini GT VW ID Buzz Pomelo Yellow / Candy White 1:64", "matched", "MGT01110"),
    ("Mini GT Lotus 99T Ayrton Senna #12 Monaco 1987 Winner w/ figure", "matched", "MGT01088"),
    ("Tarmac Works AE86 Trueno Widebody Jonsibal Black Gray 1/64", "matched", "T64G-060-BG"),
    ("Tarmac Works AE86 Sprinter Trueno Widebody White Black Tarmac Cards", "matched", "T64G-060-WB"),
    ("Mini GT LBWK RX7 Super Silhouette #20 Black", "matched", "MGT00785"),
    ("Mini GT Nissan Silvia S15 LB Super Silhouette Fausto Racing Green", "matched", "MGT00858"),
    ("Mini GT Abarth 595 LB Works Abas Works Pink #49", "matched", "MGT00851"),
    ("GT Spirit 1:18 Porsche 911 964 RWB Qeema Yellow", "matched", "GT492"),
    ("Otto 1/18 Toyota Supra GT4 100 Edition Plasma Orange", "matched", "OT1123"),
    ("Pop Race 1:64 Mazda 787B Le Mans 1991 #55 Mazdaspeed", "matched", "PR640301"),
    ("POPRACE RX7 FD3S BAPE purple camo 1/64", "matched", "PR640493"),
    ("Inno Models 1:64 Toyota MR2 SW20 Red RHD", "matched", "IN64-MR2SW20-RED"),
    ("Tarmac Works Mercedes AMG W14 Lewis Hamilton #44 Hungary 2023", "matched", "T64G-F064-LH1"),
    ("Tarmac Works W14 #47 Mick Schumacher Tyre Test w/ pit board", "matched", "T64G-F064-MS1"),
    ("Mini GT Aston Martin DB5 Skyfall Silver 007 (Damaged version) 1/64", "matched", "MGT00913-007E"),

    # --- near twins: the matcher must not guess -----------------------------
    ("Mini GT Aston Martin DB5 007 James Bond Silver 1:64", "ambiguous", None),
    ("Mini GT Cadillac V-Series.R Jack Aitken Pipo Derani 1/64", "ambiguous", None),
    ("Tarmac Works Mercedes W14 F1 1:64 Global64", "ambiguous", None),

    # --- right model, not a comparable sale ---------------------------------
    ("Mini GT Lot of 5 - Revuelto, 901, Porsche 911, Lincoln Capri, Jaguar XKR", "rejected", None),
    ("LOOSE Mini GT Lamborghini Revuelto Yellow no box", "rejected", "MGT00886"),
    ("Mini GT 1964 Porsche 911 Slate Gray CHASE", "rejected", "MGT00717"),
    ("Mini GT MGT00745 Cadillac V-Series.R  - box damaged, car mint", "matched", "MGT00745"),
    # "damaged" here is about the box; it is also a word in another model's name
    ("Mini GT BMW M3 Kaido Works Larry Chen #29 7-Eleven box damaged car mint", "matched", "KHMG217"),
    ("CUSTOM Mini GT Lamborghini Revuelto yellow w/ rubber tires", "rejected", "MGT00886"),
    ("Empty box only Tarmac Works Pagani Zonda Cinque T64G-TL021-WH", "rejected", "T64G-TL021-WH"),
    ("3D printed Pandem Civic EG6 1/64 blue (Pop Race style)", "rejected", "PR640127"),

    # --- wrong product altogether -------------------------------------------
    ("Hot Wheels Pandem Civic EG6 Blue Car Culture", "no_match", None),
    ("Mini GT Lamborghini Revuelto 1:18 Yellow", "no_match", None),        # no 1:18 Revuelto in catalogue
    ("GT Spirit 1:64 Porsche 911 RWB Qeema", "no_match", None),             # catalogue model is 1:18
    ("Mini GT Ferrari 296 GTB Rosso Corsa", "no_match", None),
    ("Pop Race Honda Civic Type R FL5 white", "no_match", None),            # Civic in catalogue is Mini GT
    ("Mini GT Lamborghini Revuelto Verde Green", "no_match", None),         # colour the catalogue lacks
    ("Mini GT 1964 Porsche 911 Irish Green", "no_match", None),
    ("Tomica Premium Nissan Skyline GT-R R34", "no_match", None),
    ("Matchbox VW ID Buzz Yellow 2024", "no_match", None),
]


class MatcherCases(unittest.TestCase):
    def test_cases(self):
        failures = []
        for title, status, sku in CASES:
            r = MATCHER.match(title)
            ok = r.status == status and (sku is None or r.model_id == sku)
            if not ok:
                failures.append(f"\n  {title!r}\n    want {status} {sku}  got {r.status} {r.model_id} "
                                f"conf={r.confidence} {r.reasons} cands={r.candidates}")
        self.assertFalse(failures, "".join(failures))

    def test_ambiguous_lists_candidates(self):
        r = MATCHER.match("Mini GT Aston Martin DB5 007 James Bond Silver 1:64")
        ids = {c for c, _ in r.candidates[:2]}
        self.assertEqual(ids, {"MGT00901-007E", "MGT00913-007E"})

    def test_own_name_word_is_not_a_flag(self):
        # "Damaged" is part of this model's name, so it must not reject the listing.
        r = MATCHER.match("Mini GT MGT00913 DB5 Skyfall Damaged Version")
        self.assertEqual((r.status, r.model_id), ("matched", "MGT00913-007E"))
        self.assertNotIn("damaged", r.flags)

    def test_box_damage_matches_but_is_not_comparable(self):
        r = MATCHER.match("Mini GT MGT00745 Cadillac V-Series.R - box damaged, car mint")
        self.assertEqual(r.status, "matched")
        self.assertIn("box_damage", r.flags)
        self.assertFalse(r.comparable)

    def test_preorder_is_flagged_but_comparable(self):
        r = MATCHER.match("PRE-ORDER Mini GT MGT01110 VW ID. Buzz Pomelo Yellow")
        self.assertEqual(r.status, "matched")
        self.assertIn("preorder", r.flags)
        self.assertTrue(r.comparable)


class Normalisation(unittest.TestCase):
    def test_scales(self):
        self.assertEqual(N.scales("Mini GT 1/64"), {"1:64"})
        self.assertEqual(N.scales("1:18 scale"), {"1:18"})
        self.assertEqual(N.scales("1-64 diecast"), {"1:64"})
        self.assertEqual(N.scales("64th scale"), {"1:64"})
        self.assertEqual(N.scales("Porsche 911 1964"), set())   # a year, not a scale

    def test_makers(self):
        self.assertEqual(N.makers("MINIGT #745"), {"Mini GT"})
        self.assertEqual(N.makers("GT Spirit 1:18"), {"GT Spirit"})
        self.assertEqual(N.makers("Tarmac Works Global64"), {"Tarmac Works"})
        self.assertEqual(N.makers("Kaido House x Mini GT"), {"Mini GT"})
        self.assertEqual(N.makers("Porsche 911 GT3 RS"), set())  # "GT" alone is not a maker

    def test_tokens_join_model_codes(self):
        self.assertIn("rx7", N.tokens("Mazda RX-7 FD3S"))
        self.assertIn("gtr", N.tokens("Skyline GT-R"))
        self.assertIn("rx7", N.joined_ngrams(N.tokens("Mazda RX 7")))
        self.assertIn("gray", N.tokens("Slate Grey"))

    def test_race_numbers(self):
        self.assertEqual(N.race_numbers("Cadillac #31 and No. 311"), {"31", "311"})

    def test_flags(self):
        self.assertIn("lot", detect_flags("Lot of 3 Mini GT"))
        self.assertIn("lot", detect_flags("Mini GT Porsche 901 Signal Red x3"))
        self.assertIn("loose", detect_flags("Mini GT Revuelto (no box)"))
        self.assertIn("chase", detect_flags("Super Chase Tarmac"))
        self.assertNotIn("lot", detect_flags("Mini GT Lotus 99T"))
        self.assertNotIn("lot", detect_flags("2 Car Box Set Pop Race"))
        self.assertNotIn("lot", detect_flags("BMW X3 M Competition"))
        self.assertNotIn("not_a_model", detect_flags("Pop Race Pandem Civic"))


if __name__ == "__main__":
    unittest.main()
