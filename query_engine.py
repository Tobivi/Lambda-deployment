from llm_model import generate_swap_advice
from vector_store import get_optimal_swap_paths
import re
import os
import requests
import json
from config import TOKEN_ADDRESSES
from dotenv import load_dotenv

load_dotenv()

ONE_INCH_API_KEY = os.getenv("ONE_INCH_API_KEY")

def get_1inch_swap_data(from_token, to_token, amount):
    """
    Fetches the best swap path from the 1inch API.
    
    Args:
        from_token: The token to swap from (symbol or address)
        to_token: The token to swap to (symbol or address)
        amount: The amount to swap (in from_token's units)
    
    Returns:
        Dictionary containing the best swap path from 1inch API
    """
    from_address = TOKEN_ADDRESSES.get(from_token, from_token)
    to_address = TOKEN_ADDRESSES.get(to_token, to_token)
    
    url = "https://api.1inch.dev/swap/v5.2/1/quote"
    
    params = {
        "fromTokenAddress": from_address,
        "toTokenAddress": to_address,
        "amount": int(amount * 1e18),
    }
    
    headers = {
        "Authorization": f"Bearer {ONE_INCH_API_KEY}",
        "Accept": "application/json",
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        # Parse and return the JSON response
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching 1inch swap data: {str(e)}")
        if 'response' in locals():
            print(f"Response: {response.text}")
        return None

def parse_swap_query(query):
    """
    Parses a natural language swap query to extract tokens and amount.
    
    Examples:
    - "How to swap 0.5 ETH to USDC?"
    - "Best path from DAI to WBTC"
    
    Returns:
        tuple: (from_token, to_token, amount)
    """
    amount_pattern = r'(\d+(?:\.\d+)?)\s*([A-Za-z]+)'
    token_pattern = r'(?:from|swap|convert|exchange)\s+(\d+(?:\.\d+)?)?\s*([A-Za-z]+)\s+(?:to|for|into)\s+([A-Za-z]+)'
    
    token_match = re.search(token_pattern, query, re.IGNORECASE)
    if token_match:
        amount = token_match.group(1)
        from_token = token_match.group(2).upper()
        to_token = token_match.group(3).upper()
        
        return from_token, to_token, float(amount) if amount else None
    
    tokens = re.findall(r'[A-Z]{2,}', query.upper())
    amount_match = re.search(amount_pattern, query, re.IGNORECASE)
    
    if len(tokens) >= 2 and amount_match:
        amount = float(amount_match.group(1))
        token = amount_match.group(2).upper()
        
        if token == tokens[0]:
            return tokens[0], tokens[1], amount
        else:
            return tokens[0], tokens[1], None
    
    elif len(tokens) >= 2:
        return tokens[0], tokens[1], None
    
    return None, None, None


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
        "from_token": None,
        "to_token": None,
        "amount": None,
        "dex": None,
        "slippage": None 
    }
    
    lines = advice.split('\n')
    for line in lines:
        if "→" in line:
            path_tokens = [t.strip() for t in line.split("→")]
            valid_tokens = [t for t in path_tokens if t in TOKEN_ADDRESSES]
            if valid_tokens:
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
    
    dex_matches = re.findall(r'(Uniswap V[23]|SushiSwap|1inch)', advice, re.IGNORECASE)
    if dex_matches:
        swap_details["dex"] = dex_matches[0] 
    
    return swap_details


def get_best_swap_path(query):
    """
    Determines the best swap path based on:
    1. Historical data analysis (if available)
    2. 1inch API data (if historical data is unavailable)
    
    Returns:
        tuple: (LLM advice, swap_details dictionary)
    """
    from_token, to_token, amount = parse_swap_query(query)
    
    if not from_token or not to_token:
        return generate_swap_advice(f"Could not parse swap details from query: '{query}'. Please advise on best practices for crypto swaps."), None
    
    historical_paths = get_optimal_swap_paths(from_token, to_token, amount)
    
    one_inch_data = None
    if amount is not None:
        print("Fetching 1inch API data...")
        one_inch_data = get_1inch_swap_data(from_token, to_token, amount)
    
    historical_context = ""
    if historical_paths:
        best_historical_path = historical_paths[0]
        historical_context = f"""
Based on historical swap data:
- Path: {best_historical_path['path']} on {best_historical_path['dex']}
- Average Rate: {best_historical_path.get('avgRate', 0):.6f}
- Times Used: {best_historical_path.get('count', 0)}
"""
    
    one_inch_context = ""
    if one_inch_data:
        estimated_amount_out = int(one_inch_data.get('toTokenAmount', 0)) / 1e6 
        estimated_gas = one_inch_data.get('estimatedGas', 0)
        one_inch_context = f"""
Based on 1inch API data:
- Estimated Amount Out: {estimated_amount_out} {to_token}
- Estimated Gas: {estimated_gas}
"""
    
    enriched_query = f"""
I need to find the best swap path for the following:
- From: {from_token}
- To: {to_token}
{f'- Amount: {amount} {from_token}' if amount else ''}

{historical_context}

{one_inch_context}

Based on the above data and your knowledge of DeFi, what is the optimal swap path? 
Consider gas costs, slippage, and overall efficiency. 
Please provide step-by-step instructions on how to execute this swap.

At the end of your response, include a JSON object with the following structure:
{{
    "from_token": "{from_token}",
    "to_token": "{to_token}",
    "amount": {amount},
    "dex": "Uniswap V3",  // or the recommended DEX
    "slippage": 0.5  // or the recommended slippage
}}
"""
    
    llm_advice = generate_swap_advice(enriched_query)
    
    json_match = re.search(r'\{.*\}', llm_advice, re.DOTALL)
    if json_match:
        swap_details = json.loads(json_match.group(0))
    else:
        swap_details = None
    
    return llm_advice, swap_details