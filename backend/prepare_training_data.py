"""Prepare the supplied ThermoSense research files for a labeled model run.

The point-level source is raw-data-long-1-1km.csv. Overlapping copies are
validated and excluded. Trial-endpoint and unpaired files remain separate so
measurements from different time grains are never joined by row order.
"""
import argparse
import csv
import json
import math
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree

from sklearn.model_selection import GroupShuffleSplit
from sklearn.preprocessing import StandardScaler

FEATURES = ["body_temperature", "heart_rate", "ambient_temperature", "humidity"]
SOURCE_COLUMNS = {
    "body_temperature": "core_temp",
    "heart_rate": "heart_rate",
    "ambient_temperature": "dry_temp",
    "humidity": "relative_humidity",
}
BOUNDS = {
    "body_temperature": (30.0, 45.0),
    "heart_rate": (30.0, 240.0),
    "ambient_temperature": (-20.0, 65.0),
    "humidity": (0.0, 100.0),
}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            with path.open("r", encoding=encoding, newline="") as source:
                reader = csv.DictReader(source)
                return list(reader.fieldnames or []), list(reader)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode {path}")


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def finite_number(row: dict[str, str], column: str) -> float:
    value = float(row[column])
    if not math.isfinite(value):
        raise ValueError(f"{column} is not finite")
    return value


def feature_key(row: dict[str, str], columns: dict[str, str]) -> tuple[float, ...]:
    return tuple(round(finite_number(row, source), 3) for source in columns.values())


