"""CSV contracts, preflight validation, and deterministic demo data."""

import csv
import io
import math
import random


CUSTOMER_COLUMNS = ("customer_id", "latitude", "longitude", "demand")
STORE_COLUMNS = ("store_id", "latitude", "longitude", "fixed_cost", "capacity")
DEFAULT_CHENNAI_BOUNDS = (12.80, 13.20, 80.10, 80.30)
MAX_VALIDATION_ERRORS = 100


class InputValidationError(ValueError):
    """Raised when uploaded CSV data violates the documented input contract."""

    def __init__(self, errors):
        self.errors = tuple(errors)
        super().__init__("\n".join(self.errors))


def _decode_csv(content):
    if isinstance(content, bytes):
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise InputValidationError(["CSV must use UTF-8 encoding."]) from error
    if isinstance(content, str):
        return content.lstrip("\ufeff")
    if hasattr(content, "getvalue"):
        return _decode_csv(content.getvalue())
    raise InputValidationError(["CSV input must be text, bytes, or an uploaded file."])


def _parse_csv(content, required_columns, id_column, numeric_columns, bounds):
    text = _decode_csv(content)
    if not text.strip():
        raise InputValidationError(["CSV is empty."])

    try:
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames
        if not headers:
            raise InputValidationError(["CSV header row is missing."])

        errors = []
        if len(headers) != len(set(headers)):
            errors.append("CSV contains duplicate column names.")
        missing = [column for column in required_columns if column not in headers]
        if missing:
            errors.append(f"Missing required columns: {', '.join(missing)}.")
        if errors:
            raise InputValidationError(errors)

        parsed_rows = []
        seen_ids = set()
        for row_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                errors.append(f"Row {row_number}: more values than header columns.")
                continue
            if not any((value or "").strip() for value in raw_row.values()):
                continue

            row = {}
            identifier = (raw_row.get(id_column) or "").strip()
            if not identifier:
                errors.append(f"Row {row_number}: {id_column} is required.")
            elif identifier in seen_ids:
                errors.append(f"Row {row_number}: duplicate {id_column} '{identifier}'.")
            else:
                seen_ids.add(identifier)
                row[id_column] = identifier

            row_has_error = False
            for column in numeric_columns:
                raw_value = (raw_row.get(column) or "").strip()
                try:
                    value = float(raw_value)
                    if not math.isfinite(value):
                        raise ValueError
                except ValueError:
                    errors.append(f"Row {row_number}: {column} must be a finite number.")
                    row_has_error = True
                    continue

                if column in ("latitude", "longitude"):
                    lower, upper = (-90, 90) if column == "latitude" else (-180, 180)
                    if not lower <= value <= upper:
                        errors.append(f"Row {row_number}: {column} must be between {lower} and {upper}.")
                        row_has_error = True
                    elif bounds is not None:
                        min_lat, max_lat, min_lon, max_lon = bounds
                        within_region = (
                            min_lat <= value <= max_lat
                            if column == "latitude"
                            else min_lon <= value <= max_lon
                        )
                        if not within_region:
                            errors.append(
                                f"Row {row_number}: {column}={value:g} is outside the configured region bounds."
                            )
                            row_has_error = True
                elif value < 0:
                    errors.append(f"Row {row_number}: {column} cannot be negative.")
                    row_has_error = True

                row[column] = value

            if not row_has_error and id_column in row:
                parsed_rows.append(row)

            if len(errors) >= MAX_VALIDATION_ERRORS:
                errors.append("Further validation errors omitted; correct these rows and upload again.")
                break

        if errors:
            raise InputValidationError(errors)
        if not parsed_rows:
            raise InputValidationError(["CSV has a header but no valid data rows."])
        return parsed_rows
    except csv.Error as error:
        raise InputValidationError([f"CSV could not be parsed: {error}"]) from error


