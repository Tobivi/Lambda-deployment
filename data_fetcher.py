import requests
import json
import time
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY")
if not ALCHEMY_API_KEY:
    ALCHEMY_API_KEY = input("Please enter your Alchemy API key: ")

DEX_ROUTERS = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2",
    "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap V3",
    "0x1111111254fb6c44bac0bed2854e76f90643097d": "1inch",
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f": "SushiSwap",
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff": "0x Protocol",
    "0x11111112542d85b3ef69ae05771c2dccff4faa26": "1inch V4",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "Uniswap V3 Router 2",
}

def get_dex_liquidity(token_pair, dex_name="Uniswap V2"):
    """
    Fetches real-time liquidity for a token pair from a specific DEX.
    
    Args:
        token_pair: Tuple of (from_token, to_token)
        dex_name: Name of the DEX (e.g., "Uniswap V2", "SushiSwap")
    
    Returns:
        Dictionary containing liquidity data
    """
    from_token, to_token = token_pair
    
    if dex_name == "Uniswap V2":
        liquidity_url = f"https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2"
        query = f"""
        {{
            pair(id: "{from_token}_{to_token}") {{
                reserve0
                reserve1
                token0 {{
                    symbol
                }}
                token1 {{
                    symbol
                }}
            }}
        }}
        """
        try:
            response = requests.post(liquidity_url, json={'query': query})
            if response.status_code == 200:
                data = response.json()
                return data.get("data", {}).get("pair", {})
        except Exception as e:
            print(f"Error fetching liquidity from {dex_name}: {str(e)}")
    
    elif dex_name == "SushiSwap":
        pass
    
    return {}

def get_swap_transactions(wallet_address, max_results=100):
    """
    Extracts swap transactions from a wallet's transaction history.
    Specifically looks for interactions with known DEX routers.
    """
    print("Fetching swap transactions...")
    
    external_txs = get_external_transactions(wallet_address, max_results)
    token_transfers = get_token_transfers(wallet_address, max_results)
    
    swap_txs = []
    
    dex_tx_hashes = set()
    for tx in external_txs:
        to_address = tx.get("to", "").lower()
        if to_address in DEX_ROUTERS:
            tx_hash = tx.get("hash")
            if tx_hash:
                dex_tx_hashes.add(tx_hash)
                
                swap_tx = {
                    "hash": tx_hash,
                    "block_number": tx.get("blockNum"),
                    "timestamp": tx.get("metadata", {}).get("blockTimestamp"),
                    "dex": DEX_ROUTERS.get(to_address, "Unknown DEX"),
                    "from_wallet": wallet_address,
                    "router": to_address,
                    "value_eth": float(tx.get("value", 0)),
                    "input_tokens": [],
                    "output_tokens": []
                }
                swap_txs.append(swap_tx)
    
    swap_tx_map = {tx["hash"]: tx for tx in swap_txs}
    
    for transfer in token_transfers:
        tx_hash = transfer.get("hash")
        if tx_hash in dex_tx_hashes:
            swap_tx = swap_tx_map.get(tx_hash)
            if not swap_tx:
                continue
                
            if transfer.get("direction") == "sent" and transfer.get("from", "").lower() == wallet_address.lower():
                token_info = {
                    "token_address": transfer.get("rawContract", {}).get("address"),
                    "symbol": transfer.get("asset"),
                    "amount": float(transfer.get("value", 0)),
                    "decimals": transfer.get("decimals", 18)
                }
                swap_tx["input_tokens"].append(token_info)
                
            elif transfer.get("direction") == "received" and transfer.get("to", "").lower() == wallet_address.lower():
                token_info = {
                    "token_address": transfer.get("rawContract", {}).get("address"),
                    "symbol": transfer.get("asset"),
                    "amount": float(transfer.get("value", 0)),
                    "decimals": transfer.get("decimals", 18)
                }
                swap_tx["output_tokens"].append(token_info)
    
    for swap_tx in swap_txs:
        if swap_tx["input_tokens"] and swap_tx["output_tokens"]:
            input_symbols = [t["symbol"] for t in swap_tx["input_tokens"] if t["symbol"]]
            output_symbols = [t["symbol"] for t in swap_tx["output_tokens"] if t["symbol"]]
            
            swap_tx["path"] = " → ".join(input_symbols + output_symbols)
            
            if len(input_symbols) == 1 and len(output_symbols) == 1:
                input_amount = swap_tx["input_tokens"][0]["amount"]
                output_amount = swap_tx["output_tokens"][0]["amount"]
                if input_amount > 0:
                    swap_tx["rate"] = output_amount / input_amount
    
    swap_txs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    
    print(f"Found {len(swap_txs)} swap transactions")
    return swap_txs


