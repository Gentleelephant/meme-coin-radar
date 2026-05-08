"""
Test output contract validation functions.

These functions are pure logic extracted from auto-run.py.
Tests validate required field checking and contract version compatibility.
"""


# --- Pure function copies from auto-run.py (no imports needed) ---

REQUIRED_CANDIDATE_FIELDS = ["symbol", "final_score", "oos", "ers", "decision", "direction"]
SUPPORTED_CONTRACT_VERSIONS = {"1.0"}


def validate_candidate(item: dict, path: str) -> list[str]:
    """Validate a single candidate has all required fields."""
    errors: list[str] = []
    for field in REQUIRED_CANDIDATE_FIELDS:
        if field not in item or item[field] is None:
            errors.append(f"{path}: missing required field '{field}'")
    return errors


def validate_output(data: list[dict]) -> tuple[bool, list[str]]:
    """Validate the output data has required field integrity."""
    errors: list[str] = []
    if not isinstance(data, list):
        errors.append("root: expected list of candidates")
        return False, errors

    for i, item in enumerate(data):
        item_errors = validate_candidate(item, f"candidates[{i}]")
        errors.extend(item_errors)

    return len(errors) == 0, errors


def check_contract_compatibility(version: str | None) -> bool:
    """Check if a contract version is compatible with the current output contract."""
    if version is None or version == "0.9":
        return False  # Pre-contract versions
    return version in SUPPORTED_CONTRACT_VERSIONS


# --- Tests ---

def test_validate_candidate_valid():
    """Test valid candidate passes validation."""
    candidate = {
        "symbol": "PEPEUSDT",
        "final_score": 62,
        "oos": 70,
        "ers": 65,
        "decision": "recommend_paper_trade",
        "direction": "long",
    }
    errors = validate_candidate(candidate, "candidates[0]")
    assert errors == []


def test_validate_candidate_missing_field():
    """Test candidate missing required field fails validation."""
    candidate = {
        "symbol": "PEPEUSDT",
        "final_score": 62,
    }
    errors = validate_candidate(candidate, "candidates[0]")
    assert len(errors) == 4
    assert any("ers" in e for e in errors)
    assert any("direction" in e for e in errors)


def test_validate_candidate_null_field():
    """Test candidate with null required field fails validation."""
    candidate = {
        "symbol": "PEPEUSDT",
        "final_score": 62,
        "oos": 70,
        "ers": 65,
        "decision": "recommend_paper_trade",
        "direction": None,
    }
    errors = validate_candidate(candidate, "candidates[0]")
    assert len(errors) == 1
    assert "direction" in errors[0]


def test_validate_output_valid():
    """Test valid output list passes validation."""
    data = [{
        "symbol": "PEPEUSDT",
        "final_score": 62,
        "oos": 70,
        "ers": 65,
        "decision": "recommend_paper_trade",
        "direction": "long",
    }]
    valid, errors = validate_output(data)
    assert valid
    assert errors == []


def test_validate_output_non_list():
    """Test non-list data fails validation."""
    valid, errors = validate_output({"not": "a list"})  # type: ignore
    assert not valid
    assert any("expected list" in e for e in errors)


def test_validate_output_multiple_errors():
    """Test multiple validation errors reported correctly."""
    data = [
        {"symbol": "PEPEUSDT", "final_score": 62, "oos": 70, "ers": 65, "decision": "recommend_paper_trade", "direction": "long"},
        {"symbol": "DOGEUSDT", "final_score": 55},  # missing 4 fields
    ]
    valid, errors = validate_output(data)
    assert not valid
    assert len(errors) == 4  # 4 missing fields on candidate[1]


def test_check_contract_compatibility():
    """Test contract version compatibility checks."""
    assert check_contract_compatibility("1.0") is True
    assert check_contract_compatibility(None) is False
    assert check_contract_compatibility("0.9") is False
    assert check_contract_compatibility("0.0") is False
    assert check_contract_compatibility("2.0") is False


if __name__ == "__main__":
    test_validate_candidate_valid()
    print("✅ test_validate_candidate_valid passed")

    test_validate_candidate_missing_field()
    print("✅ test_validate_candidate_missing_field passed")

    test_validate_candidate_null_field()
    print("✅ test_validate_candidate_null_field passed")

    test_validate_output_valid()
    print("✅ test_validate_output_valid passed")

    test_validate_output_non_list()
    print("✅ test_validate_output_non_list passed")

    test_validate_output_multiple_errors()
    print("✅ test_validate_output_multiple_errors passed")

    test_check_contract_compatibility()
    print("✅ test_check_contract_compatibility passed")

    print("\n✅ All API contract tests passed!")