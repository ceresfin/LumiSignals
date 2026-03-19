"""Tests for order_manager — position sizing, pip precision, price formatting."""

from lumisignals.order_manager import calculate_position_size, get_pip_precision, format_price


class TestCalculatePositionSize:
    def test_standard_forex(self):
        # $10,000 account, 1% risk, 50 pip stop on EURUSD
        units = calculate_position_size(
            account_balance=10000,
            risk_percent=1.0,
            entry_price=1.0850,
            stop_price=1.0800,
        )
        # risk = $100, stop distance = 0.005, units = 100/0.005 = 20000
        assert units == 20000

    def test_zero_stop_distance(self):
        units = calculate_position_size(10000, 1.0, 1.0850, 1.0850)
        assert units == 0

    def test_respects_max_units(self):
        units = calculate_position_size(
            account_balance=1000000,
            risk_percent=5.0,
            entry_price=1.0850,
            stop_price=1.0849,
            max_units=100000,
        )
        assert units == 100000

    def test_custom_max_units(self):
        units = calculate_position_size(
            account_balance=100000,
            risk_percent=1.0,
            entry_price=1.0850,
            stop_price=1.0800,
            max_units=50000,
        )
        assert units == 50000

    def test_sell_direction_same_size(self):
        # Position size should be the same regardless of direction
        units = calculate_position_size(10000, 1.0, 1.2650, 1.2700)
        # float math: 100 / 0.005 may be 19999 or 20000 depending on rounding
        assert 19999 <= units <= 20000


class TestGetPipPrecision:
    def test_standard_forex(self):
        pip, prec = get_pip_precision("EUR_USD")
        assert pip == 0.0001
        assert prec == 5

    def test_jpy_pair(self):
        pip, prec = get_pip_precision("USD_JPY")
        assert pip == 0.01
        assert prec == 3

    def test_gold(self):
        pip, prec = get_pip_precision("XAU_USD")
        assert pip == 0.1
        assert prec == 2

    def test_silver(self):
        pip, prec = get_pip_precision("XAG_USD")
        assert pip == 0.01
        assert prec == 4

    def test_index(self):
        pip, prec = get_pip_precision("SPX500_USD")
        assert pip == 1.0
        assert prec == 1


class TestFormatPrice:
    def test_five_decimals(self):
        assert format_price(1.08500, 5) == "1.08500"

    def test_three_decimals(self):
        assert format_price(149.500, 3) == "149.500"

    def test_two_decimals(self):
        assert format_price(2345.10, 2) == "2345.10"