def fetch_all_wallet_data(wallet_address, max_results=1000):
    """
    Fetches comprehensive blockchain data for a wallet address.
    Returns a dictionary with different categories of blockchain data.
    """
    if max_results > 1000:
        print("Warning: Alchemy API limits maxCount to 1000. Setting to 1000.")
        max_results = 1000
    
    data = {
        "token_transfers": get_token_transfers(wallet_address, max_results),
        "nft_transfers": get_nft_transfers(wallet_address, max_results),
        "internal_transactions": get_internal_transactions(wallet_address, max_results),
        "external_transactions": get_external_transactions(wallet_address, max_results),
        "token_balances": get_token_balances(wallet_address),
        "nft_balances": get_nft_balances(wallet_address),
        "wallet_activity": get_wallet_activity(wallet_address),
        "contract_interactions": get_contract_interactions(wallet_address, max_results),
        "swap_transactions": get_swap_transactions(wallet_address, max_results)
    }
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"wallet_data_{wallet_address[:8]}_{timestamp}.json"
    
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Complete wallet data saved to {filename}")
    return data

def make_alchemy_request(method, params):
    """
    Makes a request to the Alchemy API with the given method and parameters.
    Handles rate limiting and retries.
    """
    url = f"https://eth-mainnet.alchemyapi.io/v2/{ALCHEMY_API_KEY}"
    
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=payload)
            
            if response.status_code != 200:
                print(f"Error response (HTTP {response.status_code}):")
                print(f"Request URL: {url}")
                print(f"Request payload: {json.dumps(payload)}")
                print(f"Response text: {response.text}")
            
            response.raise_for_status()
            
            response_json = response.json()
            if "error" in response_json:
                print(f"API Error: {response_json['error']}")
                print(f"Request method: {method}")
                print(f"Request params: {params}")
                
                if "rate limit" in str(response_json['error']).lower():
                    wait_time = (2 ** attempt) * 2 
                    print(f"Rate limited. Waiting {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                return None
            
            return response_json
            
        except requests.exceptions.RequestException as e:
            print(f"Request failed (attempt {attempt+1}/{max_retries}): {e}")
            print(f"Request method: {method}")
            print(f"Request params: {params}")
            
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                return None
    
    return None

def get_token_transfers(wallet_address, max_results=1000):
    """
    Fetches all ERC-20 token transfers (both sent and received) for a wallet.
    """
    print("Fetching ERC-20 token transfers...")
    
    max_count = format_max_count(max_results)
    
    sent_params = [{
        "fromBlock": "0x0",
        "toBlock": "latest",
        "fromAddress": wallet_address,
        "category": ["erc20"],
        "maxCount": max_count
    }]
    
    sent_response = make_alchemy_request("alchemy_getAssetTransfers", sent_params)
    sent_transfers = sent_response.get("result", {}).get("transfers", []) if sent_response else []
    
    received_params = [{
        "fromBlock": "0x0",
        "toBlock": "latest",
        "toAddress": wallet_address,
        "category": ["erc20"],
        "maxCount": max_count
    }]
    
    received_response = make_alchemy_request("alchemy_getAssetTransfers", received_params)
    received_transfers = received_response.get("result", {}).get("transfers", []) if received_response else []
    
    for transfer in sent_transfers:
        transfer["direction"] = "sent"
    
    for transfer in received_transfers:
        transfer["direction"] = "received"
    
    all_transfers = sent_transfers + received_transfers
    all_transfers.sort(key=lambda x: int(x.get("blockNum", "0x0"), 16), reverse=True)
    
    print(f"Found {len(all_transfers)} ERC-20 token transfers")
    return all_transfers

def get_nft_transfers(wallet_address, max_results=1000):
    """
    Fetches all NFT transfers (ERC-721 and ERC-1155) for a wallet.
    """
    print("Fetching NFT transfers...")
    
    categories = ["erc721", "erc1155"]
    max_count = format_max_count(max_results)
    
    sent_params = [{
        "fromBlock": "0x0",
        "toBlock": "latest",
        "fromAddress": wallet_address,
        "category": categories,
        "maxCount": max_count
    }]
    
    sent_response = make_alchemy_request("alchemy_getAssetTransfers", sent_params)
    sent_transfers = sent_response.get("result", {}).get("transfers", []) if sent_response else []
    
    received_params = [{
        "fromBlock": "0x0",
        "toBlock": "latest",
        "toAddress": wallet_address,
        "category": categories,
        "maxCount": max_count
    }]
    
    received_response = make_alchemy_request("alchemy_getAssetTransfers", received_params)
    received_transfers = received_response.get("result", {}).get("transfers", []) if received_response else []
    
    for transfer in sent_transfers:
        transfer["direction"] = "sent"
    
    for transfer in received_transfers:
        transfer["direction"] = "received"
    
    all_transfers = sent_transfers + received_transfers
    all_transfers.sort(key=lambda x: int(x.get("blockNum", "0x0"), 16), reverse=True)
    
    print(f"Found {len(all_transfers)} NFT transfers")
    return all_transfers

def get_internal_transactions(wallet_address, max_results=1000):
    """
    Fetches internal transactions (ETH transfers between contracts).
    """
    print("Fetching internal transactions...")
    
    max_count = format_max_count(max_results)
    
    sent_params = [{
        "fromBlock": "0x0",
        "toBlock": "latest",
        "fromAddress": wallet_address,
        "category": ["internal"],
        "maxCount": max_count
    }]
    
    sent_response = make_alchemy_request("alchemy_getAssetTransfers", sent_params)
    sent_transfers = sent_response.get("result", {}).get("transfers", []) if sent_response else []
    
    received_params = [{
        "fromBlock": "0x0",
        "toBlock": "latest",
        "toAddress": wallet_address,
        "category": ["internal"],
        "maxCount": max_count
    }]
    
    received_response = make_alchemy_request("alchemy_getAssetTransfers", received_params)
    received_transfers = received_response.get("result", {}).get("transfers", []) if received_response else []
    
    for transfer in sent_transfers:
        transfer["direction"] = "sent"
    
    for transfer in received_transfers:
        transfer["direction"] = "received"
    
    all_transfers = sent_transfers + received_transfers
    all_transfers.sort(key=lambda x: int(x.get("blockNum", "0x0"), 16), reverse=True)
    
    print(f"Found {len(all_transfers)} internal transactions")
    return all_transfers

def get_external_transactions(wallet_address, max_results=1000):
    """
    Fetches external transactions (normal ETH transfers).
    """
    print("Fetching external transactions...")
    
    max_count = format_max_count(max_results)
    
    sent_params = [{
        "fromBlock": "0x0",
        "toBlock": "latest",
        "fromAddress": wallet_address,
        "category": ["external"],
        "maxCount": max_count
    }]
    
    sent_response = make_alchemy_request("alchemy_getAssetTransfers", sent_params)
    sent_transfers = sent_response.get("result", {}).get("transfers", []) if sent_response else []
    
    received_params = [{
        "fromBlock": "0x0",
        "toBlock": "latest",
        "toAddress": wallet_address,
        "category": ["external"],
        "maxCount": max_count
    }]
    
    received_response = make_alchemy_request("alchemy_getAssetTransfers", received_params)
    received_transfers = received_response.get("result", {}).get("transfers", []) if received_response else []
    
    for transfer in sent_transfers:
        transfer["direction"] = "sent"
    
    for transfer in received_transfers:
        transfer["direction"] = "received"
    
    all_transfers = sent_transfers + received_transfers
    all_transfers.sort(key=lambda x: int(x.get("blockNum", "0x0"), 16), reverse=True)
    
    print(f"Found {len(all_transfers)} external transactions")
    return all_transfers

def get_token_balances(wallet_address):
    """
    Fetches current token balances for a wallet.
    """
    print("Fetching token balances...")
    
    params = [wallet_address, "erc20"]
    response = make_alchemy_request("alchemy_getTokenBalances", params)
    
    balances = response.get("result", {}).get("tokenBalances", []) if response else []
    
    enriched_balances = []
    for balance in balances:
        if int(balance.get("tokenBalance", "0x0"), 16) > 0:
            contract_address = balance.get("contractAddress")
            metadata = get_token_metadata(contract_address)
            
            if metadata:
                balance["metadata"] = metadata
            
            enriched_balances.append(balance)
    
    print(f"Found {len(enriched_balances)} tokens with non-zero balances")
    return enriched_balances

def get_token_metadata(contract_address):
    """
    Fetches metadata for a token contract.
    """
    params = [contract_address]
    response = make_alchemy_request("alchemy_getTokenMetadata", params)
    
    if response and "result" in response:
        return response["result"]
    return None

def get_nft_balances(wallet_address):
    """
    Fetches NFTs owned by a wallet.
    """
    print("Fetching NFT balances...")
    base_url = f"https://eth-mainnet.g.alchemy.com/nft/v2/{ALCHEMY_API_KEY}/getNFTs"
    params = {
        "owner": wallet_address,
        "pageSize": 100,
        "withMetadata": "false"
    }
    
    try:
        response = requests.get(base_url, params=params)
        if response.status_code != 200:
            print(f"NFT API Error (HTTP {response.status_code}): {response.text}")
            return []
        
        data = response.json()
        nfts = data.get("ownedNfts", [])
        total_count = data.get("totalCount", 0)
        
        print(f"Found {total_count} NFTs")
        return nfts
        
    except requests.exceptions.RequestException as e:
        print(f"NFT request failed: {e}")
        return []

def get_wallet_activity(wallet_address):
    """
    Fetches general activity stats for a wallet.
    """
    print("Analyzing wallet activity...")
    
    sent_params = [{
        "fromBlock": "0x0",
        "toBlock": "latest",
        "fromAddress": wallet_address,
        "category": ["external"],
        "maxCount": "0x1"
    }]
    
    oldest_response = make_alchemy_request("alchemy_getAssetTransfers", sent_params)
    
    recent_params = [{
        "fromBlock": "0x0",
        "toBlock": "latest",
        "fromAddress": wallet_address,
        "category": ["external"],
        "maxCount": "0x1",
        "order": "desc"
    }]
    
    recent_response = make_alchemy_request("alchemy_getAssetTransfers", recent_params)
    
    activity = {
        "first_transaction": None,
        "most_recent_transaction": None,
        "eth_balance": get_eth_balance(wallet_address),
        "is_contract": is_contract_address(wallet_address)
    }
    
    if oldest_response and "result" in oldest_response and oldest_response["result"].get("transfers"):
        activity["first_transaction"] = oldest_response["result"]["transfers"][0]
    
    if recent_response and "result" in recent_response and recent_response["result"].get("transfers"):
        activity["most_recent_transaction"] = recent_response["result"]["transfers"][0]
    
    return activity

def get_eth_balance(wallet_address):
    """
    Gets the ETH balance for a wallet.
    """
    params = [wallet_address, "latest"]
    response = make_alchemy_request("eth_getBalance", params)
    
    if response and "result" in response:
        balance_wei = int(response["result"], 16)
        balance_eth = balance_wei / 10**18
        return balance_eth
    
    return 0

def is_contract_address(wallet_address):
    """
    Checks if an address is a contract.
    """
    params = [wallet_address, "latest"]
    response = make_alchemy_request("eth_getCode", params)
    
    if response and "result" in response:
        return response["result"] != "0x"
    
    return False

def get_contract_interactions(wallet_address, max_results=1000):
    """
    Gets unique contract interactions for a wallet.
    """
    print("Analyzing contract interactions...")
    
    max_count = format_max_count(max_results)
    
    params = [{
        "fromBlock": "0x0",
        "toBlock": "latest", 
        "fromAddress": wallet_address,
        "category": ["external"],
        "maxCount": max_count
    }]
    
    response = make_alchemy_request("alchemy_getAssetTransfers", params)
    
    if not response or "result" not in response:
        return []
    
    transactions = response["result"].get("transfers", [])
    
    contract_interactions = {}
    for tx in transactions:
        to_address = tx.get("to")
        if to_address and is_contract_address(to_address):
            if to_address not in contract_interactions:
                contract_interactions[to_address] = {
                    "address": to_address,
                    "first_interaction": tx,
                    "interaction_count": 1
                }
            else:
                contract_interactions[to_address]["interaction_count"] += 1
    
    print(f"Found {len(contract_interactions)} unique contract interactions")
    return list(contract_interactions.values())

def format_max_count(max_results):
    """
    Format max_results as a proper hex string for Alchemy API.
    Ensures the value is within Alchemy's limits (0 < maxCount <= 0x3e8).
    """
    if max_results > 1000:
        max_results = 1000
    elif max_results <= 0:
        max_results = 1
    
    return f"0x{max_results:x}"

if __name__ == "__main__":
    print("==============================")
    print("Alchemy Blockchain Data Retriever")
    print("==============================")
    
    wallet_address = input("Enter Ethereum wallet address to analyze: ")
    if not wallet_address.startswith("0x") or len(wallet_address) != 42:
        print("Invalid Ethereum address format. Address should start with 0x and be 42 characters long.")
        exit(1)
    
    max_results = int(input("Maximum results per query (default 1000): ") or "1000")
    
    print(f"\nAnalyzing wallet: {wallet_address}")
    print("This may take several minutes depending on wallet activity...")
    
    start_time = time.time()
    wallet_data = fetch_all_wallet_data(wallet_address, max_results)
    elapsed_time = time.time() - start_time
    
    # Print summary
    print("\n==============================")
    print(f"Data retrieval completed in {elapsed_time:.2f} seconds")
    print("==============================")
    print(f"ERC-20 Transfers: {len(wallet_data['token_transfers'])}")
    print(f"NFT Transfers: {len(wallet_data['nft_transfers'])}")
    print(f"Internal Transactions: {len(wallet_data['internal_transactions'])}")
    print(f"External Transactions: {len(wallet_data['external_transactions'])}")
    print(f"Token Balances: {len(wallet_data['token_balances'])}")
    print(f"NFTs Owned: {len(wallet_data['nft_balances'])}")
    print(f"Contract Interactions: {len(wallet_data['contract_interactions'])}")
    print(f"ETH Balance: {wallet_data['wallet_activity']['eth_balance']:.4f} ETH")
    print("==============================")