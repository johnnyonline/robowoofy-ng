import os

from brownie import ZERO_ADDRESS, web3
from eth_abi import encode

from .config import SAFE
from .helpers import enso_route
from .utils import load_contract

# ============================================================================================
# Constants
# ============================================================================================


LEVERAGE_ZAPPER = "0x1c0FEB0b97aD3938A0f308CB574D3b56998f0143"
DEBT_IN_FRONT_HELPER = "0x927ABC93A9d7f5C445b1a492a1843a21d26F2368"

BUFFER_BPS = 100  # 1% headroom on fees/approvals, since the Safe txn executes after the dry-run

TROVE_STATUS = {1: "active", 2: "zombie", 4: "closed", 8: "liquidated"}


# ============================================================================================
# View functions
# ============================================================================================


def get_trove_id(owner_index: int, opener: str | None = None) -> int:
    """
    @notice Get the ID of a Trove
    @param owner_index Unique index the Trove was opened with
    @param opener Whoever called `open_trove`: the Safe (default), or the zapper for leveraged Troves
    @return The Trove ID
    """
    return int.from_bytes(web3.keccak(encode(["address", "uint256"], [opener or SAFE.address, owner_index])), "big")


def print_trove(trove_manager: str, trove_id: int):
    """
    @notice Print the important info of a Trove
    @param trove_manager The Trove Manager address
    @param trove_id Unique identifier of the Trove
    """
    # Cache the Trove info
    tm = load_contract(trove_manager)
    trove = tm.troves(trove_id)
    debt = tm.get_trove_debt_after_interest(trove_id)
    print(f"Trove {trove_id}: {TROVE_STATUS.get(trove['status'], 'empty')}, owner {trove['owner']}")

    # Nothing else to show for an empty, closed or liquidated Trove
    if debt == 0:
        return

    # Cache the tokens
    borrow_token = load_contract(tm.borrow_token(), from_abi=True)
    collateral_token = load_contract(tm.collateral_token(), from_abi=True)

    # Get the token units and symbols
    borrow_unit, collateral_unit = 10 ** borrow_token.decimals(), 10 ** collateral_token.decimals()
    borrow_symbol = borrow_token.symbol()
    precision = tm.borrow_token_precision()

    # Calculate the Trove's position
    price = load_contract(tm.price_oracle()).get_price(True)
    collateral_value = trove["collateral"] * price // 10**36
    collateral_ratio = collateral_value / debt
    minimum_collateral_ratio = tm.minimum_collateral_ratio() / precision
    leverage = collateral_value / (collateral_value - debt) if collateral_value > debt else float("inf")
    display_price = price * collateral_unit / borrow_unit / 10**36

    # Get the debt that gets redeemed before this Trove
    debt_in_front = load_contract(DEBT_IN_FRONT_HELPER).get_debt_in_front(
        tm.address, 0, trove["annual_interest_rate"], trove_id
    )

    print(f"  Collateral:      {trove['collateral'] / collateral_unit:,.4f} {collateral_token.symbol()}")
    print(f"  Debt:            {debt / borrow_unit:,.4f} {borrow_symbol}")
    print(f"  Interest rate:   {trove['annual_interest_rate'] / precision:.2%}")
    print(f"  CR:              {collateral_ratio:.2%} (min {minimum_collateral_ratio:.2%})")
    print(f"  Leverage:        {leverage:.2f}x")
    print(f"  Price:           {display_price:,.4f} {borrow_symbol}")
    print(f"  Liq. price:      {display_price * minimum_collateral_ratio / collateral_ratio:,.4f} {borrow_symbol}")
    print(f"  Debt in front:   {debt_in_front / borrow_unit:,.4f} {borrow_symbol}")
    print(f"  Zapper approved: {tm.approved(trove['owner'], LEVERAGE_ZAPPER)}")


