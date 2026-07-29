# FV01 Baseline Tests

Generated UTC: 2026-07-29T21:07:06.828160+00:00
Repository: C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main
Branch: verification/map-quality-hardening-20260729
SHA: ff00099dae404f49a83d7dd909a3c35259040ebb
Interpreter: C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\.venv\Scripts\python.exe (Python 3.12.2)
PYTHONPATH removed for subprocesses: True

| id | exit | collected | passed | failed | skipped | xfailed | xpassed | errors | warnings | duration s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| compileall | 0 |  |  |  |  |  |  |  |  | 0.754 |
| collect_only | 2 | 230 |  |  |  |  |  | 7 |  | 2.552 |
| geometry_scaffold | 0 | 2280 | 2202 |  | 78 |  |  |  |  | 7.397 |
| canonical_line_arc | 0 | 89 | 89 |  |  |  |  |  |  | 3.656 |
| related_geometry_exact_paths | 4 | 0 |  |  |  |  |  |  |  | 1.291 |
| cross_compare | 1 |  |  |  |  |  |  |  |  | 0.21 |
| full_non_carla | 2 | 230 |  |  |  |  |  | 7 |  | 2.089 |
| geometry_scaffold_optimized | 0 | 2280 | 2202 |  | 78 |  |  |  |  | 11.125 |

## Failed Commands

- collect_only
- related_geometry_exact_paths
- cross_compare
- full_non_carla

## Command Tails

### compileall

```text

```

### collect_only

```text
sts\unit\test_curvature_gap_parampoly3.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ultimate_pipeline\tests\unit\test_curvature_gap_parampoly3.py:6: in <module>
    from ultimate_pipeline.domain_gap.curvature_gap import CurvatureGap, _extract_curvatures
E   ModuleNotFoundError: No module named 'ultimate_pipeline.domain_gap.curvature_gap'
_____ ERROR collecting ultimate_pipeline/tests/unit/test_elevation_gap.py _____
ImportError while importing test module 'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\ultimate_pipeline\tests\unit\test_elevation_gap.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ultimate_pipeline\tests\unit\test_elevation_gap.py:8: in <module>
    from ultimate_pipeline.domain_gap.domain_gap_aggregator import DomainGapAggregator
E   ModuleNotFoundError: No module named 'ultimate_pipeline.domain_gap.domain_gap_aggregator'
_ ERROR collecting ultimate_pipeline/tests/unit/test_geo_alignment_rigid_scale_lock.py _
ImportError while importing test module 'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\ultimate_pipeline\tests\unit\test_geo_alignment_rigid_scale_lock.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ultimate_pipeline\tests\unit\test_geo_alignment_rigid_scale_lock.py:6: in <module>
    from ultimate_pipeline.domain_gap.geo_alignment import GeoAligner
E   ModuleNotFoundError: No module named 'ultimate_pipeline.domain_gap.geo_alignment'
_____ ERROR collecting tests/unit/test_geometric_continuity_migration.py ______
ImportError while importing test module 'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\tests\unit\test_geometric_continuity_migration.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\unit\test_geometric_continuity_migration.py:8: in <module>
    from ultimate_pipeline.quality.check_geometric_continuity import (
E   ModuleNotFoundError: No module named 'ultimate_pipeline.quality.check_geometric_continuity'
_______ ERROR collecting tests/unit/test_junction_connector_rebuild.py ________
ImportError while importing test module 'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\tests\unit\test_junction_connector_rebuild.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\unit\test_junction_connector_rebuild.py:8: in <module>
    from ultimate_pipeline.topology.junction_connector_rebuild import (
E   ModuleNotFoundError: No module named 'ultimate_pipeline.topology.junction_connector_rebuild'
___________ ERROR collecting tests/unit/test_stage6_containment.py ____________
ImportError while importing test module 'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\tests\unit\test_stage6_containment.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\unit\test_stage6_containment.py:10: in <module>
    from ultimate_pipeline.geometry.planview_smoother import PlanViewSmoother
E   ModuleNotFoundError: No module named 'ultimate_pipeline.geometry.planview_smoother'
________ ERROR collecting tests/unit/test_stage6_unsafe_flag_policy.py ________
ImportError while importing test module 'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\tests\unit\test_stage6_unsafe_flag_policy.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\unit\test_stage6_unsafe_flag_policy.py:5: in <module>
    from ultimate_pipeline.config.settings import Settings
ultimate_pipeline\config\settings.py:25: in <module>
    from ultimate_pipeline.utils.paths import repo_root, city_dir, resolve_path
E   ModuleNotFoundError: No module named 'ultimate_pipeline.utils.paths'
=========================== short test summary info ===========================
ERROR ultimate_pipeline/tests/unit/test_curvature_gap_parampoly3.py
ERROR ultimate_pipeline/tests/unit/test_elevation_gap.py
ERROR ultimate_pipeline/tests/unit/test_geo_alignment_rigid_scale_lock.py
ERROR tests/unit/test_geometric_continuity_migration.py
ERROR tests/unit/test_junction_connector_rebuild.py
ERROR tests/unit/test_stage6_containment.py
ERROR tests/unit/test_stage6_unsafe_flag_policy.py
!!!!!!!!!!!!!!!!!!! Interrupted: 7 errors during collection !!!!!!!!!!!!!!!!!!!
=================== 230 tests collected, 7 errors in 0.75s ====================
```

