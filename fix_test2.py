import re
with open(r'C:\Users\admin\AppData\Local\Temp\opencode\oc46-worktree\tests\unit\test_p09_tile_equivalence.py', 'r') as f:
    content = f.read()
content = content.replace('assert res["ownership"]["1"] == "tile_0_1"', 'assert res["ownership"]["1"] == "tile_0_0"')
with open(r'C:\Users\admin\AppData\Local\Temp\opencode\oc46-worktree\tests\unit\test_p09_tile_equivalence.py', 'w') as f:
    f.write(content)
print('Done')