# ============================================================================================
# Open trove
# ============================================================================================


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
    @notice Open a new Trove
    @dev If idle liquidity can't cover `debt_amount`, the shortfall is redeemed and auctioned, with the
         proceeds going to the Safe. `take_auction=True` has the Safe take that auction in kind in the
         same txn, i.e. receive the redeemed collateral instead. The auction id is fixed at dry-run time
    @param trove_manager The Trove Manager address
    @param collateral_amount Amount of collateral tokens to deposit
    @param debt_amount Amount of debt to borrow
    @param annual_interest_rate Annual interest rate of the Trove
    @param owner_index Unique index to allow multiple Troves per Safe
    @param max_upfront_fee Maximum upfront fee the Safe is willing to pay. Defaults to the current fee + buffer
    @param min_borrow_out Minimum borrow tokens to receive
    @param min_collateral_out Minimum collateral tokens to receive, from the redemption
    @param take_auction Whether to take any kicked redemption auction in kind
    @return The Trove ID
    """
    # Cache the Trove Manager and Dutch Desk
    tm = load_contract(trove_manager)
    dutch_desk = load_contract(tm.dutch_desk())

    # Find the position in the sorted list
    prev_id, next_id = _hints(tm, annual_interest_rate)

    # Quote the upfront fee, if not provided
    if max_upfront_fee is None:
        max_upfront_fee = _buffer(tm.get_upfront_fee(debt_amount, annual_interest_rate, False))

    # Approve the Trove Manager to pull the collateral
    _approve(load_contract(tm.collateral_token(), from_abi=True), tm.address, collateral_amount)

    # Record the Dutch Desk nonce before opening the Trove
    nonce_before = dutch_desk.nonce()

    # Open the Trove
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
        SAFE.address,
    )

    # Take the auction, if one was kicked
    if take_auction:
        _take_kicked_auction(tm, dutch_desk, nonce_before)

    return get_trove_id(owner_index)


# ============================================================================================
# Adjust trove
# ============================================================================================


def add_collateral(trove_manager: str, trove_id: int, collateral_amount: int):
    """
    @notice Add collateral to an existing Trove
    @param trove_manager The Trove Manager address
    @param trove_id Unique identifier of the Trove
    @param collateral_amount Amount of collateral tokens to add
    """
    # Cache the Trove Manager
    tm = load_contract(trove_manager)

    # Approve the Trove Manager to pull the collateral
    _approve(load_contract(tm.collateral_token(), from_abi=True), tm.address, collateral_amount)

    # Add the collateral
    tm.add_collateral(trove_id, collateral_amount)


def remove_collateral(trove_manager: str, trove_id: int, collateral_amount: int):
    """
    @notice Remove collateral from an existing Trove
    @param trove_manager The Trove Manager address
    @param trove_id Unique identifier of the Trove
    @param collateral_amount Amount of collateral tokens to remove
    """
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
    @notice Borrow more from an existing Trove
    @dev See `open_trove` for redemptions and `take_auction`
    @param trove_manager The Trove Manager address
    @param trove_id Unique identifier of the Trove
    @param debt_amount Amount of debt to borrow
    @param max_upfront_fee Maximum upfront fee the Safe is willing to pay. Defaults to the current fee + buffer
    @param min_borrow_out Minimum borrow tokens to receive
    @param min_collateral_out Minimum collateral tokens to receive, from the redemption
    @param take_auction Whether to take any kicked redemption auction in kind
    """
    # Cache the Trove Manager and Dutch Desk
    tm = load_contract(trove_manager)
    dutch_desk = load_contract(tm.dutch_desk())

    # Quote the upfront fee, if not provided
    if max_upfront_fee is None:
        annual_interest_rate = tm.troves(trove_id)["annual_interest_rate"]
        max_upfront_fee = _buffer(tm.get_upfront_fee(debt_amount, annual_interest_rate, False))

    # Record the Dutch Desk nonce before borrowing
    nonce_before = dutch_desk.nonce()

    # Borrow
    tm.borrow(trove_id, debt_amount, max_upfront_fee, min_borrow_out, min_collateral_out)

    # Take the auction, if one was kicked
    if take_auction:
        _take_kicked_auction(tm, dutch_desk, nonce_before)


