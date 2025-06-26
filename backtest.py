import json
import pandas as pd

with open('backtest.json', 'r') as f:
    data = json.load(f)

formatted_data = []
for item in data:
    formatted_data.append({
        'current_time': item['current_time'],
        'decision': item['decision'],
        'open': item['market_data']['open'],
        'high': item['market_data']['high'],
        'low': item['market_data']['low'],
        'close': item['market_data']['close'],
        'volume': item['market_data']['volume'],
        'tenkan': item['strategy_indicators']['tenkan'],
        'kijun': item['strategy_indicators']['kijun'],
        'number_of_contracts': item['strategy_indicators']['number_of_contracts'],
    })

df = pd.DataFrame(formatted_data)
df.to_csv('backtest.csv', index=False)