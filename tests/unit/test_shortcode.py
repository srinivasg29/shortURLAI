from app.shortcode import generate_code


def test_generate_code_length():
    assert len(generate_code(7)) == 7


def test_generate_code_alphabet():
    code = generate_code(50)
    assert all(c.isalnum() for c in code)


def test_generate_code_is_random():
    codes = {generate_code(10) for _ in range(200)}
    assert len(codes) == 200
