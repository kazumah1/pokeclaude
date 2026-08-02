import pytest

from casino import roulette


def test_truncated_dozen_column_raise_valueerror():
    with pytest.raises(ValueError):
        roulette.parse_bet("300 on dozen")
    with pytest.raises(ValueError):
        roulette.parse_bet("150 on column")
    with pytest.raises(ValueError):
        roulette.parse_bet("100 on dozen 9")   # out of range


def test_negative_and_zero_amounts_raise():
    with pytest.raises(ValueError):
        roulette.parse_bet("-100000 on 17")
    with pytest.raises(ValueError):
        roulette.parse_bet("0 on red")


def test_parse_common_bets():
    assert roulette.parse_bet("500 on red") == ("color", "red", 500)
    assert roulette.parse_bet("200 on 17") == ("straight", 17, 200)
    assert roulette.parse_bet("100 on odd") == ("parity", "odd", 100)
    assert roulette.parse_bet("300 on dozen 2") == ("dozen", 2, 300)


def test_straight_pays_35_to_1():
    total, net = roulette.resolve([("straight", 17, 100)], number=17)
    assert net == 3500                 # profit
    assert total == 3600               # profit + returned stake


def test_straight_miss_loses_stake():
    total, net = roulette.resolve([("straight", 17, 100)], number=18)
    assert total == 0 and net == -100


def test_red_pays_even_money():
    total, net = roulette.resolve([("color", "red", 100)], number=1)   # 1 is red
    assert net == 100


def test_zero_loses_even_money_bets():
    total, net = roulette.resolve([("color", "red", 100)], number=0)
    assert total == 0 and net == -100


def test_dozen_pays_two_to_one():
    total, net = roulette.resolve([("dozen", 2, 100)], number=17)      # 13-24
    assert net == 200


def test_spin_deterministic_and_in_range():
    n = roulette.spin(42)
    assert 0 <= n <= 36
    assert roulette.spin(42) == n
