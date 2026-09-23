import yaml
def load_manifest(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)
