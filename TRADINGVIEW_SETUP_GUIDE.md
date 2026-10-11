# 📈 FinGroww Trading Intelligence — TradingView Pine Script Indicator Setup

FinGroww નું ક્વાન્ટિટેટિવ 95% એક્યુરેસી અલ્ગોરિધમ હવે સીધું **TradingView** પર વાપરી શકાય તે માટે **Pine Script (v5)** માં કન્વર્ટ કરવામાં આવ્યું છે.

ફાઇલ: [`FinGroww_Trading_Intelligence_v5.pine`](./FinGroww_Trading_Intelligence_v5.pine)

---

## 🛠️ TradingView માં ઉમેરવાના સ્ટેપ્સ (Step-by-Step Guide)

### સ્ટેપ ૧: TradingView ખોલો
1. તમારા બ્રાઉઝરમાં [TradingView.com](https://www.tradingview.com/) ખોલો અને લોગિન કરો.
2. કોઈપણ ચાર્ટ ખોલો (દા.ત. **NIFTY**, **BANKNIFTY**, **RELIANCE**, **TATA MOTORS**).
3. ટાઈમફ્રેમ પસંદ કરો: **5m**, **15m**, અથવા **1H** (ઇન્ટ્રાડે અને સ્કેલ્પિંગ માટે **5m/15m** શ્રેષ્ઠ છે).

---

### સ્ટેપ ૨: Pine Editor ખોલો
1. ચાર્ટ સ્ક્રીનના સૌથી નીચેના ભાગમાં **"Pine Editor"** ટેબ જોવા મળશે, તેના પર ક્લિક કરો.
2. જો ત્યાં પહેલેથી કોઈ ડિફોલ્ટ કોડ હોય, તો તેને સિલેક્ટ કરીને **Delete** કરી દો.

---

### સ્ટેપ ૩: કોડ પેસ્ટ કરો
1. તમારા પ્રોજેક્ટની ફાઇલ [`FinGroww_Trading_Intelligence_v5.pine`](./FinGroww_Trading_Intelligence_v5.pine) માંથી સંપૂર્ણ કોડ કૉપિ કરો.
2. Pine Editor માં પેસ્ટ કરો.

---

### સ્ટેપ ૪: Save અને ચાર્ટ પર ઉમેરો (Add to Chart)
1. ઉપર જમણી બાજુ આવેલું **"Save"** બટન દબાવો અને નામ આપો: `FinGroww Pro Radar v5`.
2. ત્યારબાદ **"Add to chart"** (ચાર્ટ પર ઉમેરો) બટન પર ક્લિક કરો!
3. તમારા ચાર્ટ પર તરત જ FinGroww નું ઇન્ટેલિજન્સ એન્જિન લાઈવ થઈ જશે:
   - 🟩 **Supertrend બેન્ડ** (લીલો/લાલ)
   - 📊 **EMA 9, 21, 50, 200 લાઈનો**
   - 🟣 **Session VWAP લાઈન**
   - ⚡ **BUY / SELL સિગ્નલ લેબલ્સ**
   - 🎯 **Stop Loss (SL), Target 1 (T1), Target 2 (T2) લેવલ્સ**
   - 📋 **જમણી બાજુ ઉપર Real-Time HUD Dashboard ટેબલ**

---

## 🔔 ઓટોમેટિક એલર્ટ્સ કેવી રીતે સેટ કરવા (Mobile / Web Push Alerts)

જ્યારે પણ FinGroww નું 95% અલ્ગોરિધમ નવો ટ્રેડ પકડશે ત્યારે તમને TradingView એપમાં અથવા ઇમેઇલ પર તરત જ એલર્ટ મળે તે માટે:
1. ચાર્ટ પર ઉપર ઘડિયાળ જેવું **"Alert" (Alt + A)** આઇકોન ક્લિક કરો.
2. **Condition** માં `FinGroww Pro Radar` પસંદ કરો.
3. નીચેનામાંથી એલર્ટ પસંદ કરો:
   - `FinGroww 95% BUY Signal` (ફક્ત બાય સિગ્નલ માટે)
   - `FinGroww 95% SELL Signal` (ફક્ત સેલ સિગ્નલ માટે)
   - `FinGroww Any Signal Alert` (બંને સિગ્નલો માટે)
4. **Trigger:** `Once Per Bar Close` (કેન્ડલ ક્લોઝ થયા પછી) પસંદ કરો જેથી કોઈ ફેક સિગ્નલ ન આવે.
5. **Notifications:** "Notify in app", "Show pop-up", અથવા "Send email" સિલેક્ટ કરીને **Create** કરો.

---

## ⚙️ ઇન્ડિકેટર સેટિંગ્સ કસ્ટમાઇઝેશન

ઇન્ડિકેટરના નામ પાસે ગિયર આઇકોન (Settings) પર ક્લિક કરીને તમે આ સેટિંગ્સ બદલી શકો છો:
- **Minimum Confluence Score (%):** ડિફોલ્ટ `58%` છે. વધુ કન્ઝર્વેટિવ સિગ્નલો માટે `65%` કે `70%` રાખી શકો છો.
- **Dynamic Targets:** Stop Loss (1.2x ATR), Target 1 (1.5x ATR), Target 2 (2.5x ATR), Target 3 (3.8x ATR).
- **Dashboard Position:** Top Right, Bottom Right, Top Left, Bottom Left.
- **Show/Hide EMAs & VWAP:** તમારી જરૂરિયાત મુજબ ઓન/ઓફ કરી શકો છો.