def validate_customers_csv(content, bounds=DEFAULT_CHENNAI_BOUNDS):
    """Parse customer CSV bytes/text and validate schema, values, IDs, and bounds."""
    return _parse_csv(
        content,
        CUSTOMER_COLUMNS,
        "customer_id",
        ("latitude", "longitude", "demand"),
        bounds,
    )


def validate_stores_csv(content, bounds=DEFAULT_CHENNAI_BOUNDS):
    """Parse candidate-store CSV bytes/text and validate schema and values."""
    return _parse_csv(
        content,
        STORE_COLUMNS,
        "store_id",
        ("latitude", "longitude", "fixed_cost", "capacity"),
        bounds,
    )


def validate_instance_capacity(customers, stores, max_open_stores=None):
    """Check necessary aggregate capacity conditions before distance/API work."""
    errors = []
    if not customers:
        errors.append("At least one customer is required.")
    if not stores:
        errors.append("At least one candidate store is required.")
    if errors:
        raise InputValidationError(errors)

    total_demand = sum(customer["demand"] for customer in customers)
    capacities = sorted((store["capacity"] for store in stores), reverse=True)
    total_capacity = sum(capacities)
    if total_capacity < total_demand:
        errors.append(
            f"Aggregate store capacity ({total_capacity:g}) is below total demand ({total_demand:g})."
        )

    if max_open_stores is not None:
        if isinstance(max_open_stores, bool) or not isinstance(max_open_stores, int):
            errors.append("Maximum open-store limit must be a whole number.")
        elif max_open_stores < 1:
            errors.append("Maximum open-store limit must be at least one.")
        elif max_open_stores > len(stores):
            errors.append("Maximum open-store limit cannot exceed the number of candidates.")
        elif sum(capacities[:max_open_stores]) < total_demand:
            errors.append(
                f"The {max_open_stores} highest-capacity stores cannot meet total demand."
            )

    if errors:
        raise InputValidationError(errors)
    return {"total_demand": total_demand, "total_capacity": total_capacity}


def generate_demo_data(n_customers=1000, n_stores=20, seed=42, bounds=DEFAULT_CHENNAI_BOUNDS):
    """Create deterministic synthetic demand and candidate locations in Chennai bounds."""
    if n_customers < 1 or n_stores < 1:
        raise ValueError("Customer and candidate-store counts must both be positive.")

    min_lat, max_lat, min_lon, max_lon = bounds
    if not (min_lat < max_lat and min_lon < max_lon):
        raise ValueError("Geographic bounds must have increasing minimum and maximum values.")

    rng = random.Random(seed)
    centers = (
        (13.08, 80.27),
        (13.04, 80.22),
        (13.11, 80.20),
        (12.98, 80.25),
        (13.15, 80.25),
        (13.02, 80.15),
    )
    lat_margin = min(0.012, (max_lat - min_lat) / 4)
    lon_margin = min(0.015, (max_lon - min_lon) / 4)

    customers = []
    for index in range(n_customers):
        center_lat, center_lon = centers[index % len(centers)]
        latitude = min(max(center_lat + rng.uniform(-lat_margin, lat_margin), min_lat), max_lat)
        longitude = min(max(center_lon + rng.uniform(-lon_margin, lon_margin), min_lon), max_lon)
        customers.append({
            "customer_id": str(index + 1),
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "demand": float(rng.randint(5, 25)),
        })

    total_demand = sum(customer["demand"] for customer in customers)
    capacity_per_store = math.ceil(total_demand / min(n_stores, 2) * 1.1)
    stores = []
    for index in range(n_stores):
        center_lat, center_lon = centers[index % len(centers)]
        latitude = min(max(center_lat + rng.uniform(-lat_margin, lat_margin), min_lat), max_lat)
        longitude = min(max(center_lon + rng.uniform(-lon_margin, lon_margin), min_lon), max_lon)
        stores.append({
            "store_id": str(index + 1),
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "fixed_cost": float(rng.randint(1200, 3200)),
            "capacity": float(capacity_per_store),
        })

    return customers, stores