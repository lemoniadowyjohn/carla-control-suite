p = "tools/placement_control_anchor_assay.py"
s = open(p, encoding="utf-8").read()
subs = [
("""        _t_exp = []
        for _tw in tile_ways:
            _e = [ORACLE_FWD.transform(*p) for p in _tw["lonlat"]]""",
"""        _t_exp = []
        for _tw in tile_ways:
            _e = [centered.transform(*p) for p in _tw["lonlat"]]"""),
("""            _t_exp.append((sum(p[0] for p in _e) / len(_e) - ox,
                           sum(p[1] for p in _e) / len(_e) - oy))""",
"""            _t_exp.append((sum(p[0] for p in _e) / len(_e),
                           sum(p[1] for p in _e) / len(_e)))"""),
("""        _exp_all = []
        for _tw in tile_ways:
            _e = [ORACLE_FWD.transform(*p) for p in _tw["lonlat"]]
            _exp_all.append((sum(p[0] for p in _e) / len(_e) - ox,
                             sum(p[1] for p in _e) / len(_e) - oy))""",
"""        _exp_all = []
        for _tw in tile_ways:
            _e = [centered.transform(*p) for p in _tw["lonlat"]]
            _exp_all.append((sum(p[0] for p in _e) / len(_e),
                             sum(p[1] for p in _e) / len(_e)))"""),
("""        for tw, fw in pairs:
            ex = [(ORACLE_FWD.transform(*p)[0] - ox, ORACLE_FWD.transform(*p)[1] - oy) for p in tw["lonlat"]]""",
"""        for tw, fw in pairs:
            ex = [centered.transform(*p) for p in tw["lonlat"]]"""),
("""            _exs = [ORACLE_FWD.transform(*p) for p in tw["lonlat"]]
            _ecx = sum(p[0] for p in _exs) / len(_exs) - ox
            _ecy = sum(p[1] for p in _exs) / len(_exs) - oy""",
"""            _exs = [centered.transform(*p) for p in tw["lonlat"]]
            _ecx = sum(p[0] for p in _exs) / len(_exs)
            _ecy = sum(p[1] for p in _exs) / len(_exs)"""),
]
for i, (a, b) in enumerate(subs):
    assert a in s, f"pattern {i} not found"
    s = s.replace(a, b)
open(p, "w", encoding="utf-8").write(s)
print("patched all", len(subs))
