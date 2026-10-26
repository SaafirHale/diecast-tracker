import unittest

from diecast_tracker import stats


class Percentiles(unittest.TestCase):
    def test_matches_numpy_linear(self):
        xs = [10, 20, 30, 40]
        self.assertEqual(stats.percentile(xs, 0), 10)
        self.assertEqual(stats.percentile(xs, 100), 40)
        self.assertAlmostEqual(stats.percentile(xs, 25), 17.5)   # numpy: 17.5
        self.assertAlmostEqual(stats.percentile(xs, 50), 25.0)
        self.assertAlmostEqual(stats.percentile(xs, 90), 37.0)   # numpy: 37.0

    def test_unsorted_input_and_single_value(self):
        self.assertEqual(stats.median([30, 10, 20]), 20)
        self.assertEqual(stats.percentile([42.0], 10), 42.0)

    def test_errors(self):
        with self.assertRaises(ValueError):
            stats.percentile([], 50)
        with self.assertRaises(ValueError):
            stats.percentile([1, 2], 101)


class Outliers(unittest.TestCase):
    def test_typical_mini_gt_asks(self):
        # Landed asks for one Mini GT: a cluster around $24-30, one $4.99
        # "starting bid" and one $129 fishing listing.
        asks = [24.99, 26.5, 27.0, 25.99, 29.95, 28.0, 4.99, 129.0, 26.0, 27.49]
        kept, rejected = stats.split_outliers(asks)
        self.assertEqual(sorted(rejected), [4.99, 129.0])
        self.assertEqual(len(kept), 8)

    def test_small_samples_are_left_alone(self):
        kept, rejected = stats.split_outliers([20, 25, 200])
        self.assertEqual(rejected, [])

    def test_identical_prices_fall_back_to_iqr(self):
        # Retail-style pricing: most sellers list at MSRP, MAD is zero.
        asks = [21.99] * 6 + [22.99, 9.99]
        kept, rejected = stats.split_outliers(asks)
        self.assertEqual(rejected, [9.99])
        self.assertIn(22.99, kept)

    def test_all_identical(self):
        kept, rejected = stats.split_outliers([30.0] * 7)
        self.assertEqual((len(kept), rejected), (7, []))

    def test_genuine_spread_is_not_trimmed(self):
        # A 1:18 with a wide but real spread: nothing should be thrown away.
        sold = [139, 145, 150, 158, 160, 165, 172, 180, 189]
        kept, rejected = stats.split_outliers(sold)
        self.assertEqual(rejected, [])


class Summarise(unittest.TestCase):
    def test_summary_uses_kept_values(self):
        s = stats.summarise([24.99, 26.5, 27.0, 25.99, 29.95, 28.0, 4.99, 129.0, 26.0, 27.49])
        self.assertEqual((s.n, s.n_rejected), (8, 2))
        self.assertAlmostEqual(s.median, 26.75)   # middle of the 8 kept: (26.50 + 27.00) / 2
        self.assertEqual((s.low, s.high), (24.99, 29.95))
        self.assertLessEqual(s.p25, s.median)
        self.assertLessEqual(s.median, s.p75)

    def test_empty(self):
        self.assertIsNone(stats.summarise([]))


if __name__ == "__main__":
    unittest.main()
