from .config import SAFE
from .sign import sign
from .utils import load_contract


@sign()
def woofy():
    dai = load_contract("0x6B175474E89094C44Da98b954EedeAC495271d0F")
    zap = load_contract("0x094d12e5b541784701FD8d65F11fc0598FBC6332")

    dai_amount = dai.balanceOf(SAFE)
    print(f"💰 DAI balance: {dai_amount / 1e18:.4f}")

    print("⚙️ Approving zap...")
    dai.approve(zap, 420)
