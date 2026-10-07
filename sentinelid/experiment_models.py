"""Fixed family ablations and chronologically held-out supervised relevance scores."""

import itertools
import json
import os

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .experiment_features import PEER, TEMPORAL
from .experiment_io import digest, fingerprint, save_json

RANK_FIELDS = [
    "percentile:usb_change_7",
    "percentile:copy_change_7",
    "magnitude:usb_change_7",
    "magnitude:copy_change_7",
    "magnitude:after_hours_change_1",
    "magnitude:external_email_change_1",
    "timing_novel_share",
]
CHOICES = {
    "detector": ("rf", "if"),
    "representation_extension": ("off", "temporal_v1"),
    "peer_context": ("off", "historical_v1"),
    "ranking": ("detector_score", "relevance_v1"),
}


def configurations(config):
    for key, options in CHOICES.items():
        if key not in config:
            raise ValueError("Missing experiment option: " + key)
        value = config[key]
        values = [value] if isinstance(value, str) else value
        if not isinstance(values, list):
            raise ValueError("Experiment option must be a string or list: " + key)
        if not values or len(set(values)) != len(values) or any(v not in options for v in values):
            raise ValueError("Invalid experiment option: " + key)
    return [
        dict(zip(CHOICES, values, strict=True))
        for values in itertools.product(
            *([config[k]] if isinstance(config[k], str) else config[k] for k in CHOICES)
        )
    ]


def model_key(config):
    return f"{config['detector']}-t{int(config['representation_extension'] != 'off')}p{int(config['peer_context'] != 'off')}"


def feature_matrix(data, names, config):
    parts = [data["pm"]]
    result = list(names)
    if config["representation_extension"] != "off":
        parts.append(data["temporal"])
        result += ["temporal:" + k for k in TEMPORAL]
    if config["peer_context"] != "off":
        parts.append(data["peer"])
        result += PEER
    return np.concatenate(parts, axis=1), result


def fit_detector(x, y, family, protocol):
    if family == "rf":
        if len(set(y)) < 2 or min(y) < 0:
            raise ValueError("RF fitting needs both historical training classes")
        p = protocol["rf"]
        return RandomForestClassifier(
            n_estimators=p["trees"],
            max_depth=p["depth"],
            min_samples_leaf=p["minimum_leaf"],
            class_weight=p["class_weight"],
            random_state=p["seed"],
            n_jobs=1,
        ).fit(x, y)
    p = protocol["if"]
    return IsolationForest(
        n_estimators=p["trees"],
        max_samples=p["samples"],
        contamination="auto",
        random_state=p["seed"],
        n_jobs=1,
    ).fit(x)


def predict(model, x, family):
    return model.predict_proba(x)[:, 1] if family == "rf" else -model.score_samples(x)


def atomic_model(path, bundle):
    temporary = path.with_name(path.name + ".tmp")
    joblib.dump(bundle, temporary)
    os.replace(temporary, path)


