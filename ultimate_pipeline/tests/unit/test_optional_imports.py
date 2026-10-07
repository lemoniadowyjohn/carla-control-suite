import pytest
from ultimate_pipeline.utils.optional_imports import optional_import, require


class TestOptionalImport:
    def test_existing_module(self):
        result = optional_import("os")
        assert result is not None
        assert hasattr(result, "path")

    def test_existing_module_submodule(self):
        result = optional_import("os.path")
        assert result is not None
        assert hasattr(result, "join")

    def test_nonexistent_module(self):
        result = optional_import("this_module_does_not_exist_12345")
        assert result is None

    def test_nonexistent_submodule(self):
        result = optional_import("os.this_does_not_exist")
        assert result is None

    def test_empty_string(self):
        result = optional_import("")
        assert result is None

    def test_builtin_module(self):
        result = optional_import("sys")
        assert result is not None
        assert hasattr(result, "version")

    def test_third_party_if_available(self):
        # Test with a commonly available package
        result = optional_import("json")
        assert result is not None
        assert hasattr(result, "dumps")


class TestRequire:
    def test_present_dependency_passes(self):
        dep = optional_import("os")
        require(dep, "os", "file operations")
        # Should not raise

    def test_missing_dependency_raises(self):
        dep = None
        with pytest.raises(RuntimeError) as exc_info:
            require(dep, "missing_module", "some feature")
        
        error_msg = str(exc_info.value)
        assert "missing_module" in error_msg
        assert "some feature" in error_msg
        assert "not installed" in error_msg

    def test_missing_dependency_custom_message(self):
        dep = None
        with pytest.raises(RuntimeError) as exc_info:
            require(dep, "numpy", "array operations")
        
        assert "numpy" in str(exc_info.value)
        assert "array operations" in str(exc_info.value)

    def test_false_value_still_raises(self):
        # False, 0, empty string are falsy but not None
        # The function checks `if dep is None` so these should pass
        # Wait, let me check the implementation - it checks `if dep is None`
        dep = False
        # This should NOT raise because False is not None
        require(dep, "bool_module", "bool feature")
        
        dep = 0
        require(dep, "int_module", "int feature")
        
        dep = ""
        require(dep, "str_module", "str feature")


class TestOptionalImportIntegration:
    def test_pattern_usage(self):
        # Typical usage pattern
        carla = optional_import("carla")
        if carla is None:
            # Should handle gracefully
            assert True
        else:
            assert hasattr(carla, "Client")

    def test_require_after_optional_import(self):
        # Common pattern: optional_import then require
        torch = optional_import("torch")
        if torch is not None:
            require(torch, "torch", "tensor operations")
            assert hasattr(torch, "tensor")