import pytest
from ultimate_pipeline.utils.hashing import stable_hash


class TestStableHash:
    def test_basic_dict_deterministic(self):
        obj = {"b": 2, "a": 1}
        h1 = stable_hash(obj)
        h2 = stable_hash(obj)
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex length

    def test_nested_dict_order_independent(self):
        obj1 = {"a": {"c": 3, "b": 2}, "b": 1}
        obj2 = {"b": 1, "a": {"b": 2, "c": 3}}
        assert stable_hash(obj1) == stable_hash(obj2)

    def test_list_order_matters(self):
        obj1 = [1, 2, 3]
        obj2 = [3, 2, 1]
        assert stable_hash(obj1) != stable_hash(obj2)

    def test_different_types_produce_different_hashes(self):
        assert stable_hash(42) != stable_hash("42")
        assert stable_hash([1, 2]) != stable_hash((1, 2))
        assert stable_hash({"a": 1}) != stable_hash({"a": 1.0})

    def test_custom_algorithm(self):
        h_sha256 = stable_hash({"a": 1}, algo="sha256")
        h_sha1 = stable_hash({"a": 1}, algo="sha1")
        assert len(h_sha256) == 64
        assert len(h_sha1) == 40
        assert h_sha256 != h_sha1

    def test_unicode_handling(self):
        obj = {"key": "值", "emoji": "🚀"}
        h = stable_hash(obj)
        assert len(h) == 64
        assert stable_hash(obj) == h

    def test_none_and_empty(self):
        assert stable_hash(None) == stable_hash(None)
        assert stable_hash({}) == stable_hash({})
        assert stable_hash([]) == stable_hash([])

    def test_float_nan_handling(self):
        # NaN serializes to NaN in JSON, which may not be equal
        import math
        obj1 = {"v": float("nan")}
        obj2 = {"v": float("nan")}
        # Both serialize to "NaN" in JSON, so they should be equal
        assert stable_hash(obj1) == stable_hash(obj2)

    def test_large_object(self):
        obj = {str(i): i for i in range(1000)}
        h = stable_hash(obj)
        assert len(h) == 64


class TestStableHashEdgeCases:
    def test_tuple_vs_list(self):
        # Tuples and lists serialize differently in JSON
        assert stable_hash([1, 2]) != stable_hash((1, 2))

    def test_set_serialization(self):
        # Sets are now supported with type markers
        s = {1, 2, 3}
        h = stable_hash(s)
        assert len(h) == 64
        # Deterministic despite set ordering
        assert stable_hash({3, 2, 1}) == h

    def test_frozenset_serialization(self):
        fs = frozenset([1, 2, 3])
        h = stable_hash(fs)
        assert len(h) == 64
        assert stable_hash(frozenset([3, 2, 1])) == h

    def test_custom_object_not_serializable(self):
        class Custom:
            pass
        with pytest.raises(TypeError):
            stable_hash(Custom())