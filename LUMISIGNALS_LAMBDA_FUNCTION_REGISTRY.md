# LumiSignals Lambda Function Registry
*Comprehensive documentation of all Lambda functions in the LumiSignals trading system*

**Version**: 1.0  
**Last Updated**: September 12, 2025  
**Total Functions**: 30+ Lambda functions  
**System Status**: Trade logic investigation required - no automated trades for 3 weeks

---

## 🎯 **Function Categories**

### **🚀 CRITICAL: Automated Trading Strategies** 
*These functions should be generating trades but haven't for 3 weeks*

| Function Name | Schedule | Strategy Type | Last Modified | Status |
|---------------|----------|---------------|---------------|---------|
| `lumisignals-penny_curve_pc_h1_all_dual_limit_20sl` | `rate(1 hour)` | Penny Level H1 | 2025-07-30 | ⚠️ INVESTIGATE |
| `lumisignals-penny_curve_pc_h1_all_dual_limit_20sl_v2` | `rate(1 hour)` | Penny Level H1 v2 | 2025-07-30 | ⚠️ INVESTIGATE |
| `lumisignals-penny_curve_pc_m15_market_dual_20sl` | `rate(15 minutes)` | Penny Level M15 | 2025-07-30 | ⚠️ INVESTIGATE |
| `lumisignals-penny_curve_ren_pc_h1_all_001` | `rate(1 hour)` | Renaissance Penny H1 | 2025-07-30 | ⚠️ INVESTIGATE |
| `lumisignals-penny_curve_ren_pc_h1_all_dual_limit` | `rate(1 hour)` | Renaissance Penny Dual | 2025-07-30 | ⚠️ INVESTIGATE |
| `lumisignals-penny_curve_ren_pc_m5_all_001` | `rate(5 minutes)` | Renaissance Penny M5 | 2025-07-30 | ⚠️ INVESTIGATE |

### **🔷 Dime Level Trading Strategies**

| Function Name | Schedule | Strategy Type | Last Modified | Status |
|---------------|----------|---------------|---------------|---------|
| `lumisignals-dime_curve_dc_h1_all_dual_limit_100sl` | `rate(1 hour)` | Dime Level H1 | 2025-08-07 | ✅ ACTIVE |
| `lumisignals-dime_curve_ren_dc_h4_all_001` | `rate(4 hours)` | Renaissance Dime H4 | 2025-07-30 | ✅ ACTIVE |
| `lumisignals-str1_Dime_Curve_Strategies` | `rate(1 hour)` | Str1 Dime Curve | 2025-07-30 | ✅ ACTIVE |
| `lumisignals-Dime_Curve_Strategies_1` | `rate(1 hour)` | Dime Curve Alt | 2025-07-30 | ✅ ACTIVE |
| `lumisignals-str1_Dime_Curve_Butter_Strategy` | `rate(1 hour)` | Str1 Dime Butter | 2025-07-30 | ✅ ACTIVE |

### **🟡 Quarter Level Trading Strategies**

| Function Name | Schedule | Strategy Type | Last Modified | Status |
|---------------|----------|---------------|---------------|---------|
| `lumisignals-Quarter_Curve_Butter_1` | `rate(30 minutes)` | Quarter Curve Butter | 2025-07-30 | ✅ ACTIVE |
| `lumisignals-quarter_curve_qc_h1_all_dual_limit_75sl` | `rate(1 hour)` | Quarter Level H1 | 2025-07-30 | ✅ ACTIVE |
| `lumisignals-quarter_curve_ren_qc_h2_all_001` | `rate(2 hours)` | Renaissance Quarter H2 | 2025-07-30 | ✅ ACTIVE |
| `lumisignals-str1_Quarter_Curve_Butter_Strategy` | `rate(1 hour)` | Str1 Quarter Butter | 2025-07-30 | ✅ ACTIVE |

### **🔥 High Frequency & Zone Strategies**

| Function Name | Schedule | Strategy Type | Last Modified | Status |
|---------------|----------|---------------|---------------|---------|
| `lumisignals-str1_high_frequency_zone_strategy` | `rate(5 minutes)` | High Frequency Zone | 2025-07-30 | ✅ ACTIVE |
| `lumisignals-str1_Penny_Curve_Strategy` | `rate(1 hour)` | Str1 Penny Curve | 2025-07-30 | ✅ ACTIVE |

---

## 📊 **Data Infrastructure Functions**

### **Real-Time Data Collection**
| Function Name | Purpose | Schedule | Status |
|---------------|---------|----------|---------|
| `lumisignals-central-data-collector` | Phase 1 Data Collection | Manual | 🔄 LEGACY |
| `lumisignals-central-data-collector-phase2` | Phase 2 Data Collection | `rate(2 minutes)` (DISABLED) | ❌ DISABLED |
| `lumisignals-central-data-collector-phase3` | Phase 3 Hot/Warm/Cold Storage | Manual | 🔄 STANDBY |

*Note: Data collection now handled by Fargate Data Orchestrator (TD 207)*

### **API & Dashboard Services**
| Function Name | Purpose | Runtime | Last Updated |
|---------------|---------|---------|--------------|
| `lumisignals-direct-candlestick-api` | Direct Redis candlestick serving | Python 3.9 | 2025-09-12 ✅ |
| `lumisignals-dashboard-api` | Real-time portfolio monitoring | Python 3.11 | 2025-09-12 ✅ |
| `lumisignals-dashboard-data-reader` | Dashboard data reader | Python 3.9 | 2025-07-30 |
| `lumisignals-web-data-viewer` | Web data viewer | Python 3.12 | 2025-07-30 |

