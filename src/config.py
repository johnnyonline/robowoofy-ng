import os
from typing import Mapping, TypedDict

from brownie_safe import BrownieSafe


class NetworkCfg(TypedDict):
    safe: BrownieSafe
    safe_tx_queue_url: str


NETWORKS: Mapping[str, NetworkCfg] = {
    "eth": {
        "safe": BrownieSafe("ychad.eth"),
        "safe_tx_queue_url": "https://app.safe.global/transactions/queue?safe=eth:",
    },
    "base": {
        "safe": BrownieSafe("0xbfAABa9F56A39B814281D68d2Ad949e88D06b02E"),  # bChad
        "safe_tx_queue_url": "https://app.safe.global/transactions/queue?safe=base:",
    },
}

SAFE: BrownieSafe = None  # Will be initialized at import


def cfg(network: str | None = None) -> NetworkCfg:
    """
    Get the configuration for the specified network.

    Args:
        network (str | None): The network identifier. If None, defaults to 'eth'.

    Returns:
        NetworkCfg: The configuration for the specified network.
    """
    return NETWORKS.get(network, NETWORKS["eth"])


def get_safe(network: str | None = None) -> BrownieSafe:
    """
    Get the BrownieSafe instance for the specified network.

    Args:
        network (str | None): The network identifier. If None, defaults to 'eth'.

    Returns:
        BrownieSafe: The BrownieSafe instance for the specified network.
    """
    return cfg(network)["safe"]


def get_safe_tx_queue_url(network: str | None = None) -> str:
    """
    Get the Safe transaction queue URL for the specified network.

    Args:
        network (str | None): The network identifier. If None, defaults to 'eth'.

    Returns:
        str: The Safe transaction queue URL for the specified network.
    """
    return cfg(network)["safe_tx_queue_url"]


# Initialize SAFE at import time
network = os.getenv("NETWORK", "eth")
SAFE = get_safe(network)