def prepare(source_dir: Path, output_dir: Path, labels_path: Path | None = None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    primary_path = source_dir / "raw-data-long-1-1km.csv"
    if not primary_path.exists():
        raise FileNotFoundError(f"Primary dataset not found: {primary_path}")
    primary_headers, source_rows = read_csv(primary_path)
    required = {"participant_number", "trial_number", "kilometer", *SOURCE_COLUMNS.values()}
    missing_columns = required - set(primary_headers)
    if missing_columns:
        raise ValueError(f"Primary dataset is missing columns: {sorted(missing_columns)}")

    records, excluded = [], []
    seen_record_ids = set()
    for source_row, row in enumerate(source_rows, start=2):
        record_id = f"{row['trial_number']}:{row['kilometer']}"
        try:
            record = {"record_id": record_id,
                      "participant_id": row["participant_number"].strip(),
                      "trial_id": int(row["trial_number"]),
                      "kilometer": float(row["kilometer"]),
                      "source_row": source_row}
            for output_name, source_name in SOURCE_COLUMNS.items():
                value = finite_number(row, source_name)
                low, high = BOUNDS[output_name]
                if not low <= value <= high:
                    raise ValueError(f"{output_name}={value} is outside [{low}, {high}]")
                record[output_name] = value
            if not record["participant_id"]:
                raise ValueError("participant_number is empty")
            if record_id in seen_record_ids:
                raise ValueError(f"duplicate trial/km key {record_id}")
            seen_record_ids.add(record_id)
            record["risk_level"] = ""
            records.append(record)
        except (KeyError, TypeError, ValueError) as error:
            excluded.append({"source_row": source_row, "record_id": record_id,
                             "reason": str(error)})

    if len(records) < 10:
        raise ValueError("Too few valid primary rows to create a useful split")
    label_counts = {}
    if labels_path:
        _, label_rows = read_csv(labels_path)
        if not label_rows or not {"record_id", "risk_level"}.issubset(label_rows[0]):
            raise ValueError("Labels file must contain record_id and risk_level columns")
        labels = {}
        for row in label_rows:
            key, label = row["record_id"].strip(), row["risk_level"].strip().upper()
            if not key or key in labels:
                raise ValueError(f"Blank or duplicate record_id in labels file: {key}")
            if label not in {"LOW", "MODERATE", "HIGH"}:
                raise ValueError(f"Unsupported risk_level for {key}: {label}")
            labels[key] = label
        record_ids = {record["record_id"] for record in records}
        if set(labels) != record_ids:
            raise ValueError("Labels file must contain exactly one label for every valid primary record")
        for record in records:
            record["risk_level"] = labels[record["record_id"]]
        label_counts = {label: sum(value == label for value in labels.values())
                        for label in ("LOW", "MODERATE", "HIGH")}
    x = [[record[name] for name in FEATURES] for record in records]
    groups = [record["participant_id"] for record in records]
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.20, random_state=42)
    train_idx, test_idx = next(splitter.split(x, groups=groups))
    train_rows = [records[int(i)] for i in train_idx]
    test_rows = [records[int(i)] for i in test_idx]
    train_groups = {record["participant_id"] for record in train_rows}
    test_groups = {record["participant_id"] for record in test_rows}
    if train_groups & test_groups:
        raise AssertionError("Participant leakage detected across the split")
    split_label_counts = {
        "train": {label: sum(row["risk_level"] == label for row in train_rows) for label in ("LOW", "MODERATE", "HIGH")},
        "test": {label: sum(row["risk_level"] == label for row in test_rows) for label in ("LOW", "MODERATE", "HIGH")},
    }
    all_classes_available = bool(labels_path) and all(label_counts.get(label, 0) > 0 for label in ("LOW", "MODERATE", "HIGH"))
    evaluation_classes_available = all_classes_available and all(
        split_label_counts[split][label] > 0
        for split in ("train", "test") for label in ("LOW", "MODERATE", "HIGH"))

    scaler = StandardScaler()
    scaler.fit([ [row[name] for name in FEATURES] for row in train_rows ])
    columns = ["record_id", "participant_id", "trial_id", "kilometer", "source_row"]
    columns += FEATURES + [f"{name}_z" for name in FEATURES] + ["risk_level"]
    prepared = []
    split_by_id = {row["record_id"]: "train" for row in train_rows}
    split_by_id.update({row["record_id"]: "test" for row in test_rows})
    for record in records:
        scaled = scaler.transform([[record[name] for name in FEATURES]])[0]
        output = dict(record, split=split_by_id[record["record_id"]])
        output.update({f"{name}_z": float(value) for name, value in zip(FEATURES, scaled)})
        prepared.append(output)
    write_csv(output_dir / "prepared_all.csv", ["split", *columns], prepared)
    write_csv(output_dir / "train.csv", columns, [r for r in prepared if r["split"] == "train"])
    write_csv(output_dir / "test.csv", columns, [r for r in prepared if r["split"] == "test"])
    write_csv(output_dir / "excluded_rows.csv", ["source_row", "record_id", "reason"], excluded)
    write_csv(output_dir / "risk_labels_template.csv",
              ["record_id", "participant_id", "trial_id", "kilometer", "risk_level"],
              [{**{key: record[key] for key in ("record_id", "participant_id", "trial_id", "kilometer")}, "risk_level": ""}
               for record in records])

    # Validate and retain one canonical trial-level endpoint table. The endcore
    # source has no trial ID, so row-to-trial mapping is accepted only if each
    # start and end temperature exactly matches the corresponding trial readings.
    endpoint_file = source_dir / "data-set1-endcore.csv"
    endpoint_headers, endpoints = read_csv(endpoint_file)
    long_by_trial: dict[int, list[dict[str, str]]] = {}
    for row in source_rows:
        long_by_trial.setdefault(int(row["trial_number"]), []).append(row)
    endpoint_rows = []
    trial_ids = sorted(long_by_trial)
    if len(endpoints) != len(trial_ids):
        raise ValueError("Endpoint rows cannot be mapped one-to-one to primary trials")
    for endpoint, trial_id in zip(endpoints, trial_ids):
        trial = sorted(long_by_trial[trial_id], key=lambda item: float(item["kilometer"]))
        if round(finite_number(endpoint, "Initial_TCORE_C"), 3) != round(finite_number(trial[0], "core_temp"), 3):
            raise ValueError(f"Endpoint start value does not match trial {trial_id}")
        if round(finite_number(endpoint, "EndTCORE"), 3) != round(finite_number(trial[-1], "core_temp"), 3):
            raise ValueError(f"Endpoint end value does not match trial {trial_id}")
        participants = {item["participant_number"] for item in trial}
        if len(participants) != 1:
            raise ValueError(f"Trial {trial_id} maps to multiple participants")
        endpoint_rows.append({"trial_id": trial_id, "participant_id": next(iter(participants)), **endpoint})

    # The other two endpoint files are alternate column selections of the same
    # 75 records. Verify their common fields before documenting them as overlap.
    endpoint_overlap = {}
    for variant in ("data-set2-endcore.csv", "data-set3-endcore.csv"):
        headers, rows = read_csv(source_dir / variant)
        common = [column for column in endpoint_headers if column in headers]
        if len(rows) != len(endpoints) or any(
            any(round(float(a[col]), 6) != round(float(b[col]), 6) for col in common)
            for a, b in zip(endpoints, rows)
        ):
            raise ValueError(f"{variant} does not match data-set1-endcore.csv")
        endpoint_overlap[variant] = {"rows": len(rows), "matching_shared_columns": common}
    write_csv(output_dir / "trial_endpoints.csv",
              ["trial_id", "participant_id", *endpoint_headers], endpoint_rows)

    # Confirm the 750-row file and aligned X/y pair are subsets, then exclude
    # those duplicate views from the point-level training table.
    primary_keys = {feature_key(row, SOURCE_COLUMNS) for row in source_rows}
    subset_checks = {}
    earlier_path = source_dir / "raw-data-long-1-1k-ua.csv"
    if earlier_path.exists():
        _, earlier_rows = read_csv(earlier_path)
        subset_checks[earlier_path.name] = {"rows": len(earlier_rows), "matched_primary_rows": sum(
            feature_key(row, SOURCE_COLUMNS) in primary_keys for row in earlier_rows)}
    wide_path = source_dir / "raw-data1-1km.csv"
    wide_headers, wide_rows = read_csv(wide_path)
    subset_checks[wide_path.name] = {"rows": len(wide_rows), "matched_primary_rows": sum(
        feature_key(row, SOURCE_COLUMNS) in primary_keys for row in wide_rows)}
    x_headers, x_rows = read_csv(source_dir / "X-data1-1km.csv")
    y_headers, y_rows = read_csv(source_dir / "y-data1-1km.csv")
    if len(x_rows) != len(y_rows):
        raise ValueError("X-data1-1km.csv and y-data1-1km.csv row counts differ")
    xy_rows = [{"core_temp": y["core_temp"], "heart_rate": x["heart_rate"],
                "dry_temp": x["dry_temp"], "relative_humidity": x["relative_humidity"]}
               for x, y in zip(x_rows, y_rows)]
    subset_checks["X-data1-1km.csv + y-data1-1km.csv"] = {
        "rows": len(xy_rows), "matched_primary_rows": sum(feature_key(row, SOURCE_COLUMNS) in primary_keys for row in xy_rows)}
    if any(check["rows"] != check["matched_primary_rows"] for check in subset_checks.values()):
        raise ValueError("An overlapping point-level source is not fully contained in the primary table")

    # Record the metadata sensor series as separate sources; they do not carry
    # a shared sample/time key and are therefore not row-wise joined.
    supplemental = [
        "Metadane_dataset/core temperature/core_temperature_data.csv",
        "Metadane_dataset/heart rate/heart_rate_data.csv",
        "Metadane_dataset/humidity/humidity_data.csv",
        "Metadane_dataset/skin temperature/skin_temperature_data.csv",
    ]
    source_manifest = []
    source_manifest.append({"file": primary_path.name, "rows": len(source_rows),
                            "disposition": "Primary point-level dataset; used once"})
    for name, check in subset_checks.items():
        source_manifest.append({"file": name, "rows": check["rows"],
                                "disposition": f"Overlapping subset; {check['matched_primary_rows']} rows match primary; not appended"})
    source_manifest.append({"file": "data-set1-endcore.csv", "rows": len(endpoints),
                            "disposition": "Linked to primary trial IDs by matching start and end core temperatures; kept at trial grain"})
    for name, check in endpoint_overlap.items():
        source_manifest.append({"file": name, "rows": check["rows"],
                                "disposition": "Alternate columns for same endpoint trials; not appended"})
    for rel in supplemental:
        headers, rows = read_csv(source_dir / rel)
        source_manifest.append({"file": rel, "rows": len(rows),
                                "disposition": "Unpaired sensor series; no common sample/time key; not joined"})

    workbook_path = source_dir / "Characteristics of the 21 male professional firefighters from SDIS 71 (Sa_ne-et-Loire, France).xlsx"
    with ZipFile(workbook_path) as workbook:
        xml = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    workbook_info = [sheet.attrib["name"] for sheet in xml.findall("main:sheets/main:sheet", namespace)]
    source_manifest.append({"file": workbook_path.name, "rows": f"{len(workbook_info)} sheets",
                            "disposition": "Multi-sheet AM/PM and pre/post study tables; separate trial grain; not joined"})
    write_csv(output_dir / "source_manifest.csv", ["file", "rows", "disposition"], source_manifest)

    scaler_data = {"method": "StandardScaler (z-score)", "fit_on": "training rows only",
                   "features": FEATURES,
                   "mean": {name: float(value) for name, value in zip(FEATURES, scaler.mean_)},
                   "scale": {name: float(value) for name, value in zip(FEATURES, scaler.scale_)}}
    (output_dir / "scaler.json").write_text(json.dumps(scaler_data, indent=2), encoding="utf-8")
    report = {
        "primary_source": primary_path.name,
        "valid_rows": len(records), "excluded_rows": len(excluded),
        "feature_columns": FEATURES,
        "risk_labels_present": False,
        "training_ready": evaluation_classes_available,
        "labels_source": str(labels_path) if labels_path else None,
        "risk_label_counts": label_counts,
        "split_risk_label_counts": split_label_counts if labels_path else None,
        "reason": (None if evaluation_classes_available else
                   "The supplied files contain continuous measurements but no LOW/MODERATE/HIGH target. Complete reviewed labels for every record and confirm all three classes occur in both participant-based splits before supervised training."),
        "split": {"method": "GroupShuffleSplit", "group": "participant_id", "test_size": 0.20,
                  "random_state": 42, "train_rows": len(train_rows), "test_rows": len(test_rows),
                  "train_participants": len(train_groups), "test_participants": len(test_groups),
                  "participant_overlap": len(train_groups & test_groups)},
        "overlapping_sources": subset_checks,
        "endpoint_rows": len(endpoint_rows),
        "endpoint_overlap_sources": endpoint_overlap,
        "firefighter_workbook_sheets": workbook_info,
        "standardization": scaler_data,
    }
    report["risk_labels_present"] = bool(labels_path)
    (output_dir / "preparation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path.home() / "Downloads",
                        help="Folder containing the supplied source files (default: ~/Downloads)")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parent / "data" / "processed",
                        help="Folder for prepared files")
    parser.add_argument("--labels-file", type=Path, default=None,
                        help="Optional CSV with record_id and reviewed LOW/MODERATE/HIGH risk_level")
    args = parser.parse_args()
    result = prepare(args.source_dir, args.output_dir, args.labels_file)
    print(json.dumps({key: result[key] for key in (
        "valid_rows", "excluded_rows", "risk_labels_present", "training_ready", "split", "endpoint_rows")}, indent=2))
