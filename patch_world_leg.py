import re

p = "tools/placement_control_anchor_assay.py"
s = open(p, encoding="utf-8").read()

old = """        if _bldg_idx:
            V_bldg = V[_bldg_idx]
            _W = V_bldg + np.array([ox - REBASE[0], oy - REBASE[1]])
            _mc = []
            for _wid, _cn in mor_idx.items():
                _sel = _cn[(_cn[:, 0] >= _x0 - 1) & (_cn[:, 0] < _x0 + TILE_SIZE_M + 1)
                           & (_cn[:, 1] >= _y0 - 1) & (_cn[:, 1] < _y0 + TILE_SIZE_M + 1)]
                if len(_sel):
                    _mc.append(_sel)
            if _mc:
                from scipy.spatial import cKDTree as _KD
                _MC = np.vstack(_mc)
                _sMC = _MC[::max(1, len(_MC) // 400)]
                _sW = _W[::max(1, len(_W) // 400)]
                _wcov_a = _KD(_W).query(_sMC)[0].tolist()
                _wcov_b = _KD(_W).query(_sW)[0].tolist()"""

new = """        if _bldg_idx:
            V_bldg = V[_bldg_idx]
            # Tile center offset in XODR-local: (ox, oy) from bare tmerc minus REBASE
            tile_cx = ox - REBASE[0]
            tile_cy = oy - REBASE[1]
            # MoR corners in tile-centered frame: subtract tile center offset
            _mc = []
            for _wid, _cn in mor_idx.items():
                _sel = _cn.copy()
                _sel[:, 0] -= ox - REBASE[0]
                _sel[:, 1] -= oy - REBASE[1]
                if len(_sel):
                    _mc.append(_sel)
            if _mc:
                from scipy.spatial import cKDTree as _KD
                _MC = np.vstack(_mc)
                _sMC = _MC[::max(1, len(_MC) // 400)]
                _sV = V_bldg[::max(1, len(V_bldg) // 400)]
                _wcov_a = _KD(V_bldg).query(_sMC)[0].tolist()
                _wcov_b = _KD(_MC).query(V_bldg)[0].tolist()"""

assert s.count("if _bldg_idx:") == 1
s = s.replace(
    """        if _bldg_idx:
            V_bldg = V[_bldg_idx]
            _W = V_bldg + np.array([ox - REBASE[0], oy - REBASE[1]])
            _mc = []
            for _wid, _cn in mor_idx.items():
                _sel = _cn[(_cn[:, 0] >= _x0 - 1) & (_cn[:, 0] < _x0 + TILE_SIZE_M + 1)
                           & (_cn[:, 1] >= _y0 - 1) & (_cn[:, 1] < _y0 + TILE_SIZE_M + 1)]
                if len(_sel):
                    _mc.append(_sel)
            if _mc:
                from scipy.spatial import cKDTree as _KD
                _MC = np.vstack(_mc)
                _sMC = _MC[::max(1, len(_MC) // 400)]
                _sW = _W[::max(1, len(_W) // 400)]
                _wcov_a = _KD(_W).query(_sMC)[0].tolist()
                _wcov_b = _KD(_W).query(_sW)[0].tolist()""",
    """        if _bldg_idx:
            V_bldg = V[_bldg_idx]
            # Tile center offset in XODR-local: (ox, oy) from bare tmerc minus REBASE
            tile_cx = ox - REBASE[0]
            tile_cy = oy - REBASE[1]
            # MoR corners in tile-centered frame: subtract tile center offset
            _mc = []
            for _wid, _cn in mor_idx.items():
                _sel = _cn.copy()
                _sel[:, 0] -= ox - REBASE[0]
                _sel[:, 1] -= oy - REBASE[1]
                if len(_sel):
                    _mc.append(_sel)
            if _mc:
                from scipy.spatial import cKDTree as _KD
                _MC = np.vstack(_mc)
                _sMC = _MC[::max(1, len(_MC) // 400)]
                _sV = V_bldg[::max(1, len(V_bldg) // 400)]
                _wcov_a = _KD(V_bldg).query(_sMC)[0].tolist()
                _wcov_b = _KD(_MC).query(V_bldg)[0].tolist()""")

open("tools/placement_control_anchor_assay.py", "w", encoding="utf-8").write(s)
print("patched")