### geometry_scaffold

```text
============================= test session starts =============================
platform win32 -- Python 3.12.2, pytest-9.0.1, pluggy-1.6.0
rootdir: C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main
configfile: pytest.ini
plugins: anyio-4.12.1
collected 2280 items

tests\opendrive_geometry\test_arc.py ....................                [  0%]
tests\opendrive_geometry\test_existing_implementations.py .............. [  1%]
........................................................................ [  4%]
........................................................................ [  7%]
........................................................................ [ 10%]
........................................................................ [ 14%]
........................................................................ [ 17%]
........................................................................ [ 20%]
........................................................................ [ 23%]
.........................................ssssss......................... [ 26%]
.....................................................ssssss............. [ 29%]
.................................................................ssssss. [ 33%]
........................................................................ [ 36%]
.....ssssss............................................................. [ 39%]
.................ssssss................................................. [ 42%]
.............................ssssss..................................... [ 45%]
.........................................ssssss......................... [ 48%]
.....................................................ssssss............. [ 52%]
.................................................................ssssss. [ 55%]
........................................................................ [ 58%]
.....ssssss............................................................. [ 61%]
.................ssssss................................................. [ 64%]
.............................ssssss..................................... [ 67%]
.........................................ssssss........                  [ 70%]
tests\opendrive_geometry\test_line.py ................                   [ 70%]
tests\opendrive_geometry\test_near_zero_curvature.py ................... [ 71%]
........................................................................ [ 74%]
........................................................................ [ 78%]
........................................................................ [ 81%]
........................................................................ [ 84%]
........................................................................ [ 87%]
........................................................................ [ 90%]
........................................................................ [ 93%]
..............................................................           [ 96%]
tests\opendrive_geometry\test_s_domain.py .............................. [ 97%]
........................                                                 [ 98%]
tests\opendrive_geometry\test_sampling.py ...............                [ 99%]
tests\opendrive_geometry\test_transform_invariance.py .........          [100%]

====================== 2202 passed, 78 skipped in 5.94s =======================
```

### canonical_line_arc

```text
============================= test session starts =============================
platform win32 -- Python 3.12.2, pytest-9.0.1, pluggy-1.6.0
rootdir: C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main
configfile: pytest.ini
plugins: anyio-4.12.1
collected 89 items

ultimate_pipeline\tests\unit\test_opendrive_geometry_line_arc.py ....... [  7%]
........................................................................ [ 88%]
..........                                                               [100%]

============================= 89 passed in 2.09s ==============================
```

### related_geometry_exact_paths

```text
============================= test session starts =============================
platform win32 -- Python 3.12.2, pytest-9.0.1, pluggy-1.6.0
rootdir: C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main
configfile: pytest.ini
plugins: anyio-4.12.1
collected 0 items

============================ no tests ran in 0.02s ============================
```

### cross_compare

```text
Traceback (most recent call last):
  File "C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\opendrive_geometry\cross_compare_implementations.py", line 16, in <module>
    from opendrive_geometry.primitives import evaluate_line, evaluate_arc, evaluate_param_poly3, EPS
ModuleNotFoundError: No module named 'opendrive_geometry'
```

### full_non_carla

