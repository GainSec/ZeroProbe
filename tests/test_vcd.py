import unittest

from zeroprobe.capture import Capture, Sample
from zeroprobe.vcd import encode_vcd


class VcdTests(unittest.TestCase):
    def test_encodes_only_transitions_with_nanosecond_timestamps(self):
        capture = Capture(
            gpios=(22, 23),
            samples=(
                Sample(1_000, {22: 0, 23: 1}),
                Sample(1_500, {22: 1, 23: 1}),
                Sample(3_000, {22: 1, 23: 0}),
            ),
        )
        text = encode_vcd(capture, source="sim")
        self.assertIn("$timescale 1 ns $end", text)
        self.assertIn("$var wire 1 ! GPIO22 $end", text)
        self.assertIn("$var wire 1 \" GPIO23 $end", text)
        self.assertIn("#1000\n0!\n1\"", text)
        self.assertIn("#1500\n1!", text)
        self.assertNotIn("#1500\n1!\n1\"", text)
        self.assertIn("#3000\n0\"", text)

    def test_rejects_non_monotonic_samples(self):
        capture = Capture((22,), (Sample(20, {22: 0}), Sample(10, {22: 1})))
        with self.assertRaisesRegex(ValueError, "monotonic"):
            encode_vcd(capture)

    def test_rejects_missing_channel_value(self):
        capture = Capture((22, 23), (Sample(0, {22: 0}),))
        with self.assertRaisesRegex(ValueError, "GPIO23"):
            encode_vcd(capture)


if __name__ == "__main__":
    unittest.main()
