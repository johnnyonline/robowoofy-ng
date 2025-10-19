import os
from functools import wraps
from typing import Callable, Optional
import asyncio

from brownie import accounts

from .config import SAFE
from .tg import notify_group_chat


def sign(send: bool = False, nonce: Optional[int] = None):
    """
    Decorator that automatically handles Safe setup, signing, (optionally) posting, and sending a telegram notification.

    Args:
        send (bool): Whether to post the transaction to the Safe service. Defaults to False (dry-run).
        nonce (Optional[int]): Specific nonce to use for the Safe transaction. If None, uses the pending nonce.
    """

    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            print(f"\n🔒 Safe Address: {SAFE.address}\n")

            # Rrecord tx receipts
            fn(*args, **kwargs)

            # Combine into multisend
            safe_nonce = nonce or SAFE.pending_nonce()
            safe_tx = SAFE.multisend_from_receipts(safe_nonce=safe_nonce)

            print("\n🔍 Transaction preview:\n")
            SAFE.preview(safe_tx, call_trace=True)

            if not send:
                print("\n🌵 Dry-run!\n")
                asyncio.run(notify_group_chat("🟢 🐶 <b>woof!</b>"))
                return safe_tx

            # Reset Brownie account cache
            accounts.clear()

            # Load signer from env var
            key = os.environ["ROBOWOOFY_SIGNER_PK"]
            signer = accounts.add(key)

            # Sign and post the transaction
            SAFE.sign_transaction(safe_tx, signer)
            SAFE.post_transaction(safe_tx)

            print("\n✅ Transaction queued!\n")

            # Fire off async tg notif
            asyncio.run(notify_group_chat("🐶 <b>woof!</b>"))

            return safe_tx

        return wrapper

    return decorator
