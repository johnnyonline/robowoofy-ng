import os

from brownie import ZERO_ADDRESS, web3
from eth_abi import encode

from .config import SAFE
from .helpers import enso_route
from .utils import load_contract

# Amounts are in token units. Interest rates are in borrow token precision (e.g. 5% = 5 * tm.one_pct())

LEVERAGE_ZAPPER = "0x1c0FEB0b97aD3938A0f308CB574D3b56998f0143"
BUFFER_BPS = 100  # 1% headroom on fees/approvals, since the Safe txn executes after the dry-run


def get_trove_id(owner_index: int, opener: str | None = None) -> int:
    # `opener` is whoever called `open_trove`: the Safe, or the zapper for leveraged troves
    return int.from_bytes(web3.keccak(encode(["address", "uint256"], [opener or SAFE.address, owner_index])), "big")


def open_trove(
    trove_manager: str,
    collateral_amount: int,
    debt_amount: int,
    annual_interest_rate: int,
    owner_index: int = 0,
    max_upfront_fee: int | None = None,
    min_borrow_out: int = 0,
    min_collateral_out: int = 0,
    take_auction: bool = False,
) -> int:
    """
    If idle liquidity can't cover `debt_amount`, the shortfall is redeemed and auctioned, with the
    proceeds going to the Safe. `take_auction=True` has the Safe take that auction in kind in the
    same txn, i.e. receive the redeemed collateral instead. The auction id is fixed at dry-run time
    """
    tm = load_contract(trove_manager)
    dutch_desk = load_contract(tm.dutch_desk())
    prev_id, next_id = _hints(tm, annual_interest_rate)
    if max_upfront_fee is None:
        max_upfront_fee = _buffer(tm.get_upfront_fee(debt_amount, annual_interest_rate, False))

    _approve(load_contract(tm.collateral_token(), from_abi=True), tm.address, collateral_amount)

    nonce_before = dutch_desk.nonce()
    tm.open_trove(
        owner_index,
        collateral_amount,
        debt_amount,
        prev_id,
        next_id,
        annual_interest_rate,
        max_upfront_fee,
        min_borrow_out,
        min_collateral_out,
    )
    if take_auction:
        _take_kicked_auction(tm, dutch_desk, nonce_before)

    trove_id = get_trove_id(owner_index)
    print(f"Opened trove {trove_id}")
    return trove_id


def add_collateral(trove_manager: str, trove_id: int, collateral_amount: int):
    tm = load_contract(trove_manager)
    _approve(load_contract(tm.collateral_token(), from_abi=True), tm.address, collateral_amount)
    tm.add_collateral(trove_id, collateral_amount)


def remove_collateral(trove_manager: str, trove_id: int, collateral_amount: int):
    load_contract(trove_manager).remove_collateral(trove_id, collateral_amount)


def borrow(
    trove_manager: str,
    trove_id: int,
    debt_amount: int,
    max_upfront_fee: int | None = None,
    min_borrow_out: int = 0,
    min_collateral_out: int = 0,
    take_auction: bool = False,
):
    """
    See `open_trove` for redemptions and `take_auction`
    """
    tm = load_contract(trove_manager)
    dutch_desk = load_contract(tm.dutch_desk())
    if max_upfront_fee is None:
        annual_interest_rate = tm.troves(trove_id)["annual_interest_rate"]
        max_upfront_fee = _buffer(tm.get_upfront_fee(debt_amount, annual_interest_rate, False))

    nonce_before = dutch_desk.nonce()
    tm.borrow(trove_id, debt_amount, max_upfront_fee, min_borrow_out, min_collateral_out)
    if take_auction:
        _take_kicked_auction(tm, dutch_desk, nonce_before)


def repay(trove_manager: str, trove_id: int, debt_amount: int):
    tm = load_contract(trove_manager)
    _approve(load_contract(tm.borrow_token(), from_abi=True), tm.address, debt_amount)
    tm.repay(trove_id, debt_amount)


def adjust_interest_rate(
    trove_manager: str, trove_id: int, new_annual_interest_rate: int, max_upfront_fee: int | None = None
):
    tm = load_contract(trove_manager)
    prev_id, next_id = _hints(tm, new_annual_interest_rate)
    if max_upfront_fee is None:
        # Only charged if adjusting before the cooldown is over
        debt = tm.get_trove_debt_after_interest(trove_id)
        max_upfront_fee = _buffer(tm.get_upfront_fee(debt, new_annual_interest_rate, True))

    tm.adjust_interest_rate(trove_id, new_annual_interest_rate, prev_id, next_id, max_upfront_fee)


