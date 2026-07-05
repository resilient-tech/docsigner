import sys
from pathlib import Path

# Make signer_host importable without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
