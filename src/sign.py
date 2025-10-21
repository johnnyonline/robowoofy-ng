import asyncio
import os
from functools import wraps
from typing import Callable, Optional

from brownie import accounts

from .config import SAFE, get_safe_tx_queue_url
from .tg import notify_group_chat


def sign(nonce: Optional[int] = None):
    """
    Decorator that automatically handles Safe setup, signing, (optionally) posting, and sending a telegram notification.

    Args:
        nonce (Optional[int]): Specific nonce to use for the Safe transaction. If None, uses the pending nonce.
    """

    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            print(f"\n🔒 Safe Address: {SAFE.address}\n")

            # Rrecord tx receipts
            fn(*args, **kwargs)

            # Determine nonce
            safe_nonce = nonce or SAFE.pending_nonce()
            print(f"ROBOWOOFY_NONCE={safe_nonce}\n")  # <-- machine-readable for CI

            # Combine into multisend
            safe_tx = SAFE.multisend_from_receipts(safe_nonce=safe_nonce)

            print("\n🔍 Transaction preview:\n")
            SAFE.preview(safe_tx, call_trace=True)

            # Determine send flag from env var. Default to false
            send = os.getenv("SEND", "false").lower() == "true"

            if not send:
                print("\n🌵 Dry-run!\n")
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

            network = os.getenv("NETWORK", "eth")
            repo = os.getenv("GITHUB_REPOSITORY")
            sender = os.getenv("GITHUB_PR_AUTHOR")
            run_id = os.getenv("GITHUB_RUN_ID")
            pr_number = os.getenv("GITHUB_PR_NUMBER")
            pr_title = os.getenv("GITHUB_PR_TITLE")
            pr_body = os.getenv("GITHUB_PR_BODY")

            if pr_body is None:
                pr_body = "No description provided 🤡"

            safe_link = f"{get_safe_tx_queue_url(network)}{SAFE.address}"
            code_link = f"https://github.com/{repo}/pull/{pr_number}/files"
            logs_link = f"https://github.com/{repo}/actions/runs/{run_id}"

            msg = (
                f"🐶🐶🐶\n"
                f"<b>Title:</b> {pr_title}\n"
                f"<b>Sender:</b> {sender}\n"
                f"<b>Description:</b> {pr_body}\n"
                f'<a href="{code_link}">Review</a> the code, '
                f'<a href="{logs_link}">verify</a> the output, and '
                f'<a href="{safe_link}">sign</a> here'
            )

            # Fire off async tg notif
            asyncio.run(notify_group_chat(msg))

            return safe_tx

        return wrapper

    return decorator
