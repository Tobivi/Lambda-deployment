from groq import Groq
import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY)

def generate_swap_advice(query):
    """
    Uses Groq API to generate optimal swap paths.
    
    Args:
        query: The query containing swap details and context.
    
    Returns:
        The LLM-generated swap advice.
    """
    system_prompt = """You are an expert in cryptocurrency swap optimization, specializing in DeFi and DEX routing strategies.
    Your goal is to provide clear, accurate, and efficient swap paths based on:
    1. Historical transaction data (when provided)
    2. Current market conditions 
    3. Gas optimization techniques
    4. DEX-specific advantages and liquidity patterns
    
    For each swap recommendation:
    - First recommend the optimal path(s) in a concise format
    - Explain WHY this path is optimal (considering fees, slippage, gas, etc.)
    - If relevant, suggest alternative paths for different priorities (speed vs. cost)
    - Provide step-by-step instructions on how to execute the swap
    
    When responding to queries with historical data, analyze patterns to identify consistently efficient routes.
    """
    
    try:
        response = groq_client.chat.completions.create(
            model="mixtral-8x7b-32768",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            temperature=0.5,
            max_tokens=2048,
            top_p=0.95,
            stream=True
        )

        swap_response = ""
        for chunk in response:
            chunk_content = chunk.choices[0].delta.content
            if chunk_content:
                swap_response += chunk_content

        return swap_response

    except Exception as e:
        print(f"Error with Groq API: {str(e)}")
        return f"Unable to generate swap advice. Please try again later. Error: {str(e)}"