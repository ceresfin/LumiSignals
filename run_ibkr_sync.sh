#!/bin/bash
cd /Users/sonia/Documents/LumiTrade/LumiSignals
export PYTHONPATH=/Users/sonia/Documents/LumiTrade/LumiSignals
export LUMISIGNALS_URL=https://bot.lumitrade.ai
/Library/Developer/CommandLineTools/usr/bin/python3 -m lumisignals.ibkr_sync
