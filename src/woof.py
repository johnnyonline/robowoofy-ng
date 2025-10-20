from .config import SAFE
from .sign import sign
from .utils import load_contract

@sign()
def woofy():
    # Instantiate contracts with `load_contract`
    ycrv = load_contract("0xFCc5c47bE19d06BF83eB04298b026F81069ff65b")
    ybs = load_contract("0xE9A115b77A1057C918F997c32663FdcE24FB873f")

    # Reference our Safe with `SAFE`
    balance = ycrv.balanceOf(SAFE)
    print(f"Our yCRV balance: {balance / 1e18:.4f}")

    # Approve YBS to pull our yCRV
    ycrv.approve(ybs.address, balance)
    print("Approved!")

    # Stake yCRV into YBS
    ybs.stake(balance)
    print("Staked!")