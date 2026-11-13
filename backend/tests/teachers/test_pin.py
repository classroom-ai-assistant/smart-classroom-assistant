from app.modules.teachers.pin import hash_pin, verify_pin


def test_same_pin_hashes_differently_each_time():
    assert hash_pin("1234") != hash_pin("1234")


def test_verify_round_trip():
    stored = hash_pin("987654")
    assert verify_pin("987654", stored)
    assert not verify_pin("987655", stored)


def test_verify_rejects_malformed_hash():
    assert not verify_pin("1234", "not-a-hash")
    assert not verify_pin("1234", "bcrypt$1$2$3$aa$bb")
