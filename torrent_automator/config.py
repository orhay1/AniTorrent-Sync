import yaml
from pathlib import Path

def load_config(path: str) -> dict:
    """
    Load a YAML config file and return it as a Python dictionary.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path, "r") as f:
        data = yaml.safe_load(f)

    # Optional: very basic validation
    required_keys = ["shows", "quality", "codec", "qbittorrent"]
    for key in required_keys:
        if key not in data:
            raise ValueError(f"Missing required config key: {key}")

    return data
