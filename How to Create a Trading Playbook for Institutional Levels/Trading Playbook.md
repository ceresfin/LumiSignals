# Trading Playbook

## Introduction

This playbook provides a structured framework for developing, documenting, and implementing trading strategies. It is designed to be a living document, continuously updated and refined with new strategies and insights. The playbook is intended for both human traders, for discretionary trading and verification, and for algorithmic trading systems, which can parse this document to execute trades automatically.

### Playbook Structure

The playbook is organized into a hierarchical structure:

- **Paradigms**: The highest-level classification of trading approaches. Each paradigm represents a fundamental market perspective or a core trading philosophy.
- **Strategies**: Specific, actionable trading strategies within each paradigm. Each strategy is a complete system with its own set of rules and parameters.
- **Layers**: Reusable components that define specific market conditions or analytical inputs. Layers can be shared across multiple strategies and paradigms, promoting modularity and consistency.

### How to Use This Playbook

- **For Human Traders**: Use this playbook as a reference guide for understanding and executing trading strategies. Each strategy is documented with clear entry and exit criteria, risk management rules, and performance metrics.
- **For Algorithmic Trading**: The playbook is structured in a machine-readable format (Markdown) that can be parsed by trading algorithms. Each strategy's parameters and rules are explicitly defined, allowing for automated execution and backtesting.




## Paradigm: Institutional / Psychological Levels

This paradigm focuses on trading strategies that capitalize on the predictable price action that occurs around key institutional and psychological price levels. These levels are significant because they are widely watched by market participants, including large financial institutions, and often act as strong levels of support and resistance.

### Core Principles

- **Round Numbers**: Large, round numbers (e.g., 1.2000, 100.00) are natural psychological magnets for price.
- **Quarter Levels**: Quarter points (e.g., 1.2250, 1.2500, 1.2750) are key levels for institutional order flow.
- **Order Clustering**: Large volumes of orders tend to cluster around these levels, creating predictable price reactions.
- **Self-Fulfilling Prophecy**: The more a level is respected, the more significant it becomes, as more traders and algorithms are programmed to react to it.




### Strategy: Quarters Theory with Bodyguard Entry System

This strategy is based on the Quarters Theory, which uses quarter levels (red lines) as key institutional levels, protected by "bodyguard" levels (green lines) positioned 75 pips above and below each quarter level. The bodyguards act as early warning systems - when price pierces through a bodyguard with strong candlestick sentiment, it signals a high-probability move in the direction of the breach.

#### Strategy Overview

The Quarters Theory with Bodyguard Entry System recognizes that institutional traders place significant orders at quarter levels (1.2000, 1.2250, 1.2500, etc.). The bodyguards, positioned 75 pips away from these levels, act as "trip wires" that detect when these institutional levels are being challenged. When price breaks through a bodyguard with conviction (strong candlestick sentiment), it indicates that the institutional orders at the quarter level may be overwhelmed, leading to continuation toward the next target.

#### Level Structure

**Quarter Levels (Red Lines - Institutional Levels)**:
- Major institutional price levels where large orders cluster
- Examples: 1.2000, 1.2250, 1.2500, 1.2750, 1.3000
- These are NOT entry levels, but rather the core institutional zones
- **Static Pattern**: Always end in .000, .250, .500, .750
- **Complete Reference**: See [quarter_levels_reference.md](quarter_levels_reference.md) for full list from 0 to 3

**Bodyguard Levels (Green Lines - Entry Triggers)**:
- Positioned exactly 75 pips above and below each quarter level
- Examples for 1.2250 quarter level: 1.2175 (below) and 1.2325 (above)
- These ARE the actual entry trigger levels
- Act as early warning system for quarter level challenges

#### Five Entry-Target Setup Types

