import requests
from brownie import chain

COWSWAP_RELAYER = "0xC92E8bdf79f0507f65a392b0ab4667716BFE0110"


def cowswap_quote(from_address: str, sell_token: str, buy_token: str, amount: int, is_sell: bool = True):
    data = {
        "from": from_address,
        "sellToken": sell_token,
        "buyToken": buy_token,
        "kind": "sell" if is_sell else "buy",
        "priceQuality": "verified",
    }
    data["sellAmountBeforeFee" if is_sell else "buyAmountAfterFee"] = str(amount)

    response = requests.post("https://api.cow.fi/mainnet/api/v1/quote", json=data, timeout=10)
    response.raise_for_status()

    resp = response.json()
    return {
        "sell_amount": int(resp["quote"]["sellAmount"]),
        "buy_amount": int(resp["quote"]["buyAmount"]),
        "fee_amount": int(resp["quote"]["feeAmount"]),
        "quote_id": resp["id"],
        "verified": resp["verified"],
    }


def cowswap_limit_sell(
    safe, sell_token, buy_token, sell_amount, buy_amount, receiver=None, deadline_delay=3600, partially_fillable=True
):
    gnosis_settlement = safe.contract("0x9008D19f58AAbD9eD0D60971565AA8510560ab41")  # Contract used to sign the order

    order = {
        "sellToken": sell_token.address,
        "buyToken": buy_token.address,
        "sellAmount": str(int(sell_amount)),
        "buyAmount": str(int(buy_amount)),
        "validTo": chain.time() + deadline_delay,
        "appData": "0x2B8694ED30082129598720860E8E972F07AA10D9B81CAE16CA0E2CFB24743E24",  # Yearn ref link
        "feeAmount": "0",
        "kind": "sell",
        "partiallyFillable": partially_fillable,
        "receiver": receiver or safe.address,
        "signature": safe.address,
        "from": safe.address,
        "sellTokenBalance": "erc20",
        "buyTokenBalance": "erc20",
        "signingScheme": "presign",  # This tells the api you are going to sign on chain
    }

    response = requests.post("https://api.cow.fi/mainnet/api/v1/orders", json=order, timeout=10)
    response.raise_for_status()

    order_uid = response.json()
    print(f"Order: https://explorer.cow.fi/orders/{order_uid}")

    gnosis_settlement.setPreSignature(order_uid, True)
