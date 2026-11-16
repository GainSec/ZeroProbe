import unittest

from zeroprobe.profile import CARDPUTER_ZERO, CaptureRequest, UnsafePinUse


class CardputerZeroProfileTests(unittest.TestCase):
    def test_profile_exposes_documented_hat_gpio(self):
        self.assertEqual(
            {7, 9, 10, 11, 14, 15, 22, 23, 26, 2, 3},
            set(CARDPUTER_ZERO.pins),
        )
        self.assertEqual("3.3V", CARDPUTER_ZERO.logic_level)

    def test_shared_pin_requires_explicit_override(self):
        request = CaptureRequest.from_csv("2,3")
        with self.assertRaisesRegex(UnsafePinUse, "shared with I2C1/keyboard"):
            CARDPUTER_ZERO.validate_capture(request)

    def test_general_gpio_capture_is_safe_by_default(self):
        request = CaptureRequest.from_csv("22")
        validated = CARDPUTER_ZERO.validate_capture(request)
        self.assertEqual((22,), validated.gpios)

    def test_gpio_aliases_resolve(self):
        request = CaptureRequest.from_csv("SPI_CLK,GPIO22")
        self.assertEqual((11, 22), request.resolve(CARDPUTER_ZERO).gpios)

    def test_unknown_pin_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not exposed"):
            CaptureRequest.from_csv("GPIO4").resolve(CARDPUTER_ZERO)


if __name__ == "__main__":
    unittest.main()