---

## 🔧 **System Maintenance Functions**

### **Data Synchronization**
| Function Name | Purpose | Schedule | Status |
|---------------|---------|----------|---------|
| `lumisignals-enhanced-rds-sync` | GitHub OANDA Transactions sync | Manual | ✅ ACTIVE |
| `lumisignals-airtable-daily-sync` | Airtable verification sync | `rate(10 minutes)` | ✅ ACTIVE |
| `lumisignals-historical-backfill-processor` | Historical data backfills | Manual | 🔄 STANDBY |

### **Backup & Recovery**
| Function Name | Purpose | Schedule | Status |
|---------------|---------|----------|---------|
| `lumisignals-backup-automation` | Automated backup system | Manual | ✅ ACTIVE |
| `lumisignals-database-backup` | Database backup | `cron(0 2 * * ? *)` (Daily) | ✅ ACTIVE |

### **Monitoring & Utilities**
| Function Name | Purpose | Schedule | Status |
|---------------|---------|----------|---------|
| `lumisignals-custom-metrics` | Trading metrics publishing | `rate(5 minutes)` | ✅ ACTIVE |
| `lumisignals-vpn-auto-shutdown` | VPN connection monitoring | `rate(2 hours)` | ✅ ACTIVE |

---

## 🚨 **URGENT INVESTIGATION REQUIRED**

### **Penny Level Trade Logic Issue**
**Problem**: No automated trades generated for 3 weeks despite multiple penny level strategies running

**Affected Functions** (6 penny level strategies):
1. `lumisignals-penny_curve_pc_h1_all_dual_limit_20sl` (Hourly)
2. `lumisignals-penny_curve_pc_h1_all_dual_limit_20sl_v2` (Hourly) 
3. `lumisignals-penny_curve_pc_m15_market_dual_20sl` (15 minutes)
4. `lumisignals-penny_curve_ren_pc_h1_all_001` (Hourly)
5. `lumisignals-penny_curve_ren_pc_h1_all_dual_limit` (Hourly)
6. `lumisignals-penny_curve_ren_pc_m5_all_001` (5 minutes)

**Investigation Areas**:
- [ ] CloudWatch logs for execution patterns
- [ ] Market condition logic - are triggers being met?
- [ ] OANDA API connectivity and permissions
- [ ] Configuration parameters (stop loss, position sizing, etc.)
- [ ] Error handling and notification systems

---

## 🧪 **Function Investigation Commands**

### **Check Lambda Function Status**
```bash
# Get specific function details
aws lambda get-function --function-name lumisignals-penny_curve_pc_h1_all_dual_limit_20sl

# Check recent executions
aws logs describe-log-groups --query 'logGroups[?contains(logGroupName, `penny_curve`)]'
```

### **CloudWatch Logs Investigation**
```bash
# Check recent penny strategy logs (last 3 weeks)
aws logs filter-log-events \
  --log-group-name "/aws/lambda/lumisignals-penny_curve_pc_h1_all_dual_limit_20sl" \
  --start-time $(date -d "21 days ago" +%s)000

# Look for error patterns
aws logs filter-log-events \
  --log-group-name "/aws/lambda/lumisignals-penny_curve_pc_h1_all_dual_limit_20sl" \
  --filter-pattern "ERROR"
```

### **EventBridge Rule Investigation**
```bash
# Check if schedules are actually triggering
aws events list-targets-by-rule --rule lumisignals-penny_curve_pc_h1_all_dual_limit_20sl-schedule

# Check rule state
aws events describe-rule --name lumisignals-penny_curve_pc_h1_all_dual_limit_20sl-schedule
```

---

## 🎯 **Trade Logic Analysis Framework**

### **Penny Level Strategy Logic**
**Expected Behavior**: 
- Monitor psychological price levels (1.0000, 1.0500, 1.1000, etc.)
- Execute trades when price approaches these levels
- Use dual limit system with 20 pip stop loss
- Position sizing based on account balance

**Key Questions**:
1. **Are the functions executing?** (CloudWatch logs)
2. **Are market conditions being met?** (Price level logic)
3. **Are trades being attempted but failing?** (OANDA API errors)
4. **Are position size calculations preventing trades?** (Risk management)

### **Investigation Priority Order**:
1. **Function Execution Status** - Are they running at all?
2. **Error Log Analysis** - What errors are occurring?
3. **Market Data Access** - Can functions access current prices?
4. **Trade Execution Logic** - Are conditions being met?
5. **OANDA API Integration** - Are trades being submitted?

---

## 📝 **Maintenance Guidelines**

### **When Adding New Lambda Functions**:
1. **Update this registry** with function details
2. **Document strategy logic** and trigger conditions  
3. **Set up CloudWatch monitoring** and alerts
4. **Add to backup procedures** if function contains critical logic
5. **Create EventBridge rule** if scheduled execution needed

### **When Modifying Existing Functions**:
1. **Update "Last Modified" date** in this registry
2. **Document changes** in strategy logic
3. **Test in development** environment first
4. **Monitor logs** after deployment
5. **Update related documentation** (Architecture Bible, etc.)

---

**Next Actions Required**:
1. 🚨 **URGENT**: Investigate why penny level strategies stopped generating trades
2. 🔍 **Analyze**: CloudWatch logs for all 6 penny level functions  
3. 🧪 **Test**: Manual execution of penny level trade logic
4. 🔧 **Debug**: Market condition triggers and OANDA API connectivity
5. 📊 **Monitor**: Set up alerts for future trade generation failures

---

*This registry should be updated whenever Lambda functions are created, modified, or decommissioned.*