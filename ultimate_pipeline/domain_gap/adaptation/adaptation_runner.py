from __future__ import annotations
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from .coral import apply_coral
from .mmd import apply_mmd


class DomainAdaptation:
    """
    Unified CORAL + MMD adaptation pipeline.
    """

    def run(self, feature_data, labels):
        cities = list(feature_data.keys())
        results = {}

        for src in cities:
            results[src] = {}
            for tgt in cities:
                if src == tgt:
                    continue

                Xs = feature_data[src]
                Xt = feature_data[tgt]
                ys = labels[src]
                yt = labels[tgt]

                # equalize sample sizes
                n = min(len(Xs), len(Xt), 100)
                Xs, Xt = Xs[:n], Xt[:n]
                ys, yt = ys[:n], yt[:n]

                city_result = {}

                # baseline
                city_result["baseline"] = self._eval(Xs, ys, Xt, yt)

                # coral
                Xs_coral = apply_coral(Xs, Xt)
                city_result["CORAL"] = self._eval(Xs_coral, ys, Xt, yt)

                # mmd
                Xs_mmd, Xt_mmd = apply_mmd(Xs, Xt)
                city_result["MMD"] = self._eval(Xs_mmd, ys, Xt_mmd, yt)

                results[src][tgt] = city_result

        return results

    @staticmethod
    def _eval(Xs, ys, Xt, yt):
        X_train, X_test, y_train, y_test = train_test_split(
            Xt, yt, test_size=0.3, random_state=42, stratify=yt
        )
        clf = RandomForestClassifier(n_estimators=50, random_state=4)
        clf.fit(Xs, ys)
        return float(clf.score(X_test, y_test))
