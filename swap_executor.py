import os
from web3 import Web3
from web3.middleware import construct_sign_and_send_raw_middleware
from web3.middleware import geth_poa_middleware
from data_fetcher import get_dex_liquidity
from eth_account import Account
from dotenv import load_dotenv
import json
import time
from datetime import datetime
import getpass
import re

load_dotenv()

ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY")

ETH_MAINNET = f"https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
ETH_GOERLI = f"https://eth-goerli.g.alchemy.com/v2/{ALCHEMY_API_KEY}"

UNISWAP_V2_ROUTER_ABI = json.loads('''
[
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactTokensForTokens",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactETHForTokens",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactTokensForETH",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]
''')

ERC20_ABI = json.loads('''
[
    {
        "constant": false,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": false,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": true,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "payable": false,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": true,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "payable": false,
        "stateMutability": "view",
        "type": "function"
    }
]
''')

TOKEN_ADDRESSES = {
    "ETH": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
    "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
    "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599"
}

DEX_ROUTER_ADDRESSES = {
    "Uniswap V2": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
    "Uniswap V3": "0xE592427A0AEce92De3Edee1F18E0157C05861564",
    "SushiSwap": "0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F",
    "1inch": "0x1111111254fb6c44bAC0beD2854e76F90643097d"
}

def parse_path_from_advice(advice):
    """
    Extract the recommended swap path from the LLM-generated advice.
    This function dynamically parses the swap details from the LLM's advice.
    
    Args:
        advice: The LLM-generated swap advice
        
    Returns:
        dict: Parsed swap details including dex, path, slippage, etc.
    """
    swap_details = {
        "dex": None,
        "path": [], 
        "slippage": None,
        "from_token": None,
        "to_token": None,
        "amount": None
    }
    
    dex_matches = [
        dex for dex in DEX_ROUTER_ADDRESSES.keys() 
        if dex.lower() in advice.lower()
    ]
    
    if dex_matches:
        swap_details["dex"] = dex_matches[0]
    
    lines = advice.split('\n')
    for line in lines:
        if "→" in line:
            path_tokens = [t.strip() for t in line.split("→")]
            valid_tokens = [t for t in path_tokens if t in TOKEN_ADDRESSES]
            if valid_tokens:
                swap_details["path"] = valid_tokens
                swap_details["from_token"] = valid_tokens[0]
                swap_details["to_token"] = valid_tokens[-1]
    
    amount_match = re.search(r'(\d+(?:\.\d+)?)\s*([A-Za-z]+)', advice)
    if amount_match:
        amount_str, token = amount_match.groups()
        if token == swap_details["from_token"]:
            swap_details["amount"] = float(amount_str)
    
    slippage_match = re.search(r'slippage:\s*(\d+(?:\.\d+)?)%', advice, re.IGNORECASE)
    if slippage_match:
        swap_details["slippage"] = float(slippage_match.group(1))
    
    return swap_details

