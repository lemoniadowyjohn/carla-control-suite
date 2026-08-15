from __future__ import annotations
from .coral import apply_coral
from .mmd import apply_mean_matching


class DomainAdaptation:
    """
    Unified CORAL + mean-matching adaptation pipeline.
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
                Xs_coral, Xt_coral = apply_coral(Xs, Xt)
                city_result["CORAL"] = self._eval(Xs_coral, ys, Xt_coral, yt)

                # mean matching; this is intentionally not labeled as kernel MMD.
                Xs_mm, Xt_mm = apply_mean_matching(Xs, Xt)
                city_result["mean_matching"] = self._eval(Xs_mm, ys, Xt_mm, yt)

                results[src][tgt] = city_result

        return results

    @staticmethod
    def _eval(Xs, ys, Xt, yt):
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split

        X_train, X_test, y_train, y_test = train_test_split(
            Xt, yt, test_size=0.3, random_state=42, stratify=yt
        )
        clf = RandomForestClassifier(n_estimators=50, random_state=4)
        clf.fit(Xs, ys)
        return float(clf.score(X_test, y_test))