def close_trove(trove_manager: str, trove_id: int, zombie: bool = False):
    tm = load_contract(trove_manager)
    borrow_token = load_contract(tm.borrow_token(), from_abi=True)

    # Debt keeps accruing until the Safe txn executes
    borrow_token.approve(tm.address, _buffer(tm.get_trove_debt_after_interest(trove_id)))
    if zombie:
        tm.close_zombie_trove(trove_id)
    else:
        tm.close_trove(trove_id)
    borrow_token.approve(tm.address, 0)


def approve_operator(trove_manager: str, operator: str, approved: bool = True):
    tm = load_contract(trove_manager)
    if tm.approved(SAFE, operator) != approved:
        tm.approve(operator, approved)


def take_auction(trove_manager: str, auction_id: int, max_take_amount: int = 2**256 - 1):
    tm = load_contract(trove_manager)
    auction = load_contract(load_contract(tm.dutch_desk()).auction())
    info = auction.auctions(auction_id)

    # The auction's receiver (i.e. the redeemer) takes in kind, and only pays any surplus above its maximum
    needed = auction.get_needed_amount(auction_id, max_take_amount)
    if info["receiver"] == SAFE.address:
        needed = max(0, needed - (info["maximum_amount"] - info["amount_received"]))

    _approve(load_contract(tm.borrow_token(), from_abi=True), auction.address, needed)
    auction.take(auction_id, max_take_amount, SAFE.address)


def open_leveraged_trove(
    trove_manager: str,
    initial_collateral: int,
    debt_amount: int,
    annual_interest_rate: int,
    owner_index: int | None = None,
    max_upfront_fee: int | None = None,
    min_borrow_out: int = 0,
    min_collateral_out: int = 0,
    slippage_bps: int = 100,
) -> int:
    """
    Trove ids of zapper-opened troves are derived from the zapper address, so `owner_index` defaults to a random one
    """
    tm = load_contract(trove_manager)
    zapper = load_contract(LEVERAGE_ZAPPER)
    if owner_index is None:
        owner_index = int.from_bytes(os.urandom(32), "big")
    prev_id, next_id = _hints(tm, annual_interest_rate)
    if max_upfront_fee is None:
        max_upfront_fee = _buffer(tm.get_upfront_fee(debt_amount, annual_interest_rate, False))
    debt_swap, swapped_collateral = _debt_swap(tm, zapper, debt_amount, slippage_bps)

    _approve(load_contract(tm.collateral_token(), from_abi=True), zapper.address, initial_collateral)
    zapper.open_leveraged_trove(
        (
            SAFE.address,
            tm.address,
            owner_index,
            initial_collateral,
            initial_collateral + swapped_collateral,
            debt_amount,
            prev_id,
            next_id,
            annual_interest_rate,
            max_upfront_fee,
            min_borrow_out,
            min_collateral_out,
            debt_swap,
        )
    )

    trove_id = get_trove_id(owner_index, zapper.address)
    print(f"Opened leveraged trove {trove_id}")
    return trove_id


def lever_up_trove(
    trove_manager: str,
    trove_id: int,
    debt_amount: int,
    initial_collateral: int = 0,
    max_upfront_fee: int | None = None,
    min_borrow_out: int = 0,
    min_collateral_out: int = 0,
    slippage_bps: int = 100,
):
    tm = load_contract(trove_manager)
    zapper = load_contract(LEVERAGE_ZAPPER)
    if max_upfront_fee is None:
        annual_interest_rate = tm.troves(trove_id)["annual_interest_rate"]
        max_upfront_fee = _buffer(tm.get_upfront_fee(debt_amount, annual_interest_rate, False))
    debt_swap, swapped_collateral = _debt_swap(tm, zapper, debt_amount, slippage_bps)

    approve_operator(tm.address, zapper.address)
    _approve(load_contract(tm.collateral_token(), from_abi=True), zapper.address, initial_collateral)
    zapper.lever_up_trove(
        (
            tm.address,
            trove_id,
            initial_collateral,
            initial_collateral + swapped_collateral,
            debt_amount,
            max_upfront_fee,
            min_borrow_out,
            min_collateral_out,
            debt_swap,
        )
    )