class SwapExecutor:
    def __init__(self, network="mainnet", test_mode=True, private_key=None):
        """
        Initialize the SwapExecutor with network connection.
        
        Args:
            network: "mainnet" or "goerli"
            test_mode: If True, will simulate transactions without sending
            private_key: Optional private key to initialize the wallet
        """
        self.test_mode = test_mode
        
        if network == "mainnet":
            self.web3 = Web3(Web3.HTTPProvider(ETH_MAINNET))
            self.chain_id = 1
        elif network == "goerli":
            self.web3 = Web3(Web3.HTTPProvider(ETH_GOERLI))
            self.web3.middleware_onion.inject(geth_poa_middleware, layer=0)
            self.chain_id = 5
        else:
            raise ValueError(f"Unsupported network: {network}")
            
        if not self.web3.is_connected():
            raise ConnectionError(f"Failed to connect to {network} network")
        
        self.account = None
        self.address = None
        
        if private_key:
            self.load_wallet(private_key)
        else:
            env_private_key = os.getenv("WALLET_PRIVATE_KEY")
            if env_private_key:
                self.load_wallet(env_private_key)
            else:
                print("No private key provided. Running in read-only mode.")
                print("Use load_wallet() method to connect a wallet.")
    
    def prompt_for_private_key(self):
        """
        Securely prompt the user to input their private key.
        
        Returns:
            The loaded private key
        """
        print("\n==== SECURE WALLET LOADING ====")
        print("WARNING: Never share your private key with anyone!")
        print("This key will only be used locally and won't be stored.\n")
        
        private_key = getpass.getpass("Enter your wallet private key: ")
        
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
            
        if len(private_key) != 66:  # 0x + 64 hex chars
            print("Warning: The key format doesn't appear to be a standard Ethereum private key.")
            confirm = input("Do you want to continue anyway? (y/n): ")
            if confirm.lower() != 'y':
                return None
        
        return private_key
        
    def load_wallet(self, private_key=None):
        """
        Load a wallet using a private key.
        
        Args:
            private_key: The private key to use. If None, will prompt securely.
            
        Returns:
            The wallet address
        """
        if not private_key:
            private_key = self.prompt_for_private_key()
            if not private_key:
                raise ValueError("No private key provided")
        
        try:
            self.account = Account.from_key(private_key)
            self.address = self.account.address
            
            eth_balance = self.web3.eth.get_balance(self.address)
            eth_balance_ether = self.web3.from_wei(eth_balance, 'ether')
            
            print(f"Wallet loaded: {self.address[:6]}...{self.address[-4:]}")
            print(f"ETH Balance: {eth_balance_ether:.4f} ETH")
            
            return self.address
            
        except Exception as e:
            print(f"Error loading wallet: {str(e)}")
            return None
    
    def _get_token_contract(self, token_address):
        """Create a contract instance for the given token address"""
        return self.web3.eth.contract(address=self.web3.to_checksum_address(token_address), abi=ERC20_ABI)
    
    def _get_router_contract(self, dex_name):
        """Create a contract instance for the given DEX router"""
        if dex_name not in DEX_ROUTER_ADDRESSES:
            raise ValueError(f"Unsupported DEX: {dex_name}")
            
        router_address = self.web3.to_checksum_address(DEX_ROUTER_ADDRESSES[dex_name])
        return self.web3.eth.contract(address=router_address, abi=UNISWAP_V2_ROUTER_ABI)
    
    def get_token_balance(self, token_symbol):
        """
        Get the balance of a token for the connected wallet.
        """
        if not self.address:
            raise ValueError("No wallet connected. Use load_wallet() first.")
            
        if token_symbol == "ETH":
            balance_wei = self.web3.eth.get_balance(self.address)
            return self.web3.from_wei(balance_wei, 'ether')
            
        if token_symbol not in TOKEN_ADDRESSES:
            raise ValueError(f"Unknown token: {token_symbol}")
            
        token_address = self.web3.to_checksum_address(TOKEN_ADDRESSES[token_symbol])
        token_contract = self._get_token_contract(token_address)
        
        balance = token_contract.functions.balanceOf(self.address).call()
        decimals = token_contract.functions.decimals().call()
        
        balance_readable = balance / (10 ** decimals)
        return balance_readable
    
    def approve_token(self, token_symbol, dex_name, amount=None):
        """
        Approve a DEX router to spend tokens from this wallet.
        
        Args:
            token_symbol: Symbol of the token to approve
            dex_name: Name of the DEX whose router needs approval
            amount: Amount to approve (None for unlimited)
        """
        if not self.account:
            raise ValueError("No wallet connected. Use load_wallet() first.")
            
        if token_symbol == "ETH":
            print("No approval needed for native ETH")
            return True
            
        if token_symbol not in TOKEN_ADDRESSES:
            raise ValueError(f"Unknown token: {token_symbol}")
            
        if dex_name not in DEX_ROUTER_ADDRESSES:
            raise ValueError(f"Unknown DEX: {dex_name}")
            
        token_address = self.web3.to_checksum_address(TOKEN_ADDRESSES[token_symbol])
        router_address = self.web3.to_checksum_address(DEX_ROUTER_ADDRESSES[dex_name])
        
        token_contract = self._get_token_contract(token_address)
        
        approval_amount = amount if amount is not None else 2**256 - 1
        
        gas_estimate = token_contract.functions.approve(
            router_address, 
            approval_amount
        ).estimate_gas({'from': self.address})
        
        gas_price = self.web3.eth.gas_price
        
        tx = token_contract.functions.approve(
            router_address,
            approval_amount
        ).build_transaction({
            'from': self.address,
            'gas': int(gas_estimate * 1.2), 
            'gasPrice': gas_price,
            'nonce': self.web3.eth.get_transaction_count(self.address),
            'chainId': self.chain_id
        })
        
        if self.test_mode:
            print(f"TEST MODE: Would approve {token_symbol} for {dex_name}")
            return True
            
        signed_tx = self.web3.eth.account.sign_transaction(tx, self.account.key)
        tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        print(f"Approval transaction sent: {tx_hash.hex()}")
        
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        return receipt.status == 1
    
    def generate_swap_transaction(self, from_token, to_token, amount, dex_name="Uniswap V2", slippage=0.5, destination_address=None):
        """
        Generate a swap transaction for the user to sign.
        
        Args:
            from_token: Symbol of the token to swap from
            to_token: Symbol of the token to swap to
            amount: Amount to swap (in the from_token's units)
            dex_name: Name of the DEX to use
            slippage: Maximum acceptable slippage percentage
            destination_address: Optional address to receive the swapped tokens (defaults to self.address)
            
        Returns:
            Dictionary containing the transaction data and details
        """
        if not self.account:
            raise ValueError("No wallet connected. Use load_wallet() first.")
            
        destination = destination_address if destination_address else self.address
        
        if destination:
            try:
                destination = self.web3.to_checksum_address(destination)
            except ValueError:
                raise ValueError(f"Invalid destination address format: {destination}")
            
        if from_token not in TOKEN_ADDRESSES and from_token != "ETH":
            raise ValueError(f"Unknown source token: {from_token}")
            
        if to_token not in TOKEN_ADDRESSES and to_token != "ETH":
            raise ValueError(f"Unknown destination token: {to_token}")
            
        if from_token == "ETH":
            balance = self.get_token_balance("ETH")
            if balance < amount:
                raise ValueError(f"Insufficient ETH balance: {balance} < {amount}")
        else:
            balance = self.get_token_balance(from_token)
            if balance < amount:
                raise ValueError(f"Insufficient {from_token} balance: {balance} < {amount}")
        
        router = self._get_router_contract(dex_name)
        router_address = self.web3.to_checksum_address(DEX_ROUTER_ADDRESSES[dex_name])

        path = []
        if from_token == "ETH":
            path.append(self.web3.to_checksum_address(TOKEN_ADDRESSES["WETH"]))
        else:
            path.append(self.web3.to_checksum_address(TOKEN_ADDRESSES[from_token]))
            
        if to_token == "ETH":
            path.append(self.web3.to_checksum_address(TOKEN_ADDRESSES["WETH"]))
        else:
            path.append(self.web3.to_checksum_address(TOKEN_ADDRESSES[to_token]))
        
        deadline = int(time.time() + 30 * 60)
        
        if from_token == "ETH":
            amount_in_wei = self.web3.to_wei(amount, 'ether')
        else:
            token_contract = self._get_token_contract(TOKEN_ADDRESSES[from_token])
            decimals = token_contract.functions.decimals().call()
            amount_in_wei = int(amount * (10 ** decimals))
        
        
        amount_out_min = int(amount_in_wei * (1 - slippage / 100))
        
        if from_token == "ETH" and to_token != "ETH":
            tx_params = {
                'from': self.address,
                'value': amount_in_wei,
                'nonce': self.web3.eth.get_transaction_count(self.address),
                'chainId': self.chain_id
            }
            
            try:
                gas_estimate = router.functions.swapExactETHForTokens(
                    amount_out_min,
                    path,
                    destination,
                    deadline
                ).estimate_gas(tx_params)
                tx_params['gas'] = int(gas_estimate * 1.2) 
            except Exception as e:
                print(f"Gas estimation failed: {str(e)}")
                tx_params['gas'] = 300000 
            
            tx = router.functions.swapExactETHForTokens(
                amount_out_min,
                path,
                destination,
                deadline
            ).build_transaction(tx_params)
            
        elif from_token != "ETH" and to_token == "ETH":
            tx_params = {
                'from': self.address,
                'nonce': self.web3.eth.get_transaction_count(self.address),
                'chainId': self.chain_id
            }
            
            try:
                gas_estimate = router.functions.swapExactTokensForETH(
                    amount_in_wei,
                    amount_out_min,
                    path,
                    destination,
                    deadline
                ).estimate_gas(tx_params)
                tx_params['gas'] = int(gas_estimate * 1.2)
            except Exception as e:
                print(f"Gas estimation failed: {str(e)}")
                tx_params['gas'] = 300000  # Fallback gas limit
            
            tx = router.functions.swapExactTokensForETH(
                amount_in_wei,
                amount_out_min,
                path,
                destination,  # Use destination address here
                deadline
            ).build_transaction(tx_params)
            
        else:
            # Token to Token
            tx_params = {
                'from': self.address,
                'nonce': self.web3.eth.get_transaction_count(self.address),
                'chainId': self.chain_id
            }
            
            # Estimate gas
            try:
                gas_estimate = router.functions.swapExactTokensForTokens(
                    amount_in_wei,
                    amount_out_min,
                    path,
                    destination,  # Use destination address here
                    deadline
                ).estimate_gas(tx_params)
                tx_params['gas'] = int(gas_estimate * 1.2)
            except Exception as e:
                print(f"Gas estimation failed: {str(e)}")
                tx_params['gas'] = 300000  # Fallback gas limit
            
            tx = router.functions.swapExactTokensForTokens(
                amount_in_wei,
                amount_out_min,
                path,
                destination,  # Use destination address here
                deadline
            ).build_transaction(tx_params)
        
        if self.test_mode:
            print(f"TEST MODE: Would swap {amount} {from_token} to {to_token} via {dex_name}")
            print(f"Path: {path}")
            print(f"Minimum amount out: {amount_out_min}")
            print(f"Destination address: {destination}")
            return {
                "test_mode": True,
                "tx_data": tx,
                "details": {
                    "from_token": from_token,
                    "to_token": to_token,
                    "amount": amount,
                    "dex": dex_name,
                    "slippage": slippage,
                    "destination": destination,
                    "path": path,
                    "min_amount_out": amount_out_min
                }
            }
            
        return {
            "tx_data": tx,
            "details": {
                "from_token": from_token,
                "to_token": to_token,
                "amount": amount,
                "dex": dex_name,
                "slippage": slippage,
                "destination": destination,
                "path": path,
                "min_amount_out": amount_out_min
            }
        }
    
    def execute_swap(self, from_token, to_token, amount, dex_name="Uniswap V2", slippage=0.5, destination_address=None, test_mode=None):
        """
        Execute a token swap.
        
        Args:
            from_token: Symbol of the token to swap from
            to_token: Symbol of the token to swap to
            amount: Amount to swap (in the from_token's units)
            dex_name: Name of the DEX to use
            slippage: Maximum acceptable slippage percentage
            destination_address: Optional address to receive the swapped tokens (defaults to self.address)
            test_mode: Whether to run in test mode (simulate without executing)
            
        Returns:
            Transaction hash if successful
        """
        if test_mode is None:
            test_mode = self.test_mode  # Use instance-level test_mode if not provided
        
        if not self.account:
            raise ValueError("No wallet connected. Use load_wallet() first.")
            
        # Generate the swap transaction
        swap_data = self.generate_swap_transaction(from_token, to_token, amount, dex_name, slippage, destination_address)
        
        if test_mode:
            print(f"TEST MODE: Would execute swap with details: {swap_data['details']}")
            return "test_tx_hash"
            
        # Sign and send transaction
        signed_tx = self.web3.eth.account.sign_transaction(swap_data['tx_data'], self.account.key)
        tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        print(f"Swap transaction sent: {tx_hash.hex()}")
        print(f"Swapping {amount} {from_token} to {to_token}...")
        print(f"Destination address: {destination_address}")
        
        # Wait for the transaction to be mined
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
        
        if receipt.status == 1:
            print(f"Swap successful! Transaction hash: {tx_hash.hex()}")
            return tx_hash.hex()
        else:
            print(f"Swap failed! Transaction hash: {tx_hash.hex()}")
            return None