```text
sts\unit\test_curvature_gap_parampoly3.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ultimate_pipeline\tests\unit\test_curvature_gap_parampoly3.py:6: in <module>
    from ultimate_pipeline.domain_gap.curvature_gap import CurvatureGap, _extract_curvatures
E   ModuleNotFoundError: No module named 'ultimate_pipeline.domain_gap.curvature_gap'
_____ ERROR collecting ultimate_pipeline/tests/unit/test_elevation_gap.py _____
ImportError while importing test module 'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\ultimate_pipeline\tests\unit\test_elevation_gap.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ultimate_pipeline\tests\unit\test_elevation_gap.py:8: in <module>
    from ultimate_pipeline.domain_gap.domain_gap_aggregator import DomainGapAggregator
E   ModuleNotFoundError: No module named 'ultimate_pipeline.domain_gap.domain_gap_aggregator'
_ ERROR collecting ultimate_pipeline/tests/unit/test_geo_alignment_rigid_scale_lock.py _
ImportError while importing test module 'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\ultimate_pipeline\tests\unit\test_geo_alignment_rigid_scale_lock.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ultimate_pipeline\tests\unit\test_geo_alignment_rigid_scale_lock.py:6: in <module>
    from ultimate_pipeline.domain_gap.geo_alignment import GeoAligner
E   ModuleNotFoundError: No module named 'ultimate_pipeline.domain_gap.geo_alignment'
_____ ERROR collecting tests/unit/test_geometric_continuity_migration.py ______
ImportError while importing test module 'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\tests\unit\test_geometric_continuity_migration.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\unit\test_geometric_continuity_migration.py:8: in <module>
    from ultimate_pipeline.quality.check_geometric_continuity import (
E   ModuleNotFoundError: No module named 'ultimate_pipeline.quality.check_geometric_continuity'
_______ ERROR collecting tests/unit/test_junction_connector_rebuild.py ________
ImportError while importing test module 'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\tests\unit\test_junction_connector_rebuild.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\unit\test_junction_connector_rebuild.py:8: in <module>
    from ultimate_pipeline.topology.junction_connector_rebuild import (
E   ModuleNotFoundError: No module named 'ultimate_pipeline.topology.junction_connector_rebuild'
___________ ERROR collecting tests/unit/test_stage6_containment.py ____________
ImportError while importing test module 'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\tests\unit\test_stage6_containment.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\unit\test_stage6_containment.py:10: in <module>
    from ultimate_pipeline.geometry.planview_smoother import PlanViewSmoother
E   ModuleNotFoundError: No module named 'ultimate_pipeline.geometry.planview_smoother'
________ ERROR collecting tests/unit/test_stage6_unsafe_flag_policy.py ________
ImportError while importing test module 'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\tests\unit\test_stage6_unsafe_flag_policy.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\unit\test_stage6_unsafe_flag_policy.py:5: in <module>
    from ultimate_pipeline.config.settings import Settings
ultimate_pipeline\config\settings.py:25: in <module>
    from ultimate_pipeline.utils.paths import repo_root, city_dir, resolve_path
E   ModuleNotFoundError: No module named 'ultimate_pipeline.utils.paths'
=========================== short test summary info ===========================
ERROR ultimate_pipeline/tests/unit/test_curvature_gap_parampoly3.py
ERROR ultimate_pipeline/tests/unit/test_elevation_gap.py
ERROR ultimate_pipeline/tests/unit/test_geo_alignment_rigid_scale_lock.py
ERROR tests/unit/test_geometric_continuity_migration.py
ERROR tests/unit/test_junction_connector_rebuild.py
ERROR tests/unit/test_stage6_containment.py
ERROR tests/unit/test_stage6_unsafe_flag_policy.py
!!!!!!!!!!!!!!!!!!! Interrupted: 7 errors during collection !!!!!!!!!!!!!!!!!!!
============================== 7 errors in 0.82s ==============================
```

### geometry_scaffold_optimized

```text
============================= test session starts =============================
platform win32 -- Python 3.12.2, pytest-9.0.1, pluggy-1.6.0
rootdir: C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main
configfile: pytest.ini
plugins: anyio-4.12.1
collected 2280 items

tests\opendrive_geometry\test_arc.py ....................                [  0%]
tests\opendrive_geometry\test_existing_implementations.py .............. [  1%]
........................................................................ [  4%]
........................................................................ [  7%]
........................................................................ [ 10%]
........................................................................ [ 14%]
........................................................................ [ 17%]
........................................................................ [ 20%]
........................................................................ [ 23%]
.........................................ssssss......................... [ 26%]
.....................................................ssssss............. [ 29%]
.................................................................ssssss. [ 33%]
........................................................................ [ 36%]
.....ssssss............................................................. [ 39%]
.................ssssss................................................. [ 42%]
.............................ssssss..................................... [ 45%]
.........................................ssssss......................... [ 48%]
.....................................................ssssss............. [ 52%]
.................................................................ssssss. [ 55%]
........................................................................ [ 58%]
.....ssssss............................................................. [ 61%]
.................ssssss................................................. [ 64%]
.............................ssssss..................................... [ 67%]
.........................................ssssss........                  [ 70%]
tests\opendrive_geometry\test_line.py ................                   [ 70%]
tests\opendrive_geometry\test_near_zero_curvature.py ................... [ 71%]
........................................................................ [ 74%]
........................................................................ [ 78%]
........................................................................ [ 81%]
........................................................................ [ 84%]
........................................................................ [ 87%]
........................................................................ [ 90%]
........................................................................ [ 93%]
..............................................................           [ 96%]
tests\opendrive_geometry\test_s_domain.py .............................. [ 97%]
........................                                                 [ 98%]
tests\opendrive_geometry\test_sampling.py ...............                [ 99%]
tests\opendrive_geometry\test_transform_invariance.py .........          [100%]

============================== warnings summary ===============================
.venv\Lib\site-packages\_pytest\config\__init__.py:1273
  C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\.venv\Lib\site-packages\_pytest\config\__init__.py:1273: PytestConfigWarning: assertions not in test modules or plugins will be ignored because assert statements are not executed by the underlying Python interpreter (are you using python -O?)

    self._warn_about_missing_assertion(mode)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 2202 passed, 78 skipped, 1 warning in 6.92s =================
```