def repay(trove_manager: str, trove_id: int, debt_amount: int):
    """
    @notice Repay debt of an existing Trove
    @param trove_manager The Trove Manager address
    @param trove_id Unique identifier of the Trove
    @param debt_amount Amount of debt to repay
    """
    # Cache the Trove Manager
    tm = load_contract(trove_manager)

    # Approve the Trove Manager to pull the borrow tokens
    _approve(load_contract(tm.borrow_token(), from_abi=True), tm.address, debt_amount)

    # Repay
    tm.repay(trove_id, debt_amount)


def adjust_interest_rate(
    trove_manager: str, trove_id: int, new_annual_interest_rate: int, max_upfront_fee: int | None = None
):
    """
    @notice Adjust the interest rate of an existing Trove
    @dev The upfront fee is only charged if adjusting before the cooldown is over
    @param trove_manager The Trove Manager address
    @param trove_id Unique identifier of the Trove
    @param new_annual_interest_rate New annual interest rate of the Trove
    @param max_upfront_fee Maximum upfront fee the Safe is willing to pay. Defaults to the current fee + buffer
    """
    # Cache the Trove Manager
    tm = load_contract(trove_manager)

    # Find the new position in the sorted list
    prev_id, next_id = _hints(tm, new_annual_interest_rate)

    # Quote the upfront fee, if not provided
    if max_upfront_fee is None:
        debt = tm.get_trove_debt_after_interest(trove_id)
        max_upfront_fee = _buffer(tm.get_upfront_fee(debt, new_annual_interest_rate, True))

    # Adjust the interest rate
    tm.adjust_interest_rate(trove_id, new_annual_interest_rate, prev_id, next_id, max_upfront_fee)


def approve_operator(trove_manager: str, operator: str, approved: bool = True):
    """
    @notice Approve or revoke an operator on the Safe's Troves, if not already
    @param trove_manager The Trove Manager address
    @param operator The operator address
    @param approved Whether to approve or revoke
    """
    # Cache the Trove Manager
    tm = load_contract(trove_manager)

    # Update the approval, if needed
    if tm.approved(SAFE, operator) != approved:
        tm.approve(operator, approved)


# ============================================================================================
# Close trove
# ============================================================================================


def close_trove(trove_manager: str, trove_id: int, zombie: bool = False):
    """
    @notice Close an existing Trove by repaying all its debt
    @param trove_manager The Trove Manager address
    @param trove_id Unique identifier of the Trove
    @param zombie Whether the Trove is a zombie Trove
    """
    # Cache the Trove Manager and borrow token
    tm = load_contract(trove_manager)
    borrow_token = load_contract(tm.borrow_token(), from_abi=True)

    # Approve the debt + buffer, since it keeps accruing until the Safe txn executes
    borrow_token.approve(tm.address, _buffer(tm.get_trove_debt_after_interest(trove_id)))

    # Close the Trove
    if zombie:
        tm.close_zombie_trove(trove_id)
    else:
        tm.close_trove(trove_id)

    # Make sure our approval is back to 0
    borrow_token.approve(tm.address, 0)


# ============================================================================================
# Take auction
# ============================================================================================


def take_auction(trove_manager: str, auction_id: int, max_take_amount: int = 2**256 - 1):
    """
    @notice Take an auction of a market
    @dev If the Safe is the auction's receiver (i.e. the redeemer), it takes in kind and only pays any
         surplus above the auction's maximum amount
    @param trove_manager The Trove Manager address
    @param auction_id Unique identifier of the auction
    @param max_take_amount Maximum amount of collateral to take
    """
    # Cache the Trove Manager and auction
    tm = load_contract(trove_manager)
    auction = load_contract(load_contract(tm.dutch_desk()).auction())
    info = auction.auctions(auction_id)

    # Get the borrow tokens needed. The receiver only pays any surplus above its maximum
    needed = auction.get_needed_amount(auction_id, max_take_amount)
    if info["receiver"] == SAFE.address:
        needed = max(0, needed - (info["maximum_amount"] - info["amount_received"]))

    # Approve the auction to pull the borrow tokens
    _approve(load_contract(tm.borrow_token(), from_abi=True), auction.address, needed)

    # Take the auction
    auction.take(auction_id, max_take_amount, SAFE.address)


