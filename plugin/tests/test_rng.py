from casino import rng


def test_shuffle_is_deterministic_per_seed():
    deck = list(range(52))
    assert rng.shuffle(deck, 123) == rng.shuffle(deck, 123)


def test_shuffle_is_a_permutation_and_nondestructive():
    deck = list(range(52))
    shuffled = rng.shuffle(deck, 999)
    assert sorted(shuffled) == deck        # same multiset
    assert deck == list(range(52))         # original untouched


def test_different_seeds_usually_differ():
    deck = list(range(52))
    assert rng.shuffle(deck, 1) != rng.shuffle(deck, 2)


def test_make_seed_in_range():
    s = rng.make_seed()
    assert 0 <= s < (1 << 63)


def test_randint_deterministic_and_in_range():
    n = rng.randint(0, 36, 42)
    assert 0 <= n <= 36
    assert rng.randint(0, 36, 42) == n
