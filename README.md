# Robowoofy-NG

**Robowoofy** is a GitHub-Actions-driven automation tool that lets you safely execute, simulate, and propose multi-step on-chain transactions through a Gnosis Safe.
It’s designed so users can open PRs that define **one function** (e.g. `woofy()`) describing the on-chain actions they want the Safe to perform.
A GitHub Action then picks up `/run` comments, runs the code in a Dockerized Brownie environment, and either does a **dry run** or **submits a transaction** to the Safe

## How it Works

- Every PR defines a function (e.g. `woofy()`) inside the `woof.py`, decorated with `@sign()`
- The decorator constructs a Safe transaction and (optionally) signs and sends it
- The GitHub Action listens for comments like `/run fn=woofy network=eth send=true`

## Writing your function

A function could look like:
```python
from .config import SAFE
from .sign import sign
from .utils import load_contract

@sign(nonce=None)  # optional: specify nonce to override pending
def woofy():
    ycrv = load_contract("0xFCc5c47bE19d06BF83eB04298b026F81069ff65b")
    ybs = load_contract("0xE9A115b77A1057C918F997c32663FdcE24FB873f")

    balance = ycrv.balanceOf(SAFE)
    print(f"Our yCRV balance: {balance / 1e18:.4f}")

    ycrv.approve(ybs.address, balance)
    print("Approved YBS to pull yCRV")

    ybs.stake(balance)
    print("Staked yCRV into YBS")
```

Or a 🐮 CoW Swap limit sell:
```python
from .config import SAFE
from .sign import sign
from .utils import load_contract
from .helpers import cowswap_quote, cowswap_limit_sell, COWSWAP_RELAYER

@sign()
def swap_crvusd_for_wsteth():
    token_in = load_contract("0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E")  # crvUSD
    token_out = load_contract("0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0")  # wstETH

    amount = token_in.balanceOf(SAFE)
    print(f"Swapping {amount / (10 ** token_in.decimals())} {token_in.symbol()} for {token_out.symbol()}")

    if token_in.allowance(SAFE, COWSWAP_RELAYER) < amount:
        token_in.approve(COWSWAP_RELAYER, amount)

    quote = cowswap_quote(
        from_address=SAFE.address,
        sell_token=token_in.address,
        buy_token=token_out.address,
        amount=amount,
    )

    cowswap_limit_sell(
        safe=SAFE,
        sell_token=token_in,
        buy_token=token_out,
        sell_amount=quote["sell_amount"],
        buy_amount=int(quote["buy_amount"] * 0.995),  # 0.5% slippage
    )
    print("🐮 Moo...")
```

## Setting up the Repository

If you want to use Robowoofy to queue txns to your own Safe:

1. **Use this repo as a template**
   - Click **“Use this template”** on GitHub (top right of the repo)
   - Create your own repository (e.g. `my-very-safe-safe`)

2. **Configure Secrets and Variables**
   - Go to **Settings --> Secrets and variables --> Actions**
   - Add the following (based on `.env.example`):
     ```
     ROBOWOOFY_SIGNER_PK=<private key of the EOA proposer>
     ETHERSCAN_TOKEN=<your Etherscan API key>
     TG_BOT_ACCESS_TOKEN=<Telegram bot token>
     TG_GROUP_CHAT_ID=<Telegram group chat ID for notifications>
     ETH_RPC_URL=<Ethereum RPC URL>
     ```
   - Make sure all variables match the `.env.example` format
   - In `src/config.py`, set your Safe address per network in the `NETWORKS` mapping

3. **Commit your function**
   - Modify `src/woof.py` to include your transaction logic
   - Push your branch and open a PR

4. **Trigger a run**
   - Comment on your PR with:
     ```
     /run fn=woofy network=eth send=false
     ```
   - Robowoofy will:
     - React with 👀 and 🚀  
     - Perform a dry run  
     - Post results and logs as a comment  
     - If `send=true` and run succeeds, it will queue the txn and label and close the PR automatically

### Default values

If any parameters are missing from the `/run` comment, the following defaults are applied:

| Parameter | Default | Description |
|------------|----------|-------------|
| `fn` | `woofy` | Function name to execute |
| `network` | `eth` | Network to use (must exist in `network-config.yaml`) |
| `send` | `false` | If `false`, performs a dry run; if `true`, proposes a Safe txn |
| `delete-branch-after-send` | `true` | If `true`, deletes the branch after successful send; if `false`, keeps it |

Commenting just `/run` is equivalent to `/run fn=woofy network=eth send=false delete-branch-after-send=true`

## Docker Usage

You can reproduce the same environment locally as CI:

```bash
# Build
docker build -t robowoofy-ng .

# Run
docker run -it --rm --env-file .env -v $(pwd):/robowoofy-ng robowoofy-ng bash
```

Inside the container, run:
```bash
brownie run src/woof.py woofy --network eth-fork
```

## Code Style

Format and lint code with ruff:
```bash
# Format code
ruff format .

# Lint code
ruff check .

# Fix fixable lint issues
ruff check --fix .
```