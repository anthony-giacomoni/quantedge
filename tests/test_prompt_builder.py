from modules.prompt_builder import fill_template


def test_zero_template_value_is_not_converted_to_na():
    out=fill_template("A={a}",{"a":0})
    assert "A=0" in out
