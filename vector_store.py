import logging
import json
from pinecone import Pinecone, PineconeException
from sentence_transformers import SentenceTransformer
import os
from dotenv import load_dotenv

load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "crypto-swaps")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

def connect_to_pinecone():
    """Establish a connection to Pinecone and return the index."""
    try:
        logger.info("Connecting to Pinecone...")
        pc = Pinecone(api_key=PINECONE_API_KEY)
        index = pc.Index(PINECONE_INDEX_NAME)
        logger.info(f"Successfully connected to Pinecone index: {PINECONE_INDEX_NAME}")
        return pc, index
    except PineconeException as e:
        logger.error(f"Failed to connect to Pinecone: {str(e)}")
        raise Exception(f"Pinecone connection error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise Exception(f"Unexpected error: {str(e)}")

def store_swap_transactions(swap_transactions):
    """Embeds and stores swap transaction data in Pinecone."""
    pc, index = connect_to_pinecone()
    
    vectors = []
    for tx in swap_transactions:
        # Create rich descriptions for vectors
        descriptions = []
        
        # Basic swap info
        if "path" in tx:
            swap_path = tx.get("path", "")
            dex_name = tx.get("dex", "Unknown DEX")
            descriptions.append(f"Swap path: {swap_path} on {dex_name}")
        
        # Token details
        input_tokens = tx.get("input_tokens", [])
        output_tokens = tx.get("output_tokens", [])
        
        if input_tokens and output_tokens:
            input_str = ", ".join([f"{t.get('amount')} {t.get('symbol')}" for t in input_tokens if "symbol" in t])
            output_str = ", ".join([f"{t.get('amount')} {t.get('symbol')}" for t in output_tokens if "symbol" in t])
            descriptions.append(f"Swapped {input_str} for {output_str}")
        
        # Swap rate if available
        if "rate" in tx:
            rate = tx.get("rate")
            if rate:
                descriptions.append(f"Exchange rate: {rate}")
        
        # Final description for embedding
        swap_description = " ".join(descriptions)
        
        if swap_description:
            # Embed description
            vector = embedding_model.encode(swap_description).tolist()
            
            # Metadata for retrieval
            metadata = {
                "txHash": tx.get("hash", ""),
                "blockNumber": tx.get("block_number", ""),
                "timestamp": tx.get("timestamp", ""),
                "dex": tx.get("dex", "Unknown DEX"),
                "path": tx.get("path", ""),
                "description": swap_description,
                "swapRate": tx.get("rate", 0),
                "inputTokens": json.dumps(input_tokens),
                "outputTokens": json.dumps(output_tokens),
                "success": tx.get("success", True),  # Add success flag
                "efficiency": tx.get("efficiency", 1.0)  # Add efficiency metric
            }
            
            # Use tx hash as ID
            vectors.append((tx.get("hash", f"swap-{len(vectors)}"), vector, metadata))

    if vectors:
        index.upsert(vectors)
        logger.info(f"Stored {len(vectors)} swap transactions in Pinecone.")
    else:
        logger.warning("No valid swap transactions to store.")

def analyze_swap_success_rates(dex_name=None):
    """
    Analyzes swap success rates and efficiency metrics.
    
    Args:
        dex_name: Optional filter by DEX name
    
    Returns:
        Dictionary with success rates and efficiency metrics
    """
    pc, index = connect_to_pinecone()
    
    filter_dict = {}
    if dex_name:
        filter_dict["dex"] = {"$eq": dex_name}
    
    results = index.query(
        vector=[0] * 384,  # Dummy vector to fetch all results
        top_k=1000,
        include_metadata=True,
        filter=filter_dict
    )
    
    success_count = 0
    total_count = 0
    efficiency_sum = 0.0
    
    for match in results.get("matches", []):
        metadata = match.get("metadata", {})
        if metadata.get("success", True):
            success_count += 1
        efficiency_sum += metadata.get("efficiency", 1.0)
        total_count += 1
    
    success_rate = success_count / total_count if total_count > 0 else 0.0
    avg_efficiency = efficiency_sum / total_count if total_count > 0 else 0.0
    
    return {
        "success_rate": success_rate,
        "avg_efficiency": avg_efficiency,
        "total_swaps": total_count
    }

def retrieve_similar_swaps(query, token_filter=None, dex_filter=None, top_k=5):
    """
    Finds similar past swaps in Pinecone.
    
    Args:
        query: The search query (e.g., "ETH to USDC")
        token_filter: Filter by specific token, e.g., "ETH" or "USDC"
        dex_filter: Filter by specific DEX, e.g., "Uniswap V3"
        top_k: Number of results to return
    """
    pc, index = connect_to_pinecone()

    # Create filter condition if specified
    filter_dict = {}
    if token_filter:
        filter_dict.update({"$or": [
            {"path": {"$contains": token_filter}}
        ]})
    if dex_filter:
        filter_dict.update({"dex": {"$eq": dex_filter}})
    
    # Encode the query
    query_vector = embedding_model.encode(query).tolist()
    
    # Query Pinecone
    results = index.query(
        vector=query_vector, 
        top_k=top_k, 
        include_metadata=True,
        filter=filter_dict if filter_dict else None
    )
    
    # Process results
    swap_paths = []
    for match in results.get("matches", []):
        metadata = match.get("metadata", {})
        
        # Parse token data
        input_tokens = json.loads(metadata.get("inputTokens", "[]"))
        output_tokens = json.loads(metadata.get("outputTokens", "[]"))
        
        swap_info = {
            "txHash": metadata.get("txHash", ""),
            "timestamp": metadata.get("timestamp", ""),
            "dex": metadata.get("dex", "Unknown DEX"),
            "path": metadata.get("path", ""),
            "description": metadata.get("description", ""),
            "swapRate": metadata.get("swapRate", 0),
            "score": match.get("score", 0),
            "inputTokens": input_tokens,
            "outputTokens": output_tokens
        }
        
        swap_paths.append(swap_info)
    
    return swap_paths

def get_optimal_swap_paths(from_token, to_token, amount=None):
    """
    Analyzes historical swap data to recommend optimal paths between tokens.
    
    Args:
        from_token: The source token symbol (e.g., "ETH")
        to_token: The destination token symbol (e.g., "USDC")
        amount: Optional amount to swap (for rate estimates)
    
    Returns:
        List of recommended swap paths with statistics
    """
    # Query for direct swaps
    direct_query = f"Swap {from_token} to {to_token}"
    direct_swaps = retrieve_similar_swaps(
        direct_query, 
        token_filter=None,  # Don't filter to find all possible paths
        top_k=10
    )
    
    # Group results by path and DEX
    path_stats = {}
    
    for swap in direct_swaps:
        path = swap.get("path", "")
        dex = swap.get("dex", "Unknown")
        
        key = f"{path} on {dex}"
        
        if key not in path_stats:
            path_stats[key] = {
                "path": path,
                "dex": dex,
                "count": 0,
                "rates": [],
                "txHashes": [],
                "bestRate": 0,
                "avgRate": 0
            }
        
        stats = path_stats[key]
        stats["count"] += 1
        
        rate = swap.get("swapRate", 0)
        if rate > 0:
            stats["rates"].append(rate)
            if rate > stats["bestRate"]:
                stats["bestRate"] = rate
        
        stats["txHashes"].append(swap.get("txHash", ""))
    
    # Calculate average rates
    for key, stats in path_stats.items():
        if stats["rates"]:
            stats["avgRate"] = sum(stats["rates"]) / len(stats["rates"])
    
    # Sort by best average rate
    sorted_paths = sorted(
        path_stats.values(), 
        key=lambda x: (x["avgRate"], x["count"]), 
        reverse=True
    )
    
    return sorted_paths