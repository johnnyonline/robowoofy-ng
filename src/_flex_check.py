# TEMPORARY fork check for src/flex.py -- delete before committing
import time

from brownie import accounts, chain, web3
from eth_abi import encode

from . import flex
from .config import SAFE
from .helpers import enso_route
from .utils import load_contract

E = 10**18
DADDY = "0x4e8341C77c94cCE982AB96d92BB28D69f4638290"
REGISTRY = "0x9117440a7D03238905d1C8908157Bd7a547c77c8"
TM = "0x5fF405CC51705D609F7F2CCc2Bb36a66675938fC"  # wstETH / WETH
WSTETH = "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0"
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
UNI_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"  # uniswap v3 SwapRouter (stands in for Enso)
UNI_QUOTER = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"


def _selector(sig):
    return bytes(web3.keccak(text=sig)[:4])


def _fund():
    whale = accounts[0]
    whale.transfer(WSTETH, 300 * E)
    whale.transfer(WETH, 300 * E)
    for token in [WSTETH, WETH]:
        bal = load_contract(token, from_abi=True).balanceOf(whale)
        data = "0x" + (_selector("transfer(address,uint256)") + encode(["address", "uint256"], [SAFE.address, bal])).hex()
        whale.transfer(token, 0, data=data)


def _weth():
    return load_contract(WETH, from_abi=True).balanceOf(SAFE)


def _wsteth():
    return load_contract(WSTETH, from_abi=True).balanceOf(SAFE)


def _trove(tm, trove_id, tag):
    t = tm.troves(trove_id)
    print(
        f"[{tag}] debt={tm.get_trove_debt_after_interest(trove_id) / E:.4f} coll={t['collateral'] / E:.4f} "
        f"rate={t['annual_interest_rate'] / 1e16}% status={t['status']}"
    )


def check_troves():
    _fund()
    tm = load_contract(TM)
    dd = load_contract(tm.dutch_desk())
    lender = tm.lender()
    one_pct = tm.one_pct()

    flex.deposit(lender, 100 * E)
    a = flex.open_trove(TM, 50 * E, 20 * E, 2 * one_pct, owner_index=0)
    flex.add_collateral(TM, a, 5 * E)
    flex.remove_collateral(TM, a, 5 * E)
    flex.adjust_interest_rate(TM, a, 3 * one_pct)
    _trove(tm, a, "A")

    # B borrows more than idle --> redeems A, and the Safe takes the auction in kind
    idle = load_contract(WETH, from_abi=True).balanceOf(lender)
    weth_before, wsteth_before = _weth(), _wsteth()
    nonce = dd.nonce()
    b = flex.open_trove(TM, 120 * E, 90 * E, 5 * one_pct, owner_index=1, take_auction=True)
    auction = load_contract(dd.auction())
    weth_delta = _weth() - weth_before
    print(
        f"in-kind take: kicked={dd.nonce() == nonce + 1} left={auction.get_available_amount(nonce)} "
        f"weth_delta={weth_delta / E:.6f} (idle was {idle / E:.6f}) "
        f"wsteth_delta={(_wsteth() - wsteth_before) / E:.4f} (incl. -120 collateral) "
        f"auction_allowance={load_contract(WETH, from_abi=True).allowance(SAFE, auction.address)}"
    )
    assert weth_delta == idle, "Safe paid for the in-kind take"
    _trove(tm, a, "A redeemed")
    _trove(tm, b, "B")

    flex.borrow(TM, b, 1 * E)
    chain.sleep(tm.repay_cooldown() + 1)
    flex.repay(TM, b, 5 * E)
    flex.close_trove(TM, b)
    flex.close_trove(TM, a, zombie=tm.troves(a)["status"] == 2)
    _trove(tm, a, "A closed")
    _trove(tm, b, "B closed")
    flex.redeem(lender)
    print("lender shares left", load_contract(lender, from_abi=True).maxRedeem(SAFE))
    print("✅ check_troves")


def _fake_enso_route(token_in, token_out, amount_in, from_address, slippage_bps=100):
    params = (token_in, token_out, 100, from_address, 2**32, amount_in, 0, 0)
    data = _selector("exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))") + encode(
        ["(address,address,uint24,address,uint256,uint256,uint256,uint160)"], [params]
    )
    amount_out = load_contract(UNI_QUOTER).quoteExactInputSingle.call((token_in, token_out, amount_in, 100, 0))[0]
    return {
        "router": UNI_ROUTER,
        "data": "0x" + data.hex(),
        "amount_out": amount_out,
        "min_amount_out": amount_out * (10_000 - slippage_bps) // 10_000,
    }


def _setup_zapper(fake=True):
    daddy = accounts.at(DADDY, force=True)
    load_contract(REGISTRY).endorse(TM, {"from": daddy})
    if fake:
        load_contract(flex.LEVERAGE_ZAPPER).set_router(UNI_ROUTER, True, {"from": daddy})
        flex.enso_route = _fake_enso_route


def _zapper_flow(tag):
    tm = load_contract(TM)
    lender = tm.lender()
    one_pct = tm.one_pct()

    flex.deposit(lender, 100 * E)
    t = flex.open_leveraged_trove(TM, 10 * E, 20 * E, 3 * one_pct)
    _trove(tm, t, "open lev")
    flex.lever_up_trove(TM, t, 5 * E)
    _trove(tm, t, "lever up")
    chain.sleep(tm.repay_cooldown() + 1)
    flex.lever_down_trove(TM, t, 5 * E)
    _trove(tm, t, "lever down")
    flex.close_leveraged_trove(TM, t)
    _trove(tm, t, "close lev")

    # Redemption path: idle < debt --> the zapper redeems A and takes the auction in kind mid-callback
    idle = load_contract(WETH, from_abi=True).balanceOf(lender)
    a = flex.open_trove(TM, 120 * E, idle - 5 * E, 2 * one_pct, owner_index=0)
    t2 = flex.open_leveraged_trove(TM, 10 * E, 15 * E, 5 * one_pct)
    _trove(tm, t2, "open lev w/ redemption")
    _trove(tm, a, "A redeemed")
    print(f"✅ {tag}")


def check_zapper():
    _fund()
    _setup_zapper(fake=True)
    _zapper_flow("check_zapper (uniswap stand-in)")


def check_zapper_enso():
    _fund()
    _setup_zapper(fake=False)
    _zapper_flow("check_zapper_enso (real enso)")


def check_enso():
    zapper = load_contract(flex.LEVERAGE_ZAPPER)
    swap = enso_route(WETH, WSTETH, E, zapper.SWAP_EXECUTOR())
    print(f"router={swap['router']} whitelisted={zapper.routers(swap['router'])} out={swap['amount_out'] / E:.4f}")
    print("✅ check_enso")


def _replay(fn, setup=None):
    _fund()
    if setup:
        setup()
    nonce = SAFE.pending_nonce()
    chain.snapshot()
    fn()
    safe_tx = SAFE.multisend_from_receipts(safe_nonce=nonce)
    chain.revert()
    t0 = time.time()
    SAFE.preview(safe_tx, call_trace=False, reset=False)
    print(f"preview took {time.time() - t0:.1f}s")


def check_replay():
    tm = load_contract(TM)

    def fn():
        flex.deposit(tm.lender(), 50 * E)
        flex.open_trove(TM, 50 * E, 20 * E, 3 * tm.one_pct(), owner_index=0)
        flex.open_leveraged_trove(TM, 10 * E, 20 * E, 3 * tm.one_pct(), owner_index=7)

    _replay(fn, setup=_setup_zapper)
    print("✅ check_replay")
