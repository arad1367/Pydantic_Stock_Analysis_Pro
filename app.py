from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from pydantic_ai import Agent
from pydantic import BaseModel
import yfinance as yf
from functools import wraps
import os
import re
import asyncio
import nest_asyncio

# Enable nested asyncio support
nest_asyncio.apply()

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Available Groq models
GROQ_MODELS = {
    "llama-3.3-70b-specdec": "Llama 3.3 70B SpecDec",
    "llama3-groq-70b-8192-tool-use-preview": "Llama 3 70B"
}

# Pydantic models remain the same as before
class StockPriceResult(BaseModel):
    symbol: str
    price: float
    currency: str = "USD"
    message: str

class StockAdviceResult(BaseModel):
    analysis: str
    recommendation: str
    confidence: int
    risk_level: str

class TechnicalAnalysisResult(BaseModel):
    technical_indicators: dict
    future_outlook: str
    support_levels: list
    resistance_levels: list
    trading_volume: float

def extract_stock_symbol(query):
    """Extract stock symbol from query using various methods"""
    # Try to find symbol in parentheses first (e.g., "symbol: TSLA" or "(TSLA)")
    symbol_match = re.search(r'(?:symbol:?\s*|[\(\[])\s*([A-Z]+)[\)\]]?', query.upper())
    if symbol_match:
        return symbol_match.group(1)
    
    # Look for common stock names and their symbols
    stock_mapping = {
        'TESLA': 'TSLA',
        'APPLE': 'AAPL',
        'MICROSOFT': 'MSFT',
        'AMAZON': 'AMZN',
        'GOOGLE': 'GOOGL',
        'META': 'META',
        'FACEBOOK': 'META',
        'NVIDIA': 'NVDA',
        'Tellurian Inc':'TELL'
    }
    
    for name, symbol in stock_mapping.items():
        if name in query.upper():
            return symbol
            
    # If no match found, try the first word
    return query.upper().split()[0] if query.split() else "UNKNOWN"

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'api_key' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def run_in_event_loop(coro):
    """Helper function to run coroutines in an event loop"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

def get_stock_info(stock_symbol):
    """Get stock information with proper error handling"""
    try:
        stock = yf.Ticker(stock_symbol)
        info = stock.info
        
        current_price = info.get('regularMarketPrice')
        if current_price is None:
            current_price = info.get('currentPrice', 0)
            
        volume = info.get('volume', 0)
        
        # Calculate support and resistance levels
        if current_price:
            support_levels = [
                round(current_price * 0.95, 2),
                round(current_price * 0.90, 2)
            ]
            resistance_levels = [
                round(current_price * 1.05, 2),
                round(current_price * 1.10, 2)
            ]
        else:
            support_levels = []
            resistance_levels = []
            
        return {
            'success': True,
            'price': current_price,
            'volume': volume,
            'support_levels': support_levels,
            'resistance_levels': resistance_levels
        }
    except Exception as e:
        print(f"Error fetching stock data: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        api_key = request.form['api_key'].strip()
        
        if not api_key:
            return render_template('login.html', error="Please enter an API key")
        
        if not api_key.startswith('gsk_'):
            return render_template('login.html', error="Invalid API key format. API key should start with 'gsk_'")
        
        session['api_key'] = api_key
        return redirect(url_for('index'))
    
    return render_template('login.html')

@app.route('/')
@require_api_key
def index():
    return render_template('index.html', models=GROQ_MODELS)

@app.route('/analyze', methods=['POST'])
@require_api_key
def analyze_stock():
    try:
        query = request.form['query']
        model = request.form['model']
        api_key = session['api_key']
        
        # Extract stock symbol
        stock_symbol = extract_stock_symbol(query)
        if stock_symbol == "UNKNOWN":
            return jsonify({
                'success': False,
                'error': "Could not identify stock symbol in the query. Please include the stock symbol (e.g., TSLA for Tesla)"
            })
        
        # Get stock data
        stock_data = get_stock_info(stock_symbol)
        if not stock_data.get('success', False):
            return jsonify({
                'success': False,
                'error': f"Could not fetch data for stock symbol {stock_symbol}"
            })

        # Set up Groq environment
        os.environ['GROQ_API_KEY'] = api_key

        async def analyze_stock_async():
            # Create agents
            price_agent = Agent(
                f"groq:{model}",
                result_type=StockPriceResult,
                system_prompt=f"You are a financial analyst. Analyze {stock_symbol} (price: ${stock_data['price']})."
            )
            
            advisor_agent = Agent(
                f"groq:{model}",
                result_type=StockAdviceResult,
                system_prompt=f"You are an investment advisor. Analyze {stock_symbol} (price: ${stock_data['price']})."
            )
            
            technical_agent = Agent(
                f"groq:{model}",
                result_type=TechnicalAnalysisResult,
                system_prompt=f"You are a technical analyst. Analyze {stock_symbol} (price: ${stock_data['price']})."
            )

            # Get all responses
            price_result = await asyncio.create_task(
                price_agent.run(f"Analyze {stock_symbol}'s current market position and performance")
            )
            advice_result = await asyncio.create_task(
                advisor_agent.run(f"Should investors invest in {stock_symbol}? Provide detailed analysis")
            )
            technical_result = await asyncio.create_task(
                technical_agent.run(f"Provide technical analysis for {stock_symbol}")
            )

            return price_result, advice_result, technical_result

        # Run async analysis in event loop
        price_result, advice_result, technical_result = run_in_event_loop(analyze_stock_async())

        # Build response
        result = {
            'success': True,
            'price_data': {
                'symbol': stock_symbol,
                'price': stock_data['price'],
                'currency': 'USD',
                'message': price_result.data.message
            },
            'advice_data': {
                'analysis': advice_result.data.analysis,
                'recommendation': advice_result.data.recommendation,
                'confidence': advice_result.data.confidence,
                'risk_level': advice_result.data.risk_level
            },
            'technical_data': {
                'technical_indicators': technical_result.data.technical_indicators,
                'future_outlook': technical_result.data.future_outlook,
                'support_levels': stock_data['support_levels'],
                'resistance_levels': stock_data['resistance_levels'],
                'trading_volume': stock_data['volume']
            }
        }

        return jsonify(result)

    except Exception as e:
        print(f"Analysis Error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

if __name__ == '__main__':
    app.run(debug=True)