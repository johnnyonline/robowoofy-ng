from brownie import Contract

from .config import SAFE


def load_contract(address: str) -> Contract:
    """
    Try loading a contract via the local ABI cache first,
    and fall back to the block explorer if unavailable.

    Args:
        address (str): The contract address.

    Returns:
        Contract: The loaded contract instance.
    """
    try:
        return SAFE.contract(address)
    except ValueError:
        Contract.from_explorer(address)
        return SAFE.contract(address)
