import re
with open(r'C:\Users\admin\AppData\Local\Temp\opencode\oc46-worktree\tests\unit\test_p09_tile_equivalence.py', 'r') as f:
    content = f.read()
# Fix midpoint_policy - expect tile_0_1 because midpoint at x=50 falls in tile_0_1 (half-open [50, 100))
content = content.replace('assert res["ownership"]["1"] == "tile_0_0"', 'assert res["ownership"]["1"] == "tile_0_1"', 1)
with open(r'C:\Users\admin\AppData\Local\Temp\opencode\oc46-worktree\tests\unit\test_p09_tile_equivalence.py', 'w') as f:
    f.write(content)
print('Done')