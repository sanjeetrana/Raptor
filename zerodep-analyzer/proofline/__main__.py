"""Allow `python -m proofline` invocation."""
from .cli import main
import sys

sys.exit(main())