The strategy uses two different entry mechanisms: **Bodyguard Entries** (Setups #1, #2) and **Quarter Level Entries** (Setups #4, #5):

**Setup #1: Bodyguard to Bodyguard (Butter)**
- **Entry Type**: Bodyguard breach
- **Target**: Next bodyguard level with NO quarter or dime level in between
- **Take Profit**: 100 pips 
- **Stop Loss**: 75 pips (back to the quarter level being protected)
- **Risk/Reward Ratio**: 1.33:1
- **Use Case**: Highest probability trades - "slicing through butter" with no institutional resistance
- **Logic**: Trade between quarter levels where there are no major institutional orders
- **Non-JPY Pattern**: X.X250 ↔ X.X500 (e.g., 1.2325 ↔ 1.2425, 1.2575 ↔ 1.2675)
- **JPY Pattern**: X25.00 ↔ X27.50 (e.g., 125.75 ↔ 126.75)

**Four Butter Zones Within Each Dime (Example: 1.2500-1.2600 Range):**
1. **Zone A**: 1.2425 ↔ 1.2475 (between quarters 1.2500 and 1.2550)
2. **Zone B**: 1.2475 ↔ 1.2525 (between quarters 1.2500 and 1.2550) 
3. **Zone C**: 1.2525 ↔ 1.2575 (between quarters 1.2550 and 1.2600)
4. **Zone D**: 1.2575 ↔ 1.2625 (between quarters 1.2550 and 1.2600)

**Setup #2: Bodyguard to Next Bodyguard (Crossing Quarter)**
- **Entry Type**: Bodyguard breach
- **Target**: Next bodyguard but CROSSING a quarter level in between
- **Take Profit**: 150 pips
- **Stop Loss**: 50 pips
- **Risk/Reward Ratio**: 3:1
- **Use Case**: Medium-risk trades with institutional resistance to overcome
- **Challenge**: Must break through quarter level institutional orders

**Setup #3: Bodyguard to Quarter Level (Traditional Play)**
- **Entry Type**: Bodyguard breach
- **Target**: Quarter level in the direction of the trade
- **Take Profit**: 175 pips
- **Stop Loss**: 75 pips (back to original quarter level)
- **Risk/Reward Ratio**: 2.33:1
- **Use Case**: Traditional quarters theory play - bodyguard entry targeting quarter level
- **Logic**: Enter early at bodyguard, target the institutional quarter level in trade direction

**Setup #4: Quarter Level to Opposing Bodyguard**
- **Entry Type**: Quarter level breakout
- **Target**: Opposing bodyguard (crossing one bodyguard in between)
- **Take Profit**: 175 pips
- **Stop Loss**: 75 pips
- **Risk/Reward Ratio**: 2.33:1
- **Use Case**: Breakout trades from major institutional levels
- **Entry Trigger**: Strong breakout from quarter level with conviction

**Setup #5: Quarter Level to Quarter Level**
- **Entry Type**: Quarter level breakout
- **Target**: Next quarter level (longest distance)
- **Take Profit**: 250 pips
- **Stop Loss**: 75 pips
- **Risk/Reward Ratio**: 3.33:1
- **Use Case**: High-conviction, longer-term institutional breakout trades
- **Maximum Distance**: Covers full quarter-to-quarter range

#### Entry Mechanisms

**Bodyguard Entries (Setups #1, #2, #3)**:
- **Trigger**: Price pierces through bodyguard level with strong sentiment
- **Logic**: Early warning system detecting quarter level challenges
- **Advantage**: Higher probability entries - get in before institutional level is tested
- **Sentiment Required**: Bullish/Very Bullish for upward, Bearish/Very Bearish for downward
- **Entry Timing**: Earlier entry provides better risk/reward positioning

**Quarter Level Entries (Setups #4, #5)**:
- **Trigger**: Price breaks through actual quarter level with conviction
- **Logic**: Direct breakout from major institutional price zones
- **Advantage**: Higher conviction signals from institutional level breaks
- **Sentiment Required**: Very strong sentiment due to institutional resistance
- **Entry Timing**: Confirmation entry after institutional level is breached

**Entry Selection Strategy**:
- **Bodyguard entries offer higher probability** due to earlier positioning
- **Quarter level entries provide confirmation** but may have reduced risk/reward
- **Both entry types are valid** for institutional level trading
- **Choose based on risk tolerance**: Bodyguards for probability, quarters for confirmation

#### Entry Trigger Requirements

**Bodyguard Breach Criteria (Setups #1, #2, #3)**:
1. Price must pierce through a bodyguard level (not just touch)
2. 4-hour candlestick must show Bullish (60-80%) or Very Bullish (80-100%) sentiment for upward breaches
3. 4-hour candlestick must show Bearish (20-40%) or Very Bearish (0-20%) sentiment for downward breaches
4. Candlestick must close beyond the bodyguard level (confirmation of breach)
5. Enter in the direction of the bodyguard breach

**Quarter Level Breakout Criteria (Setups #4, #5)**:
1. Price must break through the actual quarter level with strong momentum
2. 4-hour candlestick must show Very Bullish (80-100%) sentiment for upward breakouts
3. 4-hour candlestick must show Very Bearish (0-20%) sentiment for downward breakouts
4. Higher volume/momentum confirmation preferred due to institutional resistance
5. Candlestick must close significantly beyond the quarter level

#### Key Parameters

- **Timeframe**: 4-hour candlesticks (primary signal timeframe)
- **Currency Pairs**: All major and minor currency pairs
- **Bodyguard Distance**: Fixed 75 pips from quarter levels
  - Non-JPY pairs: 0.0075 (e.g., 1.2250 ± 0.0075 = 1.2175/1.2325)
  - JPY pairs: 0.75 (e.g., 122.50 ± 0.75 = 121.75/123.25)
- **Quarter Spacing**: 250 pips between quarter levels
- **Required Sentiment**: 
  - Bodyguard entries: Minimum Bullish/Bearish sentiment
  - Quarter level entries: Very Bullish/Very Bearish sentiment required
- **Quarter Level References**:
  - **Non-JPY pairs**: See [quarter_levels_reference.md](quarter_levels_reference.md) for levels 0-3
  - **JPY pairs**: See [jpy_quarter_levels_reference.md](jpy_quarter_levels_reference.md) for levels 50-300

#### Layers

The following layers are used to create the trigger for entry:

- **Layer 1: Quarter Levels**: The core institutional levels (red lines) where large orders cluster
- **Layer 2: Bodyguard Levels**: Entry trigger levels positioned 75 pips above/below quarter levels (green lines)
- **Layer 3: Setup Type Identification**: Determines which of the 5 target combinations applies
- **Layer 4: Candlestick Sentiment**: Analysis of where price closes within the candlestick range
- **Layer 5: Entry Type Classification**: Distinguishes between bodyguard and quarter level entries
- **Layer 6: Breakout/Breach Confirmation**: Verifies proper entry signal based on entry type

#### Strategy Examples

**Visual Level Structure**

![Quarters Theory Level Structure](https://private-us-east-1.manuscdn.com/sessionFile/ozYgvmsQlsnpttZebXay17/sandbox/SQSYpV5YG6J4B6ydh2fr13-images_1757607113430_na1fn_L2hvbWUvdWJ1bnR1L3F1YXJ0ZXJzX2xldmVsX3N0cnVjdHVyZQ.png?Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9wcml2YXRlLXVzLWVhc3QtMS5tYW51c2Nkbi5jb20vc2Vzc2lvbkZpbGUvb3pZZ3Ztc1Fsc25wdHRaZWJYYXkxNy9zYW5kYm94L1NRU1lwVjVZRzZKNEI2eWRoMmZyMTMtaW1hZ2VzXzE3NTc2MDcxMTM0MzBfbmExZm5fTDJodmJXVXZkV0oxYm5SMUwzRjFZWEowWlhKelgyeGxkbVZzWDNOMGNuVmpkSFZ5WlEucG5nIiwiQ29uZGl0aW9uIjp7IkRhdGVMZXNzVGhhbiI6eyJBV1M6RXBvY2hUaW1lIjoxNzk4NzYxNjAwfX19XX0_&Key-Pair-Id=K2HSFNDJXOU9YS&Signature=YUNbTgfox23wsPGHsXWmS~rmsOCuQ8dmN8eMdLAA8QGr83KNH6-efO~QyL9yw1HMQHHoI6TplWYvHjkv6C1g3NkflcVGS9Km73Gs7n6g0j65gA1vk~JTKx7u2l-~MKH3JzwCWbzKZR1T-j~S3utcwMv82PgLFRq4FUjbIg9IaYsFJo05YzK6gJO-1guE5MePy6~A1LQ2utpVP2PVEi0NCo1Ue36OuaY2qFicg7S1QyDsS23HL4NzdMIMeUU-0GFR6106SKA0uYGv5ZoTfnKn28SqTy4grgC-sJsYpKLUz3DVH4OPnG8Web6W-YbUvU8TcRWegvMUvCmHVoOPnxyaJQ__)

The diagram above shows the complete level structure with red quarter levels (institutional zones) and green bodyguard levels (entry triggers) positioned 75 pips apart.

**Example 1: Setup #1 (Butter) - All Four Zones Within Dime Range**

![Butter Zones Complete](https://private-us-east-1.manuscdn.com/sessionFile/ozYgvmsQlsnpttZebXay17/sandbox/SQSYpV5YG6J4B6ydh2fr13-images_1757607113432_na1fn_L2hvbWUvdWJ1bnR1L2J1dHRlcl96b25lc19jb21wbGV0ZQ.png?Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9wcml2YXRlLXVzLWVhc3QtMS5tYW51c2Nkbi5jb20vc2Vzc2lvbkZpbGUvb3pZZ3Ztc1Fsc25wdHRaZWJYYXkxNy9zYW5kYm94L1NRU1lwVjVZRzZKNEI2eWRoMmZyMTMtaW1hZ2VzXzE3NTc2MDcxMTM0MzJfbmExZm5fTDJodmJXVXZkV0oxYm5SMUwySjFkSFJsY2w5NmIyNWxjMTlqYjIxd2JHVjBaUS5wbmciLCJDb25kaXRpb24iOnsiRGF0ZUxlc3NUaGFuIjp7IkFXUzpFcG9jaFRpbWUiOjE3OTg3NjE2MDB9fX1dfQ__&Key-Pair-Id=K2HSFNDJXOU9YS&Signature=YMzEQPHXD06ZRD0otkQdPwuuU-T7Xvs~Sr02BDJztG5E-vAjofzQYO3XleFEcGoYSg~9Oh9FGqxl8Zm1nJ~YcesD22sArGakHy2lrii78eHkfj~2Zc-fIeGj1u5vxeFPcypQSJFezMBDkuqh6NWKu1SZ7JGJgXgv5LSSJAzXu3rU0gb6Sc2xytWqY0J1-M2ggSNbV41TMERh4VKrC9JfjJtkZslyVxLt4~hUVPVzEJMzCpfLvPHOVkr~1DKtelJ0563G9dgx0gCWtA5eHoiEthXG-N~4vD4qgwLox~LidyGjVtZQBM-LveNmTGUrEzvI~z4k68Lq5XhpH8vw~GSFDg__)

- **Scenario**: Complete view of all 4 butter zones within 1.2500-1.2600 dime range
- **Setup**: Bodyguard to bodyguard with NO quarter or dime levels crossed
- **Four Possible Butter Trades**:
  - **Zone A**: 1.2425 ↔ 1.2475 (50 pips, between quarters 1.2500 and 1.2550)
  - **Zone B**: 1.2475 ↔ 1.2525 (50 pips, between quarters 1.2500 and 1.2550)
  - **Zone C**: 1.2525 ↔ 1.2575 (50 pips, between quarters 1.2550 and 1.2600)
  - **Zone D**: 1.2575 ↔ 1.2625 (50 pips, between quarters 1.2550 and 1.2600)
- **Execution for any zone**: 
  - Enter when price pierces bodyguard with Bullish/Bearish sentiment
  - Stop-loss at nearest quarter level (75 pips risk)
  - Take-profit at target bodyguard (50 pips reward)
  - Risk/Reward: 0.67:1 (but highest probability due to no institutional resistance)
- **Why Butter**: Clear path between bodyguards without crossing any institutional levels

**Example 2: Setup #3 (Traditional Play) - Bodyguard to Quarter**

![Setup 3 Traditional Example](https://private-us-east-1.manuscdn.com/sessionFile/ozYgvmsQlsnpttZebXay17/sandbox/SQSYpV5YG6J4B6ydh2fr13-images_1757607113433_na1fn_L2hvbWUvdWJ1bnR1L3NldHVwM190cmFkaXRpb25hbA.png?Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9wcml2YXRlLXVzLWVhc3QtMS5tYW51c2Nkbi5jb20vc2Vzc2lvbkZpbGUvb3pZZ3Ztc1Fsc25wdHRaZWJYYXkxNy9zYW5kYm94L1NRU1lwVjVZRzZKNEI2eWRoMmZyMTMtaW1hZ2VzXzE3NTc2MDcxMTM0MzNfbmExZm5fTDJodmJXVXZkV0oxYm5SMUwzTmxkSFZ3TTE5MGNtRmthWFJwYjI1aGJBLnBuZyIsIkNvbmRpdGlvbiI6eyJEYXRlTGVzc1RoYW4iOnsiQVdTOkVwb2NoVGltZSI6MTc5ODc2MTYwMH19fV19&Key-Pair-Id=K2HSFNDJXOU9YS&Signature=Yz1Cf-rYcyNi2gBSA3I4hyxSoQudnLBgO7lPS3EE08Xhtk-8fLe8aPyTj23NSx5oHRYayGod21p3WrwGrQESJY1oFk5DTOKGGl4jPC1NPCy4DOTmwK8WV226gOw00WPsNi4Inn-5gRYKM7oBeHAcYMIzBOiNsTwmEL6LZ-W~VunUDZXAq-dr4tN8St1J2tUY3wOGMoZWAIwZ7OzNCO9~m2s~405XQX2FCB7HJXRGk1ADB4ORux2bXJh37jILuqusyG31n0L~rgfJUb2sWQ80ae1qbHUvtpknEMeQv0dcvYS3gcqxIsN2gS0dAKGM~WUQxxuKxRnIGgC6o8McC4JFzg__)

- **Scenario**: GBP/USD at 1.2330, breaking above bodyguard level 1.2325 (above quarter 1.2250)
- **Setup**: Bodyguard entry targeting quarter level in trade direction
- **Execution**:
  - Enter long when price pierces above 1.2325 with Bullish sentiment
  - Stop-loss at 1.2250 (75 pips risk - back to protected quarter)
  - Take-profit at 1.2500 (175 pips reward - next quarter level in direction)
  - Risk/Reward: 2.33:1
  - **Traditional Logic**: Early bodyguard entry targeting institutional quarter level

**Candlestick Sentiment Analysis**

![Candlestick Sentiment Analysis](https://private-us-east-1.manuscdn.com/sessionFile/ozYgvmsQlsnpttZebXay17/sandbox/SQSYpV5YG6J4B6ydh2fr13-images_1757607113434_na1fn_L2hvbWUvdWJ1bnR1L2NhbmRsZXN0aWNrX3NlbnRpbWVudA.png?Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9wcml2YXRlLXVzLWVhc3QtMS5tYW51c2Nkbi5jb20vc2Vzc2lvbkZpbGUvb3pZZ3Ztc1Fsc25wdHRaZWJYYXkxNy9zYW5kYm94L1NRU1lwVjVZRzZKNEI2eWRoMmZyMTMtaW1hZ2VzXzE3NTc2MDcxMTM0MzRfbmExZm5fTDJodmJXVXZkV0oxYm5SMUwyTmhibVJzWlhOMGFXTnJYM05sYm5ScGJXVnVkQS5wbmciLCJDb25kaXRpb24iOnsiRGF0ZUxlc3NUaGFuIjp7IkFXUzpFcG9jaFRpbWUiOjE3OTg3NjE2MDB9fX1dfQ__&Key-Pair-Id=K2HSFNDJXOU9YS&Signature=LJu8xDkdNs12dFBA4v4dRahfJmP-GlZjsVm59ny2STTJLv9LGK24vuWWz56EMAhGprH-rwuAufujS11u-w5KGQH~bcALgaWi6VNKQhstCMPbZjkaF1BitKqVyNZmrtUA8CVGEVtyLAyhAnKeqioUWceoPul2OLWiyBVLYW-D1JJsAFm~FB6T5qCuQZ4YB-BWlr9wvFvh1rJdVO7UQPF2hvIK5YAZcqPnzLrhHdUlI1cAAOeupbiDnGJoerybyb9W3Rm6WhkG5UqWLdyjk2~o44rzRTbM6K4UwCEBLgqAfUZYkleCaRGcWs4SeDiy4AayJqzNPFEmCRBIvQ81DUbf0Q__)

The diagram above shows the five sentiment categories used to validate entry signals. Bodyguard entries require minimum Bullish/Bearish sentiment, while quarter level entries require Very Bullish/Very Bearish sentiment.

**Example 3: Setup #5 - Quarter Level Entry**
- **Scenario**: GBP/USD at 1.2255, breaking above quarter level 1.2250
- **Setup**: Quarter level to next quarter level
- **Execution**:
  - Enter long when price breaks above 1.2250 with Very Bullish sentiment
  - Stop-loss at 1.2175 (75 pips risk)
  - Take-profit at 1.2500 (250 pips reward - next quarter level)
  - Risk/Reward: 3.33:1
  - **High Conviction**: Direct institutional level breakout signal

#### Implementation Notes

- **Entry Type Selection**: Choose between bodyguard (early) vs quarter level (confirmation) entries
- **Butter Advantage**: Setup #1 offers highest probability due to minimal resistance
- **Institutional Resistance**: Quarter level entries require stronger conviction due to order clustering
- **Risk Management**: Adjust position size based on entry type and expected resistance
- **Multiple Signals**: Both entry types can be active simultaneously on different levels




## Layers

Layers are the building blocks of our trading strategies. They are reusable components that define specific market conditions or analytical inputs. Each layer is a self-contained module that can be combined with other layers to create complex trading signals.

### Layer Documentation

Detailed documentation for each layer, including its purpose, calculation method, and parameters, can be found in the [layers.md](layers.md) file.

#### Layers

The following layers are used to create the trigger for entry:

- **Layer 1: Quarter Levels**: The core institutional levels (red lines) where large orders cluster
- **Layer 2: Bodyguard Levels**: Entry trigger levels positioned 75 pips above/below quarter levels (green lines)
- **Layer 3: Setup Type Identification**: Determines which of the 5 target combinations applies
- **Layer 4: Candlestick Sentiment**: Analysis of where price closes within the candlestick range
- **Layer 5: Bodyguard Breach Confirmation**: Verifies price has pierced through bodyguard with conviction

#### Strategy Examples

**Example 1: Setup #1 (Bodyguard to Next Bodyguard)**
- **Scenario**: GBP/USD at 1.2170, approaching bodyguard level 1.2175 (below quarter 1.2250)
- **Setup**: Price breaks below 1.2175 bodyguard with Very Bearish sentiment
- **Execution**: 
  - Enter short when price pierces below 1.2175 with Very Bearish sentiment
  - Stop-loss at 1.2200 (25 pips risk - back toward quarter level)
  - Take-profit at 1.2075 (100 pips reward - next bodyguard below quarter 1.2000)
  - Risk/Reward: 4:1

**Example 2: Setup #5 (Bodyguard to Second Quarter Level)**
- **Scenario**: GBP/USD at 1.2330, breaking above bodyguard level 1.2325 (above quarter 1.2250)
- **Setup**: Price breaks above 1.2325 bodyguard with Very Bullish sentiment
- **Execution**:
  - Enter long when price pierces above 1.2325 with Very Bullish sentiment
  - Stop-loss at 1.2250 (75 pips risk - back to quarter level)
  - Take-profit at 1.2750 (425 pips reward - second quarter level up)
  - Risk/Reward: 5.67:1 (Note: This example shows the power of Setup #5)

#### Implementation Notes

- **Bodyguard Function**: Bodyguards act as "trip wires" - they detect when quarter levels are being challenged
- **Entry Timing**: Only enter when bodyguard is breached with proper candlestick sentiment
- **Stop Placement**: Stops are typically placed back toward the quarter level that was being protected
- **Target Selection**: Choose target based on market context and risk tolerance
- **Multiple Opportunities**: Multiple bodyguards can be active simultaneously across different quarter levels

## Playbook Expansion and Maintenance

This playbook is designed to be a living document that grows and evolves with your trading experience and market insights.

### Adding New Strategies

When adding new strategies to existing paradigms or creating new paradigms:

1. **Document the Strategy**: Follow the same structure used for the Quarters Theory strategy
2. **Identify Reusable Layers**: Determine which existing layers can be reused and which new layers need to be created
3. **Update Layer Documentation**: Add any new layers to the `layers.md` file
4. **Implement Code References**: Add corresponding functions to `code_references.py`
5. **Test and Validate**: Backtest the strategy and document performance metrics

### Reusing Layers Across Strategies

The layer system is designed for maximum reusability:

- **Candlestick Sentiment**: Can be used in any strategy requiring strong directional moves
- **Breakout Confirmation**: Applicable to any breakout-based strategy
- **Quarter Levels**: Can be adapted for different institutional level strategies
- **Bodyguard Levels**: The concept can be applied to any support/resistance level

### Version Control and Updates

- **Strategy Refinements**: Update parameters based on backtesting and live trading results
- **Layer Improvements**: Enhance layer calculations as market understanding improves
- **New Market Conditions**: Adapt strategies for changing market environments
- **Performance Tracking**: Document win rates, average R:R ratios, and other key metrics

### Integration with Trading Systems

The structured format of this playbook makes it suitable for:

- **Manual Trading**: Clear rules for discretionary traders
- **Algorithmic Implementation**: Machine-readable format for automated systems
- **Backtesting**: Systematic approach to historical testing
- **Risk Management**: Consistent risk/reward frameworks across all strategies


### Strategy: Static Round Numbers

This strategy is based on predefined institutional round number levels that are consistently watched by large market participants. Unlike the dynamic Quarters Theory, these are static levels that remain constant regardless of current price action, providing reliable support and resistance zones.

#### Strategy Overview

The Static Round Numbers strategy uses a hierarchical system of round number levels to identify high-probability reversal and continuation zones. The strategy recognizes that institutional traders and algorithms are programmed to react at these specific price levels, creating predictable order flow patterns.

#### Level Hierarchy

**For Non-JPY Pairs (4-decimal pricing):**

- **Dimes (Major Levels)**: X.9000, X.8000, X.7000, X.6000, X.5000, X.4000, X.3000, X.2000, X.1000, X.0000
- **Big Quarter Levels**: X.X750, X.X500, X.X250, X.X000  
- **Pennies (Intermediate)**: X.XX50, X.XX00
- **Small Quarter Levels**: X.XXX75, X.XXX50, X.XXX25, X.XXX00

**For JPY Pairs (2-decimal pricing):**

- **Dimes (Major Levels)**: XX0.00, XX5.00, XX0.00, XX5.00, XX0.00, XX5.00, XX0.00, XX5.00, XX0.00, XX5.00
- **Big Quarter Levels**: XX7.50, XX5.00, XX2.50, XX0.00
- **Pennies (Intermediate)**: XX.50, XX.00  
- **Small Quarter Levels**: XX.75, XX.50, XX.25, XX.00

#### Key Parameters

- **Timeframe**: Multiple timeframes (H1, H4, D1 for different level types)
- **Currency Pairs**: All major and minor currency pairs
- **Level Priority**: Dimes > Big Quarters > Pennies > Small Quarters
- **Required Confirmation**: Candlestick sentiment and price action confluence

#### Trigger for Entry

The trigger for entry depends on the level type and market context:

**Reversal Signals at Major Levels (Dimes/Big Quarters)**:
1. Price approaches a major round number level
2. Shows rejection via candlestick sentiment (opposite to approach direction)
3. Confluence with other technical factors (trend lines, previous support/resistance)
4. Enter in direction of rejection

**Breakout Signals at Any Level**:
1. Price breaks through a round number level with strong momentum
2. Candlestick sentiment confirms breakout direction (Bullish/Very Bullish for upward breaks)
3. Volume/momentum confirmation
4. Enter in direction of breakout

#### Risk Management

**For Reversal Trades**:
- **Stop-Loss**: Beyond the next significant round number level in the breakout direction
- **Take-Profit**: Next major round number level in the reversal direction
- **Risk/Reward**: Varies based on level spacing, typically 1:2 to 1:4

**For Breakout Trades**:
- **Stop-Loss**: Back below/above the broken round number level
- **Take-Profit**: Next major round number level in breakout direction  
- **Risk/Reward**: Varies based on level spacing, typically 1:2 to 1:3

#### Layers

The following layers are used to create trading signals:

- **Layer 1: Static Round Number Levels**: Predefined institutional levels based on the Forex Road Map
- **Layer 2: Level Hierarchy Classification**: Categorizes levels by importance (Dimes, Big Quarters, etc.)
- **Layer 3: Candlestick Sentiment**: Confirms direction and strength of price movement
- **Layer 4: Price Action Confluence**: Multiple technical factors aligning at round number levels
- **Layer 5: Multi-Timeframe Momentum**: Analyzes momentum across multiple timeframes (particularly crucial for penny level trading)
- **Layer 6: Market Context**: Overall trend and momentum considerations

#### Penny Level Trading Enhancement

For penny level trading (X.XX00, X.XX50), the Multi-Timeframe Momentum layer becomes particularly important due to the smaller price movements involved. When trading penny levels:

**Momentum Requirements for Penny Levels**:
- **Entry Confirmation**: At least 3 out of 5 timeframes must show aligned momentum
- **Timeframe Focus**: 48hr, 24hr, 4hr, 60min, 15min for hourly candlestick analysis
- **Momentum Threshold**: Minimum 0.05% change on shorter timeframes (15min, 60min) to filter noise
- **Divergence Signals**: When shorter timeframes (15min, 60min) show opposite momentum to longer ones, consider reversal trades at penny levels

**Example Penny Level Setup**:
- EUR/USD at 1.1650 approaching penny level 1.1700
- Multi-timeframe momentum shows: 48hr (-0.55%), 24hr (-0.11%), 4hr (-0.10%), 60min (0.00%), 15min (0.00%)
- Analysis: Longer-term bearish momentum weakening, shorter-term momentum neutral
- Signal: Potential reversal setup at 1.1700 penny level if bullish candlestick sentiment appears

#### Strategy Example

**Scenario**: GBP/USD approaching 1.3000 (Major Dime Level)

**Reversal Setup**:
- Price rallies to 1.3000 from below
- 4-hour candlestick shows Very Bearish sentiment (rejection)
- Previous resistance at 1.3000 confirms level significance
- Enter short at 1.2995
- Stop-loss at 1.3050 (55 pips risk)
- Take-profit at 1.2750 (245 pips reward) = 4.45:1 R:R

**Breakout Setup**:
- Price breaks above 1.3000 with strong momentum
- 4-hour candlestick shows Very Bullish sentiment
- High volume confirms institutional participation
- Enter long at 1.3005
- Stop-loss at 1.2980 (25 pips risk)
- Take-profit at 1.3250 (245 pips reward) = 9.8:1 R:R

#### Implementation Notes

- **Level Significance**: Higher hierarchy levels (Dimes) have stronger reactions than lower levels
- **Market Context**: Consider overall trend when choosing reversal vs. breakout bias
- **Time of Day**: London and New York sessions typically show stronger reactions at these levels
- **News Sensitivity**: Major round numbers often act as psychological barriers during news events
- **Multiple Timeframe Analysis**: Confirm signals across different timeframes for higher probability trades

