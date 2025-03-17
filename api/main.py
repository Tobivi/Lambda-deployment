from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from query_engine import get_best_swap_path, parse_swap_query
from data_fetcher import get_swap_transactions
from vector_store import store_swap_transactions
from swap_executor import SwapExecutor, parse_path_from_advice
import uvicorn
from mangum import Mangum
import json
import os
import time
from datetime import datetime

app = FastAPI()

swap_executor = SwapExecutor(network="mainnet", test_mode=True)

class SwapQuery(BaseModel):
    query: str

class SwapDetails(BaseModel):
    from_token: str
    to_token: str
    amount: float
    dex: str
    slippage: float

class SwapExecutionResponse(BaseModel):
    success: bool
    tx_hash: Optional[str] = None
    message: str

@app.get("/")
def welcome():
    """Welcome message for the API."""
    return {"message": "Welcome to the Akeru Swap Path Recommendation API!"}

@app.get("/swap-history/{wallet_address}")
def display_swap_history(wallet_address: str):
    """Display recent swap history for a wallet address."""
    if not wallet_address:
        raise HTTPException(status_code=400, detail="Wallet address is required.")
    
    print(f"\n⏳ Fetching transaction history for wallet: {wallet_address}...")
    start_time = time.time()
    
    cached_files = [f for f in os.listdir('.') if f.startswith(f"wallet_data_{wallet_address[:8]}") and f.endswith('.json')]
    
    if cached_files:
        latest_file = max(cached_files, key=os.path.getctime)
        print(f"✅ Found cached data: {latest_file}")
        
        with open(latest_file, 'r') as f:
            wallet_data = json.load(f)
            
        swap_transactions = wallet_data.get("swap_transactions", [])
        if not swap_transactions and "external_transactions" in wallet_data:
            print("⏳ Processing swap transactions from cached data...")
            swap_transactions = get_swap_transactions(wallet_address)
    else:
        transactions = get_swap_transactions(wallet_address)
        
        try:
            print("⏳ Storing transaction data for future reference...")
            store_swap_transactions(transactions)
            print("✅ Transaction data stored successfully")
        except Exception as e:
            print(f"⚠️ Could not store transaction data: {str(e)}")
            
        swap_transactions = transactions
        
    elapsed_time = time.time() - start_time
    print(f"✅ Data retrieval completed in {elapsed_time:.2f} seconds")
    
    return {"swap_transactions": swap_transactions}

@app.post("/get-swap-path")
def get_swap_path(swap_query: SwapQuery):
    """Get the best swap path for a given query."""
    query = swap_query.query
    
    if not query:
        raise HTTPException(status_code=400, detail="Swap query is required.")
    
    print(f"\n⏳ Generating optimal swap path for query: {query}...")
    start_time = time.time()
    
    advice, swap_details = get_best_swap_path(query)
    
    elapsed_time = time.time() - start_time
    print(f"\n🚀 Best Swap Path Recommendation (generated in {elapsed_time:.2f}s):")
    print("=========================================")
    print(advice)
    print("=========================================")
    
    return {"advice": advice, "swap_details": swap_details}

@app.post("/execute-swap")
def execute_swap(swap_details: SwapDetails, test_mode: bool = Query(default=True)):
    """Execute a swap based on the provided swap details."""
    try:
        if not swap_details:
            raise HTTPException(status_code=400, detail="Invalid swap details provided.")
        
        from_token = swap_details.from_token
        to_token = swap_details.to_token
        amount = swap_details.amount
        dex = swap_details.dex
        slippage = swap_details.slippage
        
        print("\n🔄 Swap Details:")
        print(f"   From: {amount} {from_token}")
        print(f"   To: {to_token}")
        print(f"   DEX: {dex}")
        print(f"   Slippage: {slippage}%")
        
        print("\n⏳ Executing swap...")
        tx_hash = swap_executor.execute_swap(
            from_token=from_token,
            to_token=to_token,
            amount=amount,
            dex_name=dex,
            slippage=slippage,
            destination_address=None,
            test_mode=test_mode
        )
        
        if tx_hash:
            return SwapExecutionResponse(success=True, tx_hash=tx_hash, message="Swap executed successfully!")
        else:
            return SwapExecutionResponse(success=False, message="Swap failed or was cancelled.")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing swap: {str(e)}")

@app.post("/connect-wallet")
def connect_wallet(private_key: str = Query(..., description="Your Ethereum private key"), test_mode: bool = Query(default=True)):
    """Connect a wallet using a private key."""
    try:
        global swap_executor
        swap_executor = SwapExecutor(network="mainnet", test_mode=test_mode)
        
        wallet_loaded = swap_executor.load_wallet(private_key)
        if not wallet_loaded:
            raise HTTPException(status_code=400, detail="Failed to load wallet. Please check the private key.")
        
        return {"success": True, "message": "Wallet connected successfully!"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error connecting wallet: {str(e)}")

handler = Mangum(app)

def lambda_handler(event, context):
    """AWS Lambda handler function that uses Mangum to process API Gateway events."""
    return handler(event, context)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)