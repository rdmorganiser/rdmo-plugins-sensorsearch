import pytest

from rdmo_sensorsearch.services.synchronization_context import (
    is_value_sync_muted,
    mute_value_sync,
)


def test_value_sync_muting_is_nested_and_restores_the_previous_context():
    assert is_value_sync_muted() is False

    with mute_value_sync():
        assert is_value_sync_muted() is True
        with mute_value_sync():
            assert is_value_sync_muted() is True
        assert is_value_sync_muted() is True

    assert is_value_sync_muted() is False


def test_value_sync_muting_is_restored_after_an_exception():
    with pytest.raises(RuntimeError, match="write failed"):
        with mute_value_sync():
            assert is_value_sync_muted() is True
            raise RuntimeError("write failed")

    assert is_value_sync_muted() is False