# ============================================================================================
# Manual loop
# ============================================================================================


def loop_trove(trove_manager: str, trove_id: int, debt_amount: int, loops: int = 1, slippage_bps: int = 100):
    """
    @notice Lever up an existing Trove without the zapper
    @dev `loops` times: borrow `debt_amount`, swap it to collateral via Enso and add it.
         Any redemption auction is taken in kind and its collateral added too
    @param trove_manager The Trove Manager address
    @param trove_id Unique identifier of the Trove
    @param debt_amount Amount of debt to borrow per loop
    @param loops Number of loops
    @param slippage_bps Maximum slippage of the swaps, in basis points
    """
    # Cache the Trove Manager and tokens
    tm = load_contract(trove_manager)
    borrow_token = load_contract(tm.borrow_token(), from_abi=True)
    collateral_token = load_contract(tm.collateral_token(), from_abi=True)

    for _ in range(loops):
        # Record the balances before borrowing
        borrow_before = borrow_token.balanceOf(SAFE)
        collateral_before = collateral_token.balanceOf(SAFE)

        # Borrow, and take any kicked auction in kind
        borrow(tm.address, trove_id, debt_amount, take_auction=True)

        # Get what we received
        borrowed = borrow_token.balanceOf(SAFE) - borrow_before
        in_kind = collateral_token.balanceOf(SAFE) - collateral_before

        # Borrow token --> collateral, if idle liquidity covered any of the loan
        swapped = 0
        if borrowed > 0:
            swap = enso_route(borrow_token.address, collateral_token.address, borrowed, SAFE.address, slippage_bps)
            _approve(borrow_token, swap["router"], borrowed)
            SAFE.account.transfer(swap["router"], 0, data=swap["data"])
            swapped = swap["min_amount_out"]

        # Count on the swap's min out and haircut the in-kind collateral, since the Safe txn executes after the dry-run
        add_collateral(tm.address, trove_id, swapped + in_kind * (10_000 - slippage_bps) // 10_000)


# ============================================================================================
# Leverage zapper
# ============================================================================================


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
    @notice Open a new leveraged Trove via the zapper
    @dev Trove IDs of zapper-opened Troves derive from the zapper address, so `owner_index` defaults to a random one
    @param trove_manager The Trove Manager address
    @param initial_collateral Amount of collateral tokens the Safe puts in
    @param debt_amount Amount of debt to borrow and swap to collateral
    @param annual_interest_rate Annual interest rate of the Trove
    @param owner_index Unique index to allow multiple Troves per opener
    @param max_upfront_fee Maximum upfront fee the Safe is willing to pay. Defaults to the current fee + buffer
    @param min_borrow_out Minimum borrow tokens to receive
    @param min_collateral_out Minimum collateral tokens to receive, from the redemption
    @param slippage_bps Maximum slippage of the swap, in basis points
    @return The Trove ID
    """
    # Cache the Trove Manager and zapper
    tm = load_contract(trove_manager)
    zapper = load_contract(LEVERAGE_ZAPPER)

    # Pick a random owner index, if not provided
    if owner_index is None:
        owner_index = int.from_bytes(os.urandom(32), "big")

    # Find the position in the sorted list
    prev_id, next_id = _hints(tm, annual_interest_rate)

    # Quote the upfront fee, if not provided
    if max_upfront_fee is None:
        max_upfront_fee = _buffer(tm.get_upfront_fee(debt_amount, annual_interest_rate, False))

    # Quote the borrow token --> collateral swap
    debt_swap, swapped_collateral = _debt_swap(tm, zapper, debt_amount, slippage_bps)

    # Approve the zapper to pull the initial collateral
    _approve(load_contract(tm.collateral_token(), from_abi=True), zapper.address, initial_collateral)

    # Open the leveraged Trove
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

    return get_trove_id(owner_index, zapper.address)


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
    """
    @notice Lever up an existing Trove via the zapper
    @param trove_manager The Trove Manager address
    @param trove_id Unique identifier of the Trove
    @param debt_amount Amount of debt to borrow and swap to collateral
    @param initial_collateral Amount of collateral tokens the Safe puts in
    @param max_upfront_fee Maximum upfront fee the Safe is willing to pay. Defaults to the current fee + buffer
    @param min_borrow_out Minimum borrow tokens to receive
    @param min_collateral_out Minimum collateral tokens to receive, from the redemption
    @param slippage_bps Maximum slippage of the swap, in basis points
    """
    # Cache the Trove Manager and zapper
    tm = load_contract(trove_manager)
    zapper = load_contract(LEVERAGE_ZAPPER)

    # Quote the upfront fee, if not provided
    if max_upfront_fee is None:
        annual_interest_rate = tm.troves(trove_id)["annual_interest_rate"]
        max_upfront_fee = _buffer(tm.get_upfront_fee(debt_amount, annual_interest_rate, False))

    # Quote the borrow token --> collateral swap
    debt_swap, swapped_collateral = _debt_swap(tm, zapper, debt_amount, slippage_bps)

    # Make sure the zapper is approved to operate on our Troves
    approve_operator(tm.address, zapper.address)

    # Approve the zapper to pull the initial collateral
    _approve(load_contract(tm.collateral_token(), from_abi=True), zapper.address, initial_collateral)

    # Lever up
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
    """
    @notice Lever down an existing Trove via the zapper
    @dev Flash loans what the removed collateral swaps into, and repays debt with it
    @param trove_manager The Trove Manager address
    @param trove_id Unique identifier of the Trove
    @param collateral_to_remove Amount of collateral tokens to remove and swap to borrow tokens
    @param slippage_bps Maximum slippage of the swap, in basis points
    """
    # Cache the Trove Manager, zapper and borrow token
    tm = load_contract(trove_manager)
    zapper = load_contract(LEVERAGE_ZAPPER)
    borrow_token = tm.borrow_token()

    # Quote the collateral --> borrow token swap
    swap = enso_route(tm.collateral_token(), borrow_token, collateral_to_remove, zapper.SWAP_EXECUTOR(), slippage_bps)

    # Make sure the router is whitelisted
    assert zapper.routers(swap["router"]), "!router"

    # Make sure the zapper is approved to operate on our Troves
    approve_operator(tm.address, zapper.address)

    # Lever down
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
    """
    @notice Close a leveraged Trove via the zapper
    @dev Swaps just enough collateral to repay the flash loan, the rest is swept back to the Safe
    @param trove_manager The Trove Manager address
    @param trove_id Unique identifier of the Trove
    @param slippage_bps Maximum slippage of the swap, in basis points
    """
    # Cache the Trove Manager, zapper and borrow token
    tm = load_contract(trove_manager)
    zapper = load_contract(LEVERAGE_ZAPPER)
    borrow_token = tm.borrow_token()

    # Flash loan the debt + buffer, since it keeps accruing until the Safe txn executes
    flash_loan_amount = _buffer(tm.get_trove_debt_after_interest(trove_id))

    # Get the collateral to swap, capped at the Trove's collateral
    price = load_contract(tm.price_oracle()).get_price(True)
    collateral_to_swap = min(
        tm.troves(trove_id)["collateral"],
        flash_loan_amount * 10**36 // price * (10_000 + 2 * slippage_bps) // 10_000,
    )

    # Quote the collateral --> borrow token swap
    swap = enso_route(tm.collateral_token(), borrow_token, collateral_to_swap, zapper.SWAP_EXECUTOR(), slippage_bps)

    # Make sure the router is whitelisted and the swap repays the flash loan
    assert zapper.routers(swap["router"]), "!router"
    assert swap["min_amount_out"] >= flash_loan_amount, "!collateral"

    # Make sure the zapper is approved to operate on our Troves
    approve_operator(tm.address, zapper.address)

    # Close the leveraged Trove
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


# ============================================================================================
# Lender
# ============================================================================================


def deposit(lender_address: str, amount: int):
    """
    @notice Deposit borrow tokens into a market's lender
    @param lender_address The lender address
    @param amount Amount of borrow tokens to deposit
    """
    # Cache the lender
    lender = load_contract(lender_address, from_abi=True)

    # Approve the lender to pull the borrow tokens
    _approve(load_contract(lender.asset(), from_abi=True), lender.address, amount)

    # Deposit
    lender.deposit(amount, SAFE.address)


def redeem(lender_address: str, shares: int | None = None):
    """
    @notice Redeem shares from a market's lender
    @param lender_address The lender address
    @param shares Amount of shares to redeem. Defaults to the max redeemable
    """
    # Cache the lender
    lender = load_contract(lender_address, from_abi=True)

    # Get the max redeemable shares, if not provided
    if shares is None:
        shares = lender.maxRedeem(SAFE)

    # Redeem
    lender.redeem(shares, SAFE.address, SAFE.address)


# ============================================================================================
# Internal functions
# ============================================================================================


def _buffer(amount: int) -> int:
    """
    @notice Add the buffer to an amount
    @param amount The amount
    @return The amount + buffer
    """
    return amount * (10_000 + BUFFER_BPS) // 10_000


def _hints(tm, annual_interest_rate: int):
    """
    @notice Find the position of an interest rate in the sorted list
    @param tm The Trove Manager contract
    @param annual_interest_rate The annual interest rate
    @return The previous and next Trove IDs
    """
    return load_contract(tm.sorted_troves()).find_insert_position(annual_interest_rate, 0, 0)


def _take_kicked_auction(tm, dutch_desk, nonce_before: int):
    """
    @notice Take the auction kicked by the last call, if any
    @param tm The Trove Manager contract
    @param dutch_desk The Dutch Desk contract
    @param nonce_before The Dutch Desk nonce before the call
    """
    # Return early if no auction was kicked
    if dutch_desk.nonce() == nonce_before:
        return

    # Make sure there is no starting price buffer. Otherwise the Safe would pay a surplus to the lender
    assert dutch_desk.starting_price_buffer_percentage() == 10**18, "!buffer"

    # Take the auction
    take_auction(tm.address, nonce_before)


def _debt_swap(tm, zapper, debt_amount: int, slippage_bps: int):
    """
    @notice Quote the borrow token --> collateral swap the zapper runs mid open/lever up
    @param tm The Trove Manager contract
    @param zapper The zapper contract
    @param debt_amount Amount of debt to borrow
    @param slippage_bps Maximum slippage of the swap, in basis points
    @return The `SwapData` and the collateral the zapper can count on (swap + any redemption auction it takes)
    """
    # Get the part of the loan that idle liquidity covers
    borrow_token = tm.borrow_token()
    atomic = min(debt_amount, load_contract(borrow_token, from_abi=True).balanceOf(tm.lender()))
    shortfall = debt_amount - atomic

    # The zapper takes the redemption auction in kind. Leave room for any rounding surplus it pays
    if shortfall > 0:
        atomic = atomic * (10_000 - slippage_bps) // 10_000

    # Quote the borrow token --> collateral swap
    swap = enso_route(borrow_token, tm.collateral_token(), atomic, zapper.SWAP_EXECUTOR(), slippage_bps)

    # Make sure the router is whitelisted
    assert zapper.routers(swap["router"]), "!router"

    # Get the collateral we can count on: the swap's min out + the auction's collateral, haircut by slippage
    auction_collateral = shortfall * 10**36 // load_contract(tm.price_oracle()).get_price(True)
    collateral = swap["min_amount_out"] + auction_collateral * (10_000 - slippage_bps) // 10_000

    return (swap["router"], swap["data"]), collateral


def _approve(token, spender: str, amount: int):
    """
    @notice Approve a spender, if the allowance isn't enough already
    @param token The token contract
    @param spender The spender address
    @param amount The amount to approve
    """
    if token.allowance(SAFE, spender) < amount:
        token.approve(spender, amount)