def train(data, names, config, protocol, directory):
    key = model_key(config)
    output = directory / "models" / key
    output.mkdir(parents=True, exist_ok=True)
    marker = output / "manifest.json"
    if marker.exists():
        saved = json.loads(marker.read_text())
        for filename, checksum in saved["files"].items():
            if digest(output / filename) != checksum:
                raise ValueError("Fitted experiment artifact changed: " + filename)
        return saved
    x, input_names = feature_matrix(data, names, config)
    if not np.isfinite(x).all():
        raise ValueError("Nonfinite detector input")
    days = np.asarray([k[0] for k in data["keys"]])
    family = config["detector"]
    fit = (days >= protocol["fit_start"]) & (days < protocol["fit_end"])
    cal = (days >= protocol["calibration_start"]) & (days < protocol["calibration_end"])
    oof = np.full(len(days), np.nan)
    blocks = []
    cutoffs = protocol["oof_cutoffs"]
    for i, cutoff in enumerate(cutoffs):
        end = cutoffs[i + 1] if i + 1 < len(cutoffs) else protocol["fit_end"]
        historical = (days >= protocol["fit_start"]) & (days < cutoff)
        held_out = (days >= cutoff) & (days < end)
        model = fit_detector(x[historical], data["label"][historical], family, protocol)
        oof[held_out] = predict(model, x[held_out], family)
        filename = f"oof-{i}.joblib"
        atomic_model(
            output / filename,
            {
                "model": model,
                "names": input_names,
                "feature_contract": "behavior-experiment-v1",
                "fit_start": protocol["fit_start"],
                "fit_end": cutoff,
                "predict_start": cutoff,
                "predict_end": end,
            },
        )
        blocks.append(
            {
                "fit_end": cutoff,
                "prediction_end": end,
                "fit_rows": int(historical.sum()),
                "held_out_rows": int(held_out.sum()),
                "model_sha256": digest(output / filename),
            }
        )
    final = fit_detector(x[fit], data["label"][fit], family, protocol)
    scores = predict(final, x, family)
    gate = float(np.quantile(scores[fit], protocol["gate_quantile"]))
    atomic_model(
        output / "detector.joblib",
        {
            "model": final,
            "detector": family,
            "names": input_names,
            "feature_contract": "behavior-experiment-v1",
            "gate": gate,
            "fit_period": [protocol["fit_start"], protocol["fit_end"]],
        },
    )
    rank_fields = ["detector_score"] + RANK_FIELDS
    rank_indices = [input_names.index(k) for k in RANK_FIELDS]
    if config["representation_extension"] != "off":
        rank_fields += ["temporal:" + k for k in TEMPORAL]
        rank_indices += [input_names.index("temporal:" + k) for k in TEMPORAL]
    if config["peer_context"] != "off":
        rank_fields += PEER
        rank_indices += [input_names.index(k) for k in PEER]
    held = np.isfinite(oof) & fit
    rank_x = np.column_stack([oof[held], x[held][:, rank_indices]])
    rank_y = data["relevance"][held]
    if (rank_y < 0).any():
        raise ValueError("Unavailable historical ranking label")
    priorities = np.full(len(days), np.nan)
    rank_status = "unavailable"
    if len(set(rank_y)) == 2:
        p = protocol["ranker"]
        ranker = make_pipeline(
            StandardScaler(),
            LogisticRegression(
                C=p["C"],
                class_weight=p["class_weight"],
                random_state=p["seed"],
                solver="lbfgs",
                max_iter=2000,
            ),
        )
        ranker.fit(rank_x, rank_y)
        priorities = ranker.predict_proba(np.column_stack([scores, x[:, rank_indices]]))[:, 1]
        atomic_model(
            output / "ranker.joblib",
            {
                "model": ranker,
                "names": rank_fields,
                "target": "Labelled malicious record in available seven-day context",
                "oof_blocks": blocks,
                "feature_contract": "behavior-experiment-v1",
            },
        )
        rank_status = "available"
    temporary = output / "scores.tmp"
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, detector=scores, priority=priorities, oof=oof)
    os.replace(temporary, output / "scores.npz")
    result = {
        "model_key": key,
        "feature_contract": "behavior-experiment-v1",
        "config": {k: config[k] for k in CHOICES if k != "ranking"},
        "input_names": input_names,
        "ranking_input_names": rank_fields,
        "gate": gate,
        "fitting_period": [protocol["fit_start"], protocol["fit_end"]],
        "fit_rows": int(fit.sum()),
        "fit_vector_sha256": fingerprint(
            {"x": __import__("hashlib").sha256(x[fit].tobytes()).hexdigest(), "names": input_names}
        ),
        "calibration_period": [protocol["calibration_start"], protocol["calibration_end"]],
        "calibration_rows": int(cal.sum()),
        "calibration_gate_exceedance": float(np.mean(scores[cal] >= gate)),
        "ranking_status": rank_status,
        "ranking_rows": int(held.sum()),
        "ranking_positive_rows": int(rank_y.sum()),
        "oof_blocks": blocks,
        "ranking_labels": "Historical training only; no reviews or evaluation labels",
        "label_access": "Supervised RF"
        if family == "rf"
        else "Label-free IF; learned ranking is supervised assistance",
    }
    result["files"] = {
        p.name: digest(p)
        for p in output.iterdir()
        if p.is_file() and p.suffix in (".joblib", ".npz")
    }
    save_json(marker, result)
    return result