def lever_down_trove(trove_manager: str, trove_id: int, collateral_to_remove: int, slippage_bps: int = 100):
    tm = load_contract(trove_manager)
    zapper = load_contract(LEVERAGE_ZAPPER)
    borrow_token = tm.borrow_token()

    # Flash loan what the removed collateral swaps into, and repay debt with it
    swap = enso_route(tm.collateral_token(), borrow_token, collateral_to_remove, zapper.SWAP_EXECUTOR(), slippage_bps)
    assert zapper.routers(swap["router"]), "!router"

    approve_operator(tm.address, zapper.address)
    zapper.lever_down_trove(
        (
            tm.address,
            borrow_token,
            trove_id,
            swap["min_amount_out"],
            collateral_to_remove,
            (swap["router"], swap["data"]),
            (ZERO_ADDRESS, b""),
        )
    )


def close_leveraged_trove(trove_manager: str, trove_id: int, slippage_bps: int = 100):
    tm = load_contract(trove_manager)
    zapper = load_contract(LEVERAGE_ZAPPER)
    borrow_token = tm.borrow_token()
    flash_loan_amount = _buffer(tm.get_trove_debt_after_interest(trove_id))

    # Swap just enough collateral to repay the flash loan, the rest is swept back to the Safe
    price = load_contract(tm.price_oracle()).get_price(True)
    collateral_to_swap = min(
        tm.troves(trove_id)["collateral"],
        flash_loan_amount * 10**36 // price * (10_000 + 2 * slippage_bps) // 10_000,
    )
    swap = enso_route(tm.collateral_token(), borrow_token, collateral_to_swap, zapper.SWAP_EXECUTOR(), slippage_bps)
    assert zapper.routers(swap["router"]), "!router"
    assert swap["min_amount_out"] >= flash_loan_amount, "!collateral"

    approve_operator(tm.address, zapper.address)
    zapper.close_leveraged_trove(
        (
            tm.address,
            borrow_token,
            trove_id,
            flash_loan_amount,
            (swap["router"], swap["data"]),
            (ZERO_ADDRESS, b""),
        )
    )


def deposit(lender_address: str, amount: int):
    lender = load_contract(lender_address, from_abi=True)
    _approve(load_contract(lender.asset(), from_abi=True), lender.address, amount)
    lender.deposit(amount, SAFE.address)


def redeem(lender_address: str, shares: int | None = None):
    lender = load_contract(lender_address, from_abi=True)
    if shares is None:
        shares = lender.maxRedeem(SAFE)
    lender.redeem(shares, SAFE.address, SAFE.address)


def _buffer(amount: int) -> int:
    return amount * (10_000 + BUFFER_BPS) // 10_000


def _hints(tm, annual_interest_rate: int):
    return load_contract(tm.sorted_troves()).find_insert_position(annual_interest_rate, 0, 0)


def _take_kicked_auction(tm, dutch_desk, nonce_before: int):
    if dutch_desk.nonce() == nonce_before:
        return

    # With a starting price buffer the Safe would pay a surplus to the Lender
    assert dutch_desk.starting_price_buffer_percentage() == 10**18, "!buffer"
    take_auction(tm.address, nonce_before)


def _debt_swap(tm, zapper, debt_amount: int, slippage_bps: int):
    """
    Quote the borrow --> collateral swap the zapper runs mid open/lever up.
    Returns the `SwapData` and the collateral the zapper can count on (swap + any redemption auction it takes)
    """
    borrow_token = tm.borrow_token()
    atomic = min(debt_amount, load_contract(borrow_token, from_abi=True).balanceOf(tm.lender()))
    shortfall = debt_amount - atomic
    if shortfall > 0:
        # The zapper takes the redemption auction in kind. Leave room for any rounding surplus it pays
        atomic = atomic * (10_000 - slippage_bps) // 10_000

    swap = enso_route(borrow_token, tm.collateral_token(), atomic, zapper.SWAP_EXECUTOR(), slippage_bps)
    assert zapper.routers(swap["router"]), "!router"

    auction_collateral = shortfall * 10**36 // load_contract(tm.price_oracle()).get_price(True)
    collateral = swap["min_amount_out"] + auction_collateral * (10_000 - slippage_bps) // 10_000
    return (swap["router"], swap["data"]), collateral


def _approve(token, spender: str, amount: int):
    if token.allowance(SAFE, spender) < amount:
        token.approve(spender, amount)
