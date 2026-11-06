from brownie import Contract

from .config import SAFE

ABI = [
    {
        "name": "setDepositLimit",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "_depositLimit", "type": "uint256"}],
        "outputs": [],
    },
    {
        "name": "depositLimit",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "acceptManagement",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [],
        "outputs": [],
    },
    {
        "name": "setPerformanceFee",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "_performanceFee", "type": "uint16"}],
        "outputs": [],
    },
    {
        "name": "endorse",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "_target", "type": "address"}],
        "outputs": [],
    },
    {
        "name": "execute",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "_target", "type": "address"},
            {"name": "_data", "type": "bytes"},
        ],
        "outputs": [{"name": "", "type": "bytes"}],
    },
    {
        "name": "deposit",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "assets", "type": "uint256"},
            {"name": "receiver", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "redeem",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "shares", "type": "uint256"},
            {"name": "receiver", "type": "address"},
            {"name": "owner", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "asset",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
    {
        "name": "approve",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "allowance",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "maxRedeem",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "owner", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]


def load_contract(address: str, from_abi: bool = False) -> Contract:
    """
    Load a contract. If `from_abi` is True, build it from the local `ABI`
    variable (no explorer fetch). Otherwise, try the local ABI cache first
    and fall back to the block explorer.

    Args:
        address (str): The contract address.
        from_abi (bool): If True, load using the local `ABI`.

    Returns:
        Contract: The loaded contract instance.
    """
    if from_abi:
        return Contract.from_abi("Contract", address, ABI, owner=SAFE.account)

    try:
        return SAFE.contract(address)
    except ValueError:
        Contract.from_explorer(address)
        return SAFE.contract(address)
