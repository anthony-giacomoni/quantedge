# ============================================================
#  QuantEdge — Central configuration
# ============================================================

from pathlib import Path
import os
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# API keys are read locally from .env (ignored by Git).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
EODHD_API_KEY = os.getenv("EODHD_API_KEY", "")

# Local/private data paths. The public repository can run without these files.
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = str(DATA_DIR / "quantedge.db")
DCA_PATH = str(DATA_DIR / "simu_invest.xlsm")
DCA_XLSX_PATH = str(DATA_DIR / "simu_invest.xlsx")
DCA_DEMO_PATH = str(PROJECT_ROOT / "examples" / "simu_invest_demo.xlsx")

# Claude configuration.
CLAUDE_MODEL = "claude-sonnet-5"
CLAUDE_MAX_TOKENS = 1500
