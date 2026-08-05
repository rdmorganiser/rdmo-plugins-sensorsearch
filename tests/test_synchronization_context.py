import pytest

from rdmo_sensorsearch.services.synchronization_context import (
    is_value_post_save_muted,
    mute_value_post_save,
)


def test_post_save_muting_is_nested_and_restores_the_previous_context():
    assert is_value_post_save_muted() is False

    with mute_value_post_save():
        assert is_value_post_save_muted() is True
        with mute_value_post_save():
            assert is_value_post_save_muted() is True
        assert is_value_post_save_muted() is True

    assert is_value_post_save_muted() is False


def test_post_save_muting_is_restored_after_an_exception():
    with pytest.raises(RuntimeError, match="write failed"):
        with mute_value_post_save():
            assert is_value_post_save_muted() is True
            raise RuntimeError("write failed")

    assert is_value_post_save_muted() is False
