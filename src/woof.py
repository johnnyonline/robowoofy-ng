from .config import SAFE
from .sign import sign
from .utils import load_contract


# @todo
# (1) cleanup README etc
# (2) remove ruff and mypy
# (3) put yearn stuff in things (yfi, config.py, etc)
@sign()
def woofy():
    dai = load_contract("0xD533a949740bb3306d119CC777fa900bA034cd52")
    zap = load_contract("0x094d12e5b541784701FD8d65F11fc0598FBC6332")

    dai_amount = dai.balanceOf(SAFE)
    print(f"💰 DAI balance: {dai_amount / 1e18:.4f}")

    print("⚙️ Approving zap...")
    dai.approve(zap.address, 420)
