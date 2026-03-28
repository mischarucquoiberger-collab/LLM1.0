import React, { useMemo, useState, useRef, useEffect, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, BookOpen, Globe, FileText,
  ExternalLink, Search, Database, X,
  Copy, Check, TrendingUp, Shield, BarChart3,
  Users, DollarSign, Lightbulb, ZoomIn, ZoomOut,
  Maximize2, Minimize2, Printer, Share2, PenLine,
  Keyboard, Zap, Trash2, Download, Clock,
  Terminal, Activity, Crosshair, Layers, Gem, Radar,
  Scale, HeartPulse, Calculator, Target, Eye, Shuffle,
} from "lucide-react";
import { toast } from "@/components/ui/use-toast";


/* ── Helpers ──────────────────────────────────────────────── */
function extractFileName(url) {
  if (!url) return null;
  try {
    const params = new URLSearchParams(url.split("?")[1] || "");
    return params.get("file") || null;
  } catch { return null; }
}

function findReportInHistory(jobId, url) {
  try {
    const history = JSON.parse(localStorage.getItem("reports_history") || "[]");
    if (jobId) {
      const match = history.find((h) => h.jobId === jobId);
      if (match) return match;
    }
    if (url) {
      const file = extractFileName(url);
      if (file) {
        const match = history.find((h) => h.html && h.html.includes(file));
        if (match) return match;
      }
    }
  } catch {}
  return null;
}


/* ── AI Research Tools ─────────────────────────────────────── */
const TOOL_SECTIONS = [
  {
    title: "Snapshot",
    tools: [
      {
        label: "Investment verdict",
        desc: "Buy/hold/avoid with conviction level and the key number to watch",
        prompt: `You are a senior equity research analyst at a top-tier investment bank covering Japanese equities. Deliver a decisive investment verdict.

**FORMAT:**

## Verdict: [STRONG BUY / BUY / HOLD / AVOID]
**Conviction: [HIGH / MEDIUM / LOW]**

**The 30-second pitch:** [2 sentences max — imagine you're in an elevator with a PM who covers 200 stocks. Make this one stick.]

**1. Business quality:** [Competitive position, moat durability, market share trajectory — cite specific data]
**2. Financial trajectory:** [ROE trend, margin direction, balance sheet, cash generation — exact numbers]
**3. Valuation signal:** [Cheap/fair/expensive vs peers AND vs own 5-year history — cite P/E, P/B, EV/EBITDA]

### Key number to watch
The single metric that determines if this thesis plays out:
- Current level: X
- Bull confirmation: X (validates thesis)
- Thesis killer: X (means you're wrong)

### What consensus is missing
[One genuine non-obvious insight about this company that most investors overlook — something that requires reading the actual filings, not just headlines.]

Be ruthlessly opinionated. Specific numbers only. No hedging.`,
        icon: FileText, color: "text-blue-400", bg: "bg-blue-500/8",
      },
      {
        label: "Bull vs bear debate",
        desc: "Quantified upside/downside with the key question bulls and bears disagree on",
        prompt: `Structure a professional bull/bear debate like a buy-side investment committee discussion.

**THE KEY DEBATE:**
[The ONE question where bulls and bears fundamentally disagree. Be specific — not "will growth continue?" but "Can the company sustain 15%+ OP margins as it scales into SE Asia, or will pricing pressure revert margins to the 10% industry average?"]

**BULL CASE (probability: X%):**
- Thesis in 1 sentence
- 3 catalysts with specific numbers (e.g., "Margin expansion from 8.2% to 12% driven by mix shift to recurring revenue")
- Bull target price: ¥XXX (show assumption: "at 18x bull EPS of ¥XXX")
- Implied upside: +XX%

**BEAR CASE (probability: X%):**
- Thesis in 1 sentence
- 3 risks with quantified downside
- Bear target price: ¥XXX
- Implied downside: -XX%

**BASE CASE (probability: X%):**
- Most likely outcome
- Fair value: ¥XXX

**EXPECTED VALUE TABLE:**
| Scenario | Probability | Target | Weighted Return |
| Bull | X% | ¥XXX | +X% |
| Base | X% | ¥XXX | +/-X% |
| Bear | X% | ¥XXX | -X% |
| **Probability-weighted value** | | **¥XXX** | **+/-XX%** |

**THE TIEBREAKER:** What single data point in the next 6-12 months tells you which case is playing out?`,
        icon: TrendingUp, color: "text-emerald-400", bg: "bg-emerald-500/8",
      },
      {
        label: "Peer valuation matrix",
        desc: "Bloomberg RV-style comp table — instantly see where the stock ranks vs peers",
        prompt: `Build a comprehensive peer valuation comparison table — this is the Bloomberg RV equivalent that every institutional investor needs. The goal is to show in one table exactly how this stock compares to its closest peers.

**Step 1: Identify 5-8 closest peers.**
Select companies that compete in the same market segment, have similar business models, or are in the same GICS sub-industry. For each peer, briefly justify why it's a valid comparison.

**Step 2: Build the comp table:**
| Company | Ticker | Mkt Cap | P/E (FY) | P/E (NTM) | EV/EBITDA | P/B | ROE | OP Margin | Rev Growth | Div Yield | Net D/E |
| **[This company]** | **XXX** | **¥Xbn** | **Xx** | **Xx** | **Xx** | **X.Xx** | **X%** | **X%** | **X%** | **X%** | **X%** |
| Peer 1 | XXX | ¥Xbn | Xx | Xx | Xx | X.Xx | X% | X% | X% | X% | X% |
| Peer 2 | ... | | | | | | | | | | |
| ... | | | | | | | | | | | |
| **Peer median** | | | **Xx** | **Xx** | **Xx** | **X.Xx** | **X%** | **X%** | **X%** | **X%** | |

Bold the subject company row. Use data from the report where available.

**Step 3: Relative positioning:**
| Metric | Company | Peer Median | Premium/Discount | Justified? |
| P/E | Xx | Xx | +/-XX% | Yes/No — because... |
| EV/EBITDA | Xx | Xx | +/-XX% | Yes/No — because... |
| P/B | X.Xx | X.Xx | +/-XX% | Yes/No — because... |

For each premium or discount, state whether it's justified by superior/inferior growth, profitability, or quality.

**Step 4: Fair value from peer multiples:**
- Applying peer median P/E to this company's EPS → fair value ¥XXX (+/-XX% vs current)
- Applying peer median EV/EBITDA → fair value ¥XXX (+/-XX% vs current)
- The peer-implied range: ¥XXX to ¥XXX

**One-line verdict:** [Is this stock cheap or expensive relative to its peers, and is the discount/premium deserved?]`,
        icon: Scale, color: "text-gray-400", bg: "bg-gray-500/8",
      },
      {
        label: "10-year owner's manual",
        desc: "Warren Buffett–style analysis — would you hold this for a decade?",
        prompt: `You are a long-term concentrated investor in the style of Warren Buffett, Charlie Munger, and Nick Sleep. Analyze this company as if you were deciding whether to buy and hold for 10 years — through recessions, management changes, and market panics. This is not about the next quarter. This is about the next decade.

**1. BUSINESS DURABILITY (Would this business exist in 10 years?)**
- What does this company do that customers cannot easily get elsewhere?
- Moat type: [Brand / Switching costs / Network effects / Cost advantage / Regulatory / None]
- Moat direction: [Widening / Stable / Narrowing] — with specific evidence
- "If I couldn't sell this stock for 10 years, would I be comfortable?" — Yes/No and why

**2. COMPOUNDING MATH (Can it double in 5 years?)**
The Rule of 72: to double in 5 years you need ~14.4% annual returns.
- Current ROE: X% → Retained earnings growth: X%
- Earnings CAGR last 5yr: X% → Projected EPS in 5yr: ¥X → in 10yr: ¥X
- At current P/E (Xx), implied 10yr price: ¥X (X.Xx your money)
- At normalized P/E (Xx), implied 10yr price: ¥X (X.Xx your money)

**3. TOTAL RETURN DECOMPOSITION (Where does the return come from?)**
| Source | Annual contribution | 10yr cumulative |
| Earnings growth | +X% | +XX% |
| Dividend yield (reinvested) | +X% | +XX% |
| Multiple expansion/contraction | +/-X% | +/-XX% |
| Buyback yield | +X% | +XX% |
| **Total expected return** | **+X%** | **+XX%** |

**4. REINVESTMENT CAPACITY (The Buffett question)**
"The ideal business earns very high returns on capital and can reinvest large amounts at those same returns."
- ROIC: X% — Can reinvest at this rate? How much of earnings?
- Reinvestment rate: X% (retained earnings / net income)
- Incremental ROIC (return on new capital deployed): X%
- Is the opportunity set expanding or shrinking?

**5. DIVIDEND TRAJECTORY (The income investor's dream)**
| Year | DPS | Payout ratio | Yield on cost (from today) |
| Current | ¥X | X% | X% |
| Year 3 (proj) | ¥X | X% | X% |
| Year 5 (proj) | ¥X | X% | X% |
| Year 10 (proj) | ¥X | X% | X% |
If dividends grow at X% annually, your yield-on-cost in 10 years: X%

**6. THESIS BREAKERS (What makes you sell)**
List the 3 specific, measurable conditions that would invalidate the 10-year thesis:
1. [Metric] falls below [threshold] — because [reason]
2. [Event] occurs — because [reason]
3. [Trend] reverses — because [reason]

**7. FINAL VERDICT:**
| | Assessment |
| Would you own for 10 years? | [Yes / No / Only at the right price] |
| Required margin of safety | [X% below fair value] |
| Max portfolio weight | [X%] |
| Conviction | [High / Medium / Low] |

**One sentence:** [Sum it up as if explaining to a smart friend over coffee]`,
        icon: Clock, color: "text-yellow-500", bg: "bg-yellow-500/8",
      },
    ],
  },
  {
    title: "Valuation",
    tools: [
      {
        label: "What's priced in?",
        desc: "Reverse-engineer the exact growth the market is paying for",
        prompt: `The most important question in investing. Reverse-engineer what the current stock price implies about this company's future.

**The McKinsey Value Driver Formula:**
Enterprise Value = NOPAT x (1 - g/ROIC) / (WACC - g)

This formula reveals a critical truth: growth only creates value when ROIC > WACC. Use this to frame the entire analysis.

**1. Implied growth rate:**
Using the current market cap and EV from the report:
- Enterprise value: ¥X (market cap +/- net debt)
- Current NOPAT: ¥X
- Assumed WACC: X% (risk-free + equity premium for Japan)
- Back-solve for implied growth rate g: X% CAGR
- Show your calculation step by step

**2. Implied profitability:**
What operating margin does the current price assume at steady state?
- Current margin: X% → Implied future margin: X%
- vs 5-year average: X%
- vs best-in-class peer: X%

**3. Expectations vs reality:**
| Metric | Market implies | 3yr actual avg | Mgmt guidance | Your estimate |
| Revenue growth | X% | X% | X% | X% |
| OP margin | X% | X% | X% | X% |
| ROIC | X% | X% | X% | X% |
| EPS growth | X% | X% | X% | X% |

**4. Value creation check:**
Using the McKinsey framework — is ROIC > WACC?
- If YES: growth adds value, the market may be right to pay for it
- If NO: growth destroys value, and the stock is expensive at ANY growth-based multiple

**5. Verdict:** "The market prices in [X% growth at Y% margins]. The data supports [A% growth at B% margins]. The stock is [X% overvalued/undervalued]."`,
        icon: Crosshair, color: "text-indigo-400", bg: "bg-indigo-500/8",
      },
      {
        label: "DCF scenario matrix",
        desc: "3-scenario DCF with full WACC x growth sensitivity grid",
        prompt: `Build a professional 3-scenario DCF valuation.

**Assumptions:**
| Input | Base | Bull | Bear | Rationale |
| Revenue CAGR (5yr) | X% | X% | X% | [1 sentence each] |
| Target OP margin Yr5 | X% | X% | X% | |
| Capex/Revenue | X% | X% | X% | |
| WACC | X% | X% | X% | |
| Terminal growth | X% | X% | X% | |

**Output:**
| Scenario | Fair Value/Share | vs Current | Upside/Downside |
| Bull | ¥XXX | ¥XXX | +XX% |
| Base | ¥XXX | ¥XXX | +/-XX% |
| Bear | ¥XXX | ¥XXX | -XX% |

**SENSITIVITY MATRIX (Base case):**
| WACC \\ Terminal g | 0% | 1% | 2% | 3% |
| 7% | ¥XXX | ¥XXX | ¥XXX | ¥XXX |
| 8% | ¥XXX | ¥XXX | ¥XXX | ¥XXX |
| 9% | ¥XXX | ¥XXX | ¥XXX | ¥XXX |
| 10% | ¥XXX | ¥XXX | ¥XXX | ¥XXX |
| 11% | ¥XXX | ¥XXX | ¥XXX | ¥XXX |

Bold the base case cell. Mark cells where the stock is >20% undervalued.

Use actual financials from the report. Every assumption must be grounded in data.`,
        icon: DollarSign, color: "text-cyan-400", bg: "bg-cyan-500/8",
      },
      {
        label: "Sum-of-parts breakup",
        desc: "Value each division independently — find the conglomerate discount",
        prompt: `Sum-of-parts valuation — the analysis activist investors use to build campaigns. Especially powerful in Japan where conglomerate discounts of 30-50% are common.

**Step 1: Segment identification**
List every business segment with revenue, operating profit, and margin.

**Step 2: Value each segment:**
| Segment | Revenue | OP | Margin | Best pure-play comp | Comp EV/EBITDA | Implied EV |
| [Name] | ¥Xbn | ¥Xbn | X% | [Specific company] | Xx | ¥Xbn |
Justify each comparable choice.

**Step 3: Balance sheet adjustments:**
| Item | Value | Notes |
| (+) Net cash or (-) net debt | ¥Xbn | |
| (+) Listed equity stakes at market | ¥Xbn | Mark to current value |
| (+) Hidden real estate value | ¥Xbn | If carried at historical cost |
| (-) Corporate overhead (capitalized) | ¥Xbn | 8-10x annual HQ costs |
| (-) Minority interests | ¥Xbn | |

**Step 4: SOTP summary:**
| | Value |
| Sum of segment values | ¥Xbn |
| + Balance sheet adjustments | ¥Xbn |
| = **Total SOTP value** | **¥Xbn** |
| **SOTP per share** | **¥XXX** |
| Current share price | ¥XXX |
| **Conglomerate discount** | **XX%** |

**Step 5: Catalyst for discount closure:**
What event could close the gap? (Spin-off, sale, activist, subsidiary IPO)
This analysis often reveals investors are getting one or more divisions for free.`,
        icon: Layers, color: "text-violet-400", bg: "bg-violet-500/8",
      },
    ],
  },
  {
    title: "Deep Dive",
    tools: [
      {
        label: "Earnings quality audit",
        desc: "Beneish M-Score, cash conversion, accruals, forensic red flags — graded A to D",
        prompt: `Institutional-grade earnings quality audit incorporating the Beneish M-Score — the model that caught Enron before it collapsed.

**PART 1: BENEISH M-SCORE**
Calculate each of the 8 variables using data from the report:

M = -4.84 + 0.920(DSRI) + 0.528(GMI) + 0.404(AQI) + 0.892(SGI) + 0.115(DEPI) - 0.172(SGAI) + 4.679(TATA) - 0.327(LVGI)

| Variable | Name | Formula | Value | Flag |
| DSRI | Days Sales Receivable Index | (Recv/Sales)t / (Recv/Sales)t-1 | X.XX | >1.0 = flag |
| GMI | Gross Margin Index | GM(t-1) / GM(t) | X.XX | >1.0 = margin deterioration |
| AQI | Asset Quality Index | [1-(CA+PPE)/TA]t / [1-(CA+PPE)/TA]t-1 | X.XX | >1.0 = capitalization concern |
| SGI | Sales Growth Index | Sales(t) / Sales(t-1) | X.XX | High growth = pressure to manipulate |
| DEPI | Depreciation Index | Dep Rate(t-1) / Dep Rate(t) | X.XX | >1.0 = slowing depreciation |
| SGAI | SGA Index | (SGA/Sales)t / (SGA/Sales)t-1 | X.XX | |
| TATA | Total Accruals/Assets | (WC chg ex-cash - Dep) / TA | X.XX | STRONGEST indicator (coeff 4.679) |
| LVGI | Leverage Index | (Debt/TA)t / (Debt/TA)t-1 | X.XX | >1.0 = increasing leverage |

**M-Score = X.XX**
- Above -1.78: **HIGH probability of manipulation**
- Above -2.22: **Elevated risk**
- Below -2.22: **Likely clean**

**PART 2: CASH FLOW QUALITY**
| Year | Net Income | Operating CF | OCF/NI | Accruals Ratio |
Show 3 years. OCF/NI < 0.8x = red flag. Accruals/TA > 10% = red flag.

**PART 3: WORKING CAPITAL SIGNALS**
| Metric | Year-2 | Year-1 | Current | vs Revenue growth |
| DSO | X | X | X | Diverging? |
| DIO | X | X | X | Diverging? |
DSO/DIO growing faster than revenue = classic manipulation signal.

**PART 4: SCHILIT SHENANIGAN CHECK**
Check for these Financial Shenanigans red flags:
- Revenue recognized too early or of questionable quality?
- One-time gains boosting income?
- Operating expenses shifted to later periods (improper capitalization)?
- Liabilities understated or not recorded?

**OVERALL GRADE: [A / B / C / D]**
A = Pristine (M-Score < -2.5, OCF/NI > 1.0x, no flags)
B = Clean (M-Score < -2.22, minor items)
C = Caution (M-Score between -2.22 and -1.78, material concerns)
D = Danger (M-Score > -1.78, multiple red flags)

**The one thing to worry about:** [Single most important finding]`,
        icon: Activity, color: "text-teal-400", bg: "bg-teal-500/8",
      },
      {
        label: "Profit bridge",
        desc: "Waterfall decomposition showing exactly what drove the earnings change",
        prompt: `Decompose Y/Y operating profit change into a clear waterfall — the #1 investment committee analysis.

**PROFIT BRIDGE:**

Previous year OP: ¥X million
----------------------------------------------
(+) Volume/revenue growth: +¥X million
    Why: [e.g., "15% unit growth in EV components"]
(+/-) Price/mix effect: +/-¥X million
    Why: [e.g., "premium mix raised ASP 8%"]
(+/-) Raw material/COGS: +/-¥X million
    Why: [e.g., "steel prices -8% Y/Y"]
(+/-) Personnel costs: +/-¥X million
    Why: [e.g., "200 engineers hired for R&D"]
(+/-) SGA/marketing: +/-¥X million
(+/-) R&D investment: +/-¥X million
(+/-) D&A: +/-¥X million
(+/-) FX impact: +/-¥X million
    Sensitivity: ¥1/$ = ~¥X million OP impact
(+/-) One-time items: +/-¥X million
    Specify: [restructuring, asset sale, impairment]
----------------------------------------------
= Current year OP: ¥X million (+/-X% Y/Y)
  Margin: X.X% to Y.Y%

**VERDICT:** Single biggest swing factor? Recurring or one-time?

**FORWARD BRIDGE (what's needed for +10% OP next year):**
| Driver | Contribution | Probability | Assumption |
| [Factor 1] | +¥X million | High/Med/Low | |
| [Factor 2] | +¥X million | High/Med/Low | |
| [Headwind] | -¥X million | High/Med/Low | |
| **Net** | **+¥X million (+X%)** | | |`,
        icon: BarChart3, color: "text-purple-400", bg: "bg-purple-500/8",
      },
      {
        label: "Capital allocation grade",
        desc: "ROIC track record, FCF deployment map, cash hoarding check",
        prompt: `Grade capital allocation — the #1 predictor of long-term shareholder returns.

**1. Value creation scorecard:**
| Metric | 3yr Avg | Current | Trend | vs WACC (~X%) |
| ROIC | X% | X% | Up/Down | Creating/Destroying |
| Incremental ROIC | — | X% | | Marginal return |
| ROE | X% | X% | | |
If ROIC < WACC, every yen of growth DESTROYS value.

**2. FCF deployment map:**
| Use of FCF | Amount | % of FCF | Assessment |
| Organic capex | ¥X | X% | Growth vs maintenance? |
| R&D | ¥X | X% | Yielding results? |
| M&A | ¥X | X% | Track record? |
| Dividends | ¥X | X% | Sustainable? |
| Buybacks | ¥X | X% | At fair prices? |
| Debt paydown | ¥X | X% | Prudent? |
| Cash accumulation | ¥X | X% | Lazy balance sheet? |

**3. Japan cash hoarding check:**
- Net cash: ¥X = X% of market cap [flag if >20%]
- Net cash per share: ¥X vs share price ¥X
- Capital return plan announced? Details?

**4. Shareholder returns:**
- Total payout ratio: X% (divs + buybacks / NI)
- Dividend CAGR (5yr): X%
- Buyback ROI: purchased below intrinsic value?

**GRADE: [A / B / C / D]**
A = Exceptional allocator (high ROIC, disciplined, shareholder-friendly)
B = Competent (generally value-creative)
C = Mediocre (cash hoarding or questionable M&A)
D = Poor (persistent value destruction)`,
        icon: Shield, color: "text-amber-400", bg: "bg-amber-500/8",
      },
    ],
  },
  {
    title: "Japan Edge",
    tools: [
      {
        label: "Hidden asset analysis",
        desc: "Cross-shareholdings, undervalued land, adjusted NAV — the Japan alpha source",
        prompt: `The analysis that separates Japan specialists from generalists. Japanese companies often carry assets at historical cost worth multiples of book value.

**1. Cross-shareholding securities (often the BIGGEST source):**
| Holding | Shares | Book value | Market value | Unrealized gain |
| [Company] | X | ¥X | ¥X | +¥X |
**Total unrealized securities gain: ¥X**
Note: In FY2023, Japanese companies unwound ¥36.9T of cross-shareholdings (record high, +86% Y/Y). Is this company participating?

**2. Real estate at historical cost:**
- Land/buildings carried at decades-old acquisition cost?
- Any revaluation data in footnotes?
- Tokyo/Osaka properties can be 5-10x book value
- **Estimated unrealized real estate gain: ¥X**

**3. Other hidden value:**
- Pension surplus (plan assets > obligations)
- Valuable IP/brands not on balance sheet
- Tax loss carryforwards
- Undervalued unlisted subsidiaries

**4. Adjusted valuation:**
| Metric | Reported | Adjusted | Difference |
| Book value/share | ¥X | ¥X | +X% |
| P/B ratio | X.Xx | X.Xx | |
| NAV per share | ¥X | ¥X | |
| Discount to adj NAV | — | X% | |

**5. Liquidation value floor:**
If all assets liquidated at fair value: ¥XXX per share
vs current price ¥XXX = X% margin of safety

**6. Catalyst watch:**
- Activist pressure? Which funds?
- TSE reform pushing unwinds?
- Announced asset sales or rationalization?
- Management stance on hidden value?`,
        icon: Lightbulb, color: "text-rose-400", bg: "bg-rose-500/8",
      },
      {
        label: "Management guidance decoder",
        desc: "Historical bias pattern, SUE score, adjusted 'real' forecast",
        prompt: `Decode Japanese management guidance — most companies are systematically conservative, and knowing the pattern is tradeable alpha.

**1. Track record:**
| Period | Initial rev guide | Actual rev | Error | Initial OP guide | Actual OP | Error |
Show all available periods. Calculate averages.

**2. The bias:**
- Revenue bias: guides X% below actual (positive = conservative)
- OP bias: guides X% below actual
- Consistency: Stable bias = predictable edge. Volatile = noise.

**3. Standardized Unexpected Earnings (SUE):**
SUE = (Actual EPS - Expected EPS) / Std Dev of past forecast errors
- Calculate SUE for each available period
- Higher SUE = stock tends to drift upward post-announcement (Post-Earnings Announcement Drift)
- This effect can persist for 60+ trading days

**4. Behavioral patterns:**
- **Front-loading conservatism?** Very low initial → revise up mid-year
- **Kitchen sinking?** Guide extremely low after bad year to reset base
- **Revision timing:** Q1 (early = confident), Q2, Q3?

**5. Decode current guidance:**
| Metric | Mgmt forecast | Bias adj. | Adjusted forecast | Consensus |
| Revenue | ¥X | +X% | ¥X | ¥X |
| OP | ¥X | +X% | ¥X | ¥X |
| EPS | ¥X | +X% | ¥X | ¥X |

**6. Trading signal:**
- Adjusted vs consensus gap: +/-X%
- If adjusted >5% above consensus: **Positive surprise likely**
- If roughly in line: **No edge**
- If adjusted >5% below: **Downside risk**

**CREDIBILITY: [HIGH / MEDIUM / LOW]** with justification.`,
        icon: Users, color: "text-sky-400", bg: "bg-sky-500/8",
      },
      {
        label: "TSE reform scorecard",
        desc: "ISS & Glass Lewis thresholds, P/B recovery roadmap, activist vulnerability",
        prompt: `Score this company on TSE governance reform compliance using the ACTUAL proxy advisor thresholds that determine institutional voting.

**SCORECARD (with real institutional thresholds):**
| Metric | Company | ISS threshold | Glass Lewis threshold | Pass/Fail |
| ROE | X.X% | <5% avg 5yr = AGAINST execs | — | |
| P/B ratio | X.Xx | — | — | >1.0x required |
| Board independence | X/Y (X%) | <1/3 = AGAINST | <1/3 = AGAINST insiders | |
| Strategic shareholdings/net assets | X% | — | >=10% = AGAINST chair | |
| Female directors | X/Y | — | 0 = AGAINST (2026) | |
| Director tenure (independence) | Xyr max | >12yr = not independent (2026) | >12yr = affiliated | |
| Shareholder return policy | [Details] | — | Specific plan required | |
| English disclosure | [Details] | — | Full IR materials | |
| Cost of capital disclosure | [Details] | WACC/ROIC published | — | |

**ISS RISK:** Will ISS recommend AGAINST top executives? (5yr avg ROE <5% = automatic recommendation against)
**Glass Lewis RISK:** Will GL recommend AGAINST board chair? (Strategic holdings >=10% net assets without clear reduction plan)

**P/B RECOVERY ANALYSIS (if P/B < 1.0x):**
Gordon Growth Model: P/B = (ROE - g) / (r - g)
- Required ROE for P/B = 1.0x: X% (at r=8%, g=2%)
- Current ROE gap: X percentage points
- Closing the gap:
  (a) Margin improvement: +X pp ROE
  (b) Leverage optimization: +X pp ROE
  (c) Buybacks: +X pp ROE
  (d) Asset sales: +X pp ROE

**ACTIVIST VULNERABILITY:**
| Factor | Value | Risk |
| Foreign ownership | X% | High if >30% |
| Net cash / mkt cap | X% | Target if >20% |
| P/B | X.Xx | Magnet if <0.8x |
| Known activists | [Names] | |

**GPIF ESG FACTOR CHECK** (world's largest pension fund, $1.7T AUM):
Research shows female directors and performance-linked pay have statistically significant positive impact on corporate value in Japan.
- Female director ratio: X% (vs GPIF finding of positive Tobin's Q impact)
- Performance-linked compensation: Yes/No

**STATUS: [LEADER / PROGRESSING / LAGGING / AT RISK]**
**Most impactful catalyst:** [One action that would most move the stock]`,
        icon: Zap, color: "text-orange-400", bg: "bg-orange-500/8",
      },
    ],
  },
  {
    title: "Alpha Signals",
    tools: [
      {
        label: "Compounder quality score",
        desc: "Fundsmith-grade scoring: ROCE, margins, cash conversion — with institutional thresholds",
        prompt: `Score this company using the frameworks of the world's best quality-growth investors. Fundsmith (Terry Smith) has compounded at 15.1% annually since 2010 using these exact criteria.

**Rate each dimension and compare to institutional benchmarks:**

**1. Return on Capital [X/5]**
- ROCE: X% (Fundsmith portfolio avg: 30%, minimum: 15%)
- ROIC ex-goodwill: X% (true organic return)
- Is the company earning well above its cost of capital?
[Evidence: ...]

**2. Gross Margin [X/5]**
- Current: X% (Fundsmith portfolio avg: 60%)
- Trend over 3 years: stable/expanding/contracting
- High gross margin = pricing power = moat indicator
[Evidence: ...]

**3. Cash Conversion [X/5]**
- OCF / Operating Profit: X% (Fundsmith target: >=95%, portfolio avg: 100%)
- FCF / Net Income: X%
- Are earnings backed by real cash?
[Evidence: ...]

**4. Capital Lightness [X/5]**
- Capex / Revenue: X% (lower = better for compounding)
- Capex / Depreciation: Xx (>1.5x = heavy reinvestment needs)
- Can the business grow without constant heavy investment?
[Evidence: ...]

**5. Reinvestment Runway [X/5]**
- TAM vs current revenue: how much room to grow?
- Can capital be redeployed at high ROIC for 5-10+ more years?
- Organic growth vs M&A dependence (organic = better)
[Evidence: ...]

**6. Competitive Moat [X/5]**
- Type: network effects / switching costs / intangibles / cost / scale
- Direction: widening, stable, or narrowing?
- Market share trend
[Evidence: ...]

**7. Management Alignment [X/5]**
- Insider ownership: X%
- Compensation: aligned with long-term value?
- Capital allocation track record
[Evidence: ...]

**8. Resilience [X/5]**
- Revenue/earnings volatility through cycles
- Sensitivity to macro (rates, FX, commodities)
- Regulatory or technological disruption risk
[Evidence: ...]

**COMPOUNDER SCORE: X / 40**
| Range | Verdict |
| 35-40 | Elite compounder — buy and hold for a decade |
| 28-34 | Strong quality — high probability of outperformance |
| 20-27 | Mixed — some quality traits but material weaknesses |
| <20 | Not a compounder — value trap risk |

**Fundsmith filter:** Would Terry Smith buy this? (Needs: high ROCE sustained through cycle, no leverage dependency, cash-generative, resilient to disruption)

**Final verdict:** [Can you own this for 10 years? What's the biggest risk to the compounding thesis?]`,
        icon: Gem, color: "text-fuchsia-400", bg: "bg-fuchsia-500/8",
      },
      {
        label: "Contrarian signal scan",
        desc: "8 systematic signals for where data contradicts the consensus narrative",
        prompt: `Systematically scan for disconnects between market narrative and fundamental data. The best investments exist where consensus has diverged from reality.

**Scan each signal:**

**1. Improving quality, falling price**
Earnings quality (cash conversion, accruals) IMPROVING while sentiment is negative?
[Status: Firing / Not firing] [Evidence]

**2. Accrual anomaly (Sloan 1996)**
Low accruals ratio (high cash earnings quality) predicts future outperformance. This anomaly has generated ~12% annual alpha historically.
- Accruals ratio: X% — Is this in the low-accrual quintile (<5%)?
[Status: Firing / Not firing]

**3. FCF yield vs dividend yield gap**
FCF yield: X% vs Dividend yield: X%
Large gap = massive capacity for shareholder return increases the market hasn't priced.
[Status: Firing / Not firing]

**4. Balance sheet ignored**
Net cash: ¥X (X% of market cap)
If >20%, the market is ignoring a fortress balance sheet. On EV basis, stock is X% cheaper.
[Status: Firing / Not firing]

**5. Margin inflection missed**
OP margins at cyclical trough or inflection? Cost restructuring flowing through? Mix shift to higher-margin products?
[Status: Firing / Not firing]

**6. Guidance decode disagrees with consensus**
Adjusted forecast (after historical bias) vs consensus: gap of X%
[Status: Firing / Not firing]

**7. Cyclical distortion**
Trailing P/E: Xx (looks expensive) vs Normalized P/E (mid-cycle margins): Xx (actually cheap)
[Status: Firing / Not firing]

**8. Governance catalyst not priced**
Cross-shareholding unwinds, buybacks, board changes announced but stock hasn't moved?
[Status: Firing / Not firing]

**SIGNAL DASHBOARD:**
| # | Signal | Status | Strength | Direction |
| 1 | Quality vs price | | Strong/Weak | Bull/Bear |
| 2 | Accrual anomaly | | Strong/Weak | Bull/Bear |
| 3 | FCF-dividend gap | | Strong/Weak | Bullish |
| 4 | Hidden balance sheet | | Strong/Weak | Bullish |
| 5 | Margin inflection | | Strong/Weak | Bullish |
| 6 | Guidance decode | | Strong/Weak | Bull/Bear |
| 7 | Cyclical distortion | | Strong/Weak | Bullish |
| 8 | Governance catalyst | | Strong/Weak | Bullish |

**Signals firing: X/8**

**CONTRARIAN VERDICT:** [Is the weight of evidence enough to say the market is wrong? What's the re-rating catalyst?]

Only flag signals with genuine evidence. Don't force it.`,
        icon: Radar, color: "text-lime-400", bg: "bg-lime-500/8",
      },
      {
        label: "Financial health pulse",
        desc: "Piotroski F-Score (9-pt) + Altman Z-Score — one-click quantitative health check",
        prompt: `Two of the most respected quantitative scoring systems in finance, calculated in one analysis. The Piotroski F-Score predicted value stock outperformance, and the Altman Z-Score predicted bankruptcy — both with decades of academic validation.

**PART 1: PIOTROSKI F-SCORE (0-9 points)**

Score each of the 9 binary signals:

**Profitability (4 points):**
| Signal | Test | Result | Score |
| F1 | ROA > 0 (positive net income / total assets) | X% | 0 or 1 |
| F2 | Operating Cash Flow > 0 | ¥X | 0 or 1 |
| F3 | ROA increasing Y/Y | X% vs X% | 0 or 1 |
| F4 | OCF > Net Income (earnings quality) | ¥X vs ¥X | 0 or 1 |

**Leverage & Liquidity (3 points):**
| Signal | Test | Result | Score |
| F5 | Long-term debt ratio declining Y/Y | X% vs X% | 0 or 1 |
| F6 | Current ratio improving Y/Y | X.Xx vs X.Xx | 0 or 1 |
| F7 | No new equity issuance in past year | Yes/No | 0 or 1 |

**Operating Efficiency (2 points):**
| Signal | Test | Result | Score |
| F8 | Gross margin improving Y/Y | X% vs X% | 0 or 1 |
| F9 | Asset turnover improving Y/Y | X.Xx vs X.Xx | 0 or 1 |

**F-SCORE: X / 9**
- 8-9: Very strong — historically outperforms by significant margin
- 5-7: Moderate — average quality
- 0-4: Weak — value trap risk, historically underperforms

**PART 2: ALTMAN Z-SCORE**

Z = 1.2(X1) + 1.4(X2) + 3.3(X3) + 0.6(X4) + 1.0(X5)

| Variable | Formula | Value | Weighted |
| X1 | Working Capital / Total Assets | X.XX | X.XX |
| X2 | Retained Earnings / Total Assets | X.XX | X.XX |
| X3 | EBIT / Total Assets (highest weight: 3.3x) | X.XX | X.XX |
| X4 | Market Cap / Total Liabilities | X.XX | X.XX |
| X5 | Revenue / Total Assets | X.XX | X.XX |

**Z-SCORE: X.XX**
- Above 3.0: **Safe zone** — bankruptcy very unlikely
- 1.8 to 3.0: **Grey zone** — some risk, monitor closely
- Below 1.8: **Distress zone** — elevated bankruptcy risk

Accuracy: 72% correct predicting bankruptcy 2 years out with only 6% false negatives.

**COMBINED HEALTH MATRIX:**
| | Z-Score Safe (>3.0) | Z-Score Grey (1.8-3.0) | Z-Score Distress (<1.8) |
| F-Score High (8-9) | Excellent health | Strong but watch leverage | Unusual — investigate |
| F-Score Mid (5-7) | Solid | Average | Concern |
| F-Score Low (0-4) | Declining quality | Significant risk | Severe distress |

**This company: [F-Score X, Z-Score X.XX] = [Health assessment]**

**One-line verdict:** [The single most important thing this health check reveals]`,
        icon: HeartPulse, color: "text-red-400", bg: "bg-red-500/8",
      },
      {
        label: "Risk-reward asymmetry map",
        desc: "Quantify the payoff skew — upside vs downside scenarios with position sizing",
        prompt: `You are a portfolio manager at a top hedge fund. Build a complete risk-reward asymmetry analysis — this is the framework that separates professional investors from amateurs. The goal: quantify exactly how much you can lose vs gain, and determine optimal position sizing.

**1. DOWNSIDE SCENARIOS (what kills the stock):**
| Scenario | Trigger | Probability | Target price | Drawdown |
| Earnings miss + multiple compression | [specific] | X% | ¥XXX | -XX% |
| Sector/macro shock | [specific] | X% | ¥XXX | -XX% |
| Company-specific disaster | [specific] | X% | ¥XXX | -XX% |
| Terminal impairment (permanent loss) | [specific] | X% | ¥XXX | -XX% |

**Probability-weighted downside: -XX%**

**2. UPSIDE SCENARIOS (what 2-3x the stock):**
| Scenario | Trigger | Probability | Target price | Upside |
| Earnings beat + re-rating | [specific] | X% | ¥XXX | +XX% |
| Strategic catalyst (M&A, spinoff, reform) | [specific] | X% | ¥XXX | +XX% |
| Secular tailwind acceleration | [specific] | X% | ¥XXX | +XX% |
| Blue sky (everything works) | [specific] | X% | ¥XXX | +XX% |

**Probability-weighted upside: +XX%**

**3. ASYMMETRY RATIO:**
Upside/Downside ratio: X.Xx
- Above 3.0x: **Exceptional** — classic asymmetric bet
- 2.0x-3.0x: **Attractive** — risk well compensated
- 1.0x-2.0x: **Fair** — balanced
- Below 1.0x: **Poor** — risk not compensated

**4. EXPECTED VALUE:**
E(V) = Σ (probability × return) for all scenarios
= **+/-XX%** annualized

**5. KELLY CRITERION POSITION SIZE:**
Kelly % = (bp - q) / b
Where: b = payoff ratio, p = win probability, q = loss probability
- Full Kelly: X% of portfolio (too aggressive for most)
- Half Kelly (recommended): X% of portfolio
- Quarter Kelly (conservative): X% of portfolio

For a ¥X million portfolio, this means ¥X million position (XX shares at ¥XXX).

**6. KEY RISK TO MONITOR:**
The single factor that would flip this from asymmetric opportunity to value trap:
- What it is: [specific metric or event]
- Current level: X
- Danger threshold: X
- How to track it: [data source or report section]

**VERDICT:** [Is this a fat pitch? Would you put real money here?]`,
        icon: Target, color: "text-pink-400", bg: "bg-pink-500/8",
      },
      {
        label: "Short thesis builder",
        desc: "Force the bear case — 6-section devil's advocate analysis with worry grade",
        prompt: `You are a short-seller at a top activist fund. Your job is to find what's WRONG with this company. This is the analysis long-only investors skip — and it's the one that saves you from value traps. Be ruthlessly skeptical. Find the cracks.

**WORRY GRADE: [A / B / C / D / F]**
(A = pristine, nothing to worry about. F = run away. Grade BEFORE the analysis so you commit to a view.)

**1. BUSINESS DETERIORATION SIGNALS**
- Is the core business actually growing, or is it M&A / accounting?
- Revenue quality: organic vs acquired vs FX vs price vs volume
- Customer concentration risk: top 5 customers as % of revenue
- Product lifecycle: growth / maturity / decline? Evidence?
- Any signs of commoditization or disruption?
[Red flags found: X]

**2. FINANCIAL RED FLAGS**
- Receivables growing faster than revenue? (channel stuffing indicator)
- Inventory buildup? (demand weakness indicator)
- Capitalizing expenses that should be expensed? (R&D, SBC)
- Off-balance-sheet liabilities? (operating leases, guarantees, pensions)
- Related party transactions?
- Audit opinion qualifications?
- Cash flow from operations vs reported net income divergence?
[Red flags found: X]

**3. VALUATION TRAP ANALYSIS**
- Is it "cheap" for a reason? (declining business, one-time earnings, cyclical peak)
- Peak earnings risk: are current margins sustainable or cyclically inflated?
- If you normalize margins to 5-year average, what's the REAL P/E?
- Reported P/E: Xx → Normalized P/E: Xx → Gap: X%
- Hidden liabilities that reduce true equity value?

**4. MANAGEMENT CONCERNS**
- Insider selling patterns (last 12 months)?
- Executive compensation vs performance alignment?
- Empire building? (M&A track record, ROIC on acquisitions)
- Promotional behavior? (overpromising, guidance gaming)
- Related party deals or self-dealing?
- Board independence and quality?

**5. CATALYST TIMELINE (What makes this go down)**
| Catalyst | Probability | Timing | Impact |
| Earnings miss | X% | [when] | -X% |
| Margin compression | X% | [when] | -X% |
| Competition intensifies | X% | [when] | -X% |
| Regulatory/legal risk | X% | [when] | -X% |
| Balance sheet stress | X% | [when] | -X% |

**6. THE KILL SHOT**
The single biggest risk that most investors are underweighting:
- What it is: [be specific]
- Why the market ignores it: [narrative or anchoring bias]
- What would trigger repricing: [specific event or data point]
- Potential downside if it plays out: -X%

**FINAL SHORT THESIS (2 sentences max):**
[Summarize why a short-seller would target this stock]

**IMPORTANT:** Even if you ultimately think this is a good company, FORCE the bear case. Every company has weaknesses. Find them. The goal is not to conclude "short it" — it's to stress-test the bull case.`,
        icon: Eye, color: "text-stone-400", bg: "bg-stone-500/8",
      },
    ],
  },
];


/* ── Note templates ──────────────────────────────────────── */
const NOTE_TEMPLATES = [
  { label: "Thesis", text: "Investment Thesis:\n\u2022 " },
  { label: "Risks", text: "Key Risks:\n\u2022 " },
  { label: "Questions", text: "Follow-up Questions:\n\u2022 " },
  { label: "Catalysts", text: "Catalysts & Timeline:\n\u2022 " },
  { label: "Action", text: "Action Items:\n\u2022 " },
];

/* ── Keyboard shortcuts ─────────────────────────────────── */
const SHORTCUTS = [
  { keys: ["1"], desc: "Sources" },
  { keys: ["2"], desc: "Notes" },
  { keys: ["3"], desc: "Research tools" },
  { keys: ["4"], desc: "Valuation lab" },
  { keys: ["Q"], desc: "Query mode" },
  { keys: ["Esc"], desc: "Close panel" },
  { keys: ["+"], desc: "Zoom in" },
  { keys: ["-"], desc: "Zoom out" },
  { keys: ["0"], desc: "Reset zoom" },
  { keys: ["F"], desc: "Fullscreen" },
  { keys: ["P"], desc: "Print report" },
  { keys: ["?"], desc: "This help" },
];


/* ── Source card ─────────────────────────────────────────── */
function SourceCard({ source, index }) {
  let hostname = "";
  try { hostname = new URL(source.url).hostname.replace("www.", ""); } catch {}
  const isEdinet = source.type === "edinet";

  return (
    <motion.a
      href={source.url || "#"}
      target={source.url ? "_blank" : undefined}
      rel="noreferrer"
      onClick={source.url ? undefined : (e) => e.preventDefault()}
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.015, 0.4), duration: 0.3 }}
      className="group flex gap-3 p-3 rounded-xl bg-black/[0.02] border border-black/[0.06] hover:bg-black/[0.04] hover:border-black/[0.12] transition-all duration-200"
    >
      <div className="shrink-0 mt-0.5">
        <span className={`inline-flex items-center justify-center w-6 h-6 rounded-lg text-[10px] font-bold tabular-nums ${
          isEdinet
            ? "bg-amber-500/10 text-amber-400/80 ring-1 ring-amber-500/20"
            : "bg-blue-500/10 text-blue-400/80 ring-1 ring-blue-500/20"
        }`}>
          {source.id || index + 1}
        </span>
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className={`text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${
            isEdinet ? "bg-amber-500/10 text-amber-400/70" : "bg-blue-500/10 text-blue-400/70"
          }`}>
            {isEdinet ? "EDINET" : "WEB"}
          </span>
          {hostname && (
            <span className="text-[10px] text-gray-300 font-mono truncate">{hostname}</span>
          )}
        </div>
        <p className="text-[12px] text-gray-600 font-medium leading-snug line-clamp-1 group-hover:text-gray-900 transition-colors">
          {source.title || hostname || "Untitled"}
        </p>
        {source.snippet && (
          <p className="text-[11px] text-gray-300 leading-relaxed line-clamp-2 mt-1">{source.snippet}</p>
        )}
        {source.date && (
          <p className="text-[10px] text-gray-300 mt-1 font-mono">{source.date}</p>
        )}
      </div>

      <ExternalLink className="w-3 h-3 text-transparent group-hover:text-gray-400 transition-colors shrink-0 mt-1" />
    </motion.a>
  );
}

/* ── Main component ──────────────────────────────────────── */
export default function ReportViewer() {
  const location = useLocation();
  const navigate = useNavigate();

  // Expose navigate for AI markdown internal links
  useEffect(() => {
    window.__reportAssistantNavigate = (path) => navigate(path);
    return () => { delete window.__reportAssistantNavigate; };
  }, [navigate]);

  const search = useMemo(() => new URLSearchParams(location.search), [location.search]);

  const rawUrl = search.get("url");
  // Only allow same-origin /download paths — reject external URLs
  const url = rawUrl && /^\/download[\/?]/.test(rawUrl) ? rawUrl : null;
  const title = search.get("title") || "Report";
  const jobId = search.get("jobId") || null;
  const isPdf = url && url.toLowerCase().includes(".pdf");

  const reportData = useMemo(() => findReportInHistory(jobId, url), [jobId, url]);
  const fileName = useMemo(() => extractFileName(url), [url]);
  const companyName = reportData?.companyName || title;
  const sources = useMemo(() => reportData?.sources || [], [reportData]);
  const ticker = reportData?.ticker || "";
  const notesKey = jobId || fileName || null;

  /* ── Panel state ───────────────────────────── */
  const initTab = location.state?.openTab;
  const [panelOpen, setPanelOpen] = useState(!!initTab);
  const [activeTab, setActiveTab] = useState(initTab || "sources");
  const [sourceFilter, setSourceFilter] = useState("");

  /* ── Viewer state ──────────────────────────── */
  const [zoom, setZoom] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

  /* ── Notes state ───────────────────────────── */
  const [notes, setNotes] = useState("");
  const [lastSaved, setLastSaved] = useState(null);
  const notesModified = useRef(false);
  const notesRef = useRef(null);

  /* ── Calc state ─────────────────────────────── */
  const [calcInputs, setCalcInputs] = useState({ eps: "", bvps: "", growth: "8", discount: "10", price: "", dividend: "" });
  const updateCalc = useCallback((field, val) => setCalcInputs(prev => ({ ...prev, [field]: val })), []);
  const calcResults = useMemo(() => {
    const eps = parseFloat(calcInputs.eps) || 0;
    const bvps = parseFloat(calcInputs.bvps) || 0;
    const g = (parseFloat(calcInputs.growth) || 0) / 100;
    const r = (parseFloat(calcInputs.discount) || 0) / 100;
    const price = parseFloat(calcInputs.price) || 0;
    const div = parseFloat(calcInputs.dividend) || 0;
    const graham = eps > 0 && bvps > 0 ? Math.sqrt(22.5 * eps * bvps) : null;
    const grahamGrowth = eps > 0 && r > 0 ? eps * (8.5 + 2 * (g * 100)) * (4.4 / (r * 100)) : null;
    const dcf = eps > 0 && r > g && r > 0 ? (eps * (1 + g)) / (r - g) : null;
    const ddm = div > 0 && r > g && r > 0 ? (div * (1 + g)) / (r - g) : null;
    const earningsYield = eps > 0 && price > 0 ? (eps / price) * 100 : null;
    const values = [graham, grahamGrowth, dcf, ddm].filter(v => v !== null && isFinite(v) && v > 0);
    const avg = values.length > 0 ? values.reduce((a, b) => a + b, 0) / values.length : null;
    const mos = avg && price > 0 ? ((avg - price) / avg) * 100 : null;
    const userG = parseFloat(calcInputs.growth) || 8;
    const userR = parseFloat(calcInputs.discount) || 10;
    const growthRates = [...new Set(Array.from({ length: 7 }, (_, i) => Math.max(0, Math.round(userG - 6 + i * 2))))].slice(0, 6);
    const discountRates = [...new Set(Array.from({ length: 7 }, (_, i) => Math.max(1, Math.round(userR - 3 + i))))].slice(0, 6);
    const gridPrice = price;
    const grid = discountRates.map(dr => growthRates.map(gr => {
      const gd = gr / 100, rd = dr / 100;
      return eps > 0 && rd > gd ? Math.round((eps * (1 + gd)) / (rd - gd)) : null;
    }));
    return { graham, grahamGrowth, dcf, ddm, earningsYield, avg, mos, grid, growthRates, discountRates, gridPrice };
  }, [calcInputs]);


  /* ── Scenario state ──────────────────────────── */
  const [scenarioInputs, setScenarioInputs] = useState({ revenue: "", opMargin: "", taxRate: "30", shares: "", revGrowth: "8", marginDelta: "0", terminalPE: "15" });
  const updateScenario = useCallback((field, val) => setScenarioInputs(prev => ({ ...prev, [field]: val })), []);
  const scenarioResults = useMemo(() => {
    const rev = parseFloat(scenarioInputs.revenue) || 0;
    const margin = (parseFloat(scenarioInputs.opMargin) || 0) / 100;
    const taxRaw = parseFloat(scenarioInputs.taxRate);
    const tax = Math.max(0, Math.min(0.95, (isNaN(taxRaw) ? 30 : taxRaw) / 100));
    const shares = parseFloat(scenarioInputs.shares) || 0;
    const revG = (parseFloat(scenarioInputs.revGrowth) || 0) / 100;
    const mDelta = (parseFloat(scenarioInputs.marginDelta) || 0) / 100;
    const pe = parseFloat(scenarioInputs.terminalPE) || 0;
    const price = parseFloat(calcInputs.price) || 0;
    if (!rev || !shares || !pe) return null;
    const years = [1, 3, 5];
    const projections = years.map(y => {
      const projRev = rev * Math.pow(1 + revG, y);
      const projMargin = Math.max(0, Math.min(1, margin + mDelta * y));
      const projOP = projRev * projMargin;
      const projNI = projOP * (1 - tax);
      const projEPS = projNI / shares;
      const targetPrice = projEPS * pe;
      const cagr = price > 0 && targetPrice > 0 ? (Math.pow(targetPrice / price, 1 / y) - 1) * 100 : null;
      return { year: y, revenue: projRev, opMargin: projMargin * 100, opIncome: projOP, netIncome: projNI, eps: projEPS, targetPrice, cagr };
    });
    return projections;
  }, [scenarioInputs, calcInputs.price]);

  /* ── DuPont state ──────────────────────────── */
  const [dupontInputs, setDupontInputs] = useState({ revenue: "", netIncome: "", totalAssets: "", totalEquity: "" });
  const updateDupont = useCallback((field, val) => setDupontInputs(prev => ({ ...prev, [field]: val })), []);
  const dupontResults = useMemo(() => {
    const rev = parseFloat(dupontInputs.revenue) || 0;
    const ni = parseFloat(dupontInputs.netIncome) || 0;
    const ta = parseFloat(dupontInputs.totalAssets) || 0;
    const eq = parseFloat(dupontInputs.totalEquity) || 0;
    if (!rev || dupontInputs.netIncome === "" || !ta || !eq || eq < 0 || ta < 0) return null;
    const netMargin = (ni / rev) * 100;
    const assetTurnover = rev / ta;
    const equityMultiplier = ta / eq;
    const roe = (ni / eq) * 100;
    const roa = (ni / ta) * 100;
    return { netMargin, assetTurnover, equityMultiplier, roe, roa };
  }, [dupontInputs]);

  /* ── Compound return state ─────────────────── */
  const [returnInputs, setReturnInputs] = useState({ amount: "", expectedReturn: "10" });
  const updateReturn = useCallback((field, val) => setReturnInputs(prev => ({ ...prev, [field]: val })), []);
  const compoundResults = useMemo(() => {
    const amount = parseFloat(returnInputs.amount) || 0;
    const ret = (parseFloat(returnInputs.expectedReturn) || 0) / 100;
    const price = parseFloat(calcInputs.price) || 0;
    const div = parseFloat(calcInputs.dividend) || 0;
    const divYield = price > 0 && div > 0 ? div / price : 0;
    if (amount <= 0 || ret <= 0) return null;
    const totalReturn = ret + divYield;
    const years = [1, 3, 5, 10, 20];
    return {
      divYield: divYield * 100,
      totalReturn: totalReturn * 100,
      rows: years.map(y => {
        const value = amount * Math.pow(1 + totalReturn, y);
        return { year: y, value, gain: value - amount, multiple: value / amount };
      })
    };
  }, [returnInputs, calcInputs.price, calcInputs.dividend]);

  /* ── Monte Carlo state ─────────────────────── */
  const [mcSeed, setMcSeed] = useState(42);
  const mcResults = useMemo(() => {
    const eps = parseFloat(calcInputs.eps) || 0;
    const baseG = (parseFloat(calcInputs.growth) || 0) / 100;
    const baseR = (parseFloat(calcInputs.discount) || 0) / 100;
    const price = parseFloat(calcInputs.price) || 0;
    if (eps <= 0 || baseR <= baseG || baseR <= 0 || price <= 0) return null;

    const N = 3000;
    // Mulberry32 PRNG for deterministic results
    let s = mcSeed | 0;
    const rand = () => { s = s + 0x6D2B79F5 | 0; let t = Math.imul(s ^ s >>> 15, 1 | s); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
    // PERT distribution: mode-heavy triangular (professional standard for analyst estimates)
    const pert = (min, mode, max) => {
      const alpha = 1 + 4 * ((mode - min) / (max - min));
      const beta = 1 + 4 * ((max - mode) / (max - min));
      // Beta variate via Jöhnk's method (simple for small alpha/beta)
      let u, v, x;
      do { u = Math.pow(rand(), 1 / alpha); v = Math.pow(rand(), 1 / beta); x = u + v; } while (x > 1);
      return min + (max - min) * (u / x);
    };

    const values = [];
    // Growth: PERT with spread around base (min 3pp spread to avoid degenerate distributions)
    const gMin = Math.max(-0.05, baseG - Math.max(baseG * 0.7, 0.015));
    const gMax = baseG + Math.max(baseG * 0.8, 0.02);
    // Discount: PERT with tighter range (±30%)
    const rMin = Math.max(0.03, baseR * 0.7);
    const rMax = baseR * 1.35;
    // Negative correlation between growth & discount: -0.3
    // (high-growth eras tend to have higher rates, but for a single stock, higher discount = worse)
    const rho = -0.3;
    for (let i = 0; i < N; i++) {
      const simG = pert(gMin, baseG, gMax);
      // Correlated discount: mix independent PERT draw with growth shock
      const indepR = pert(rMin, baseR, rMax);
      const gShock = (simG - baseG) / (gMax - gMin); // normalized growth surprise
      const simR = Math.max(0.02, indepR + rho * (rMax - rMin) * gShock);
      if (simR <= simG || simR <= 0) continue;
      const fv = (eps * (1 + simG)) / (simR - simG);
      if (fv > 0 && isFinite(fv) && fv < price * 20) values.push(fv);
    }
    if (values.length < 200) return null;
    values.sort((a, b) => a - b);

    const pctile = (p) => values[Math.floor(values.length * p)];
    const median = pctile(0.5);
    const p5 = pctile(0.05);
    const p10 = pctile(0.1);
    const p25 = pctile(0.25);
    const p75 = pctile(0.75);
    const p90 = pctile(0.9);
    const p95 = pctile(0.95);
    const mean = values.reduce((a, b) => a + b, 0) / values.length;
    const underPct = (values.filter(v => v > price).length / values.length) * 100;

    // Histogram: 24 bins between p5 and p95
    const bins = 24;
    const lo = p5;
    const hi = p95;
    const bw = (hi - lo) / bins;
    if (bw <= 0) return null;
    const hist = Array(bins).fill(0);
    let maxC = 0;
    values.forEach(v => {
      const idx = Math.floor((v - lo) / bw);
      if (idx >= 0 && idx < bins) { hist[idx]++; maxC = Math.max(maxC, hist[idx]); }
    });
    const histData = hist.map((c, i) => ({
      mid: lo + (i + 0.5) * bw,
      count: c,
      height: maxC > 0 ? (c / maxC) * 100 : 0,
      abovePrice: (lo + (i + 0.5) * bw) > price,
    }));
    // Find which bin the current price falls in
    const priceIdx = Math.floor((price - lo) / bw);

    return { median, mean, p10, p25, p75, p90, underPct, histData, priceIdx, simCount: values.length, lo, hi };
  }, [calcInputs.eps, calcInputs.growth, calcInputs.discount, calcInputs.price, mcSeed]);

  /* ── Investment Scorecard ────────────────────── */
  const scorecard = useMemo(() => {
    const eps = parseFloat(calcInputs.eps) || 0;
    const bvps = parseFloat(calcInputs.bvps) || 0;
    const price = parseFloat(calcInputs.price) || 0;
    const div = parseFloat(calcInputs.dividend) || 0;
    const g = parseFloat(calcInputs.growth) || 0;
    if (!eps || !price) return null;

    // Value (0-30): P/E, P/B, Margin of Safety
    let value = 0;
    const pe = eps > 0 ? price / eps : -1;
    if (pe > 0 && pe < 8) value += 20; else if (pe > 0 && pe < 12) value += 16; else if (pe > 0 && pe < 15) value += 12; else if (pe > 0 && pe < 20) value += 7; else value += 3;
    if (bvps > 0) { const pb = price / bvps; if (pb < 0.8) value += 10; else if (pb < 1.0) value += 8; else if (pb < 1.5) value += 5; else if (pb < 2.5) value += 2; else value += 1; }
    else value += 3;

    // Growth (0-25): growth rate + scenario CAGR
    let growth = 0;
    if (g >= 15) growth += 18; else if (g >= 10) growth += 15; else if (g >= 7) growth += 12; else if (g >= 4) growth += 8; else if (g >= 0) growth += 4;
    if (scenarioResults && scenarioResults[1]?.cagr > 0) {
      const cagr = scenarioResults[1].cagr;
      if (cagr >= 15) growth += 7; else if (cagr >= 10) growth += 5; else if (cagr >= 5) growth += 3; else growth += 1;
    } else growth += 3;

    // Income (0-15): dividend yield + payout sustainability
    let income = 0;
    if (div > 0 && price > 0) {
      const dy = (div / price) * 100;
      if (dy >= 4) income += 9; else if (dy >= 2.5) income += 10; else if (dy >= 1.5) income += 7; else income += 4;
      const payout = eps > 0 ? (div / eps) * 100 : -1;
      if (payout > 0 && payout <= 50) income += 5; else if (payout > 0 && payout <= 75) income += 3; else income += 1;
    } else income += 3;

    // Quality (0-20): ROE, earnings yield, DuPont
    let quality = 0;
    const ey = (eps / price) * 100;
    if (ey >= 8) quality += 8; else if (ey >= 6) quality += 6; else if (ey >= 4) quality += 4; else quality += 2;
    if (dupontResults) {
      if (dupontResults.roe >= 20) quality += 8; else if (dupontResults.roe >= 15) quality += 6; else if (dupontResults.roe >= 10) quality += 4; else quality += 2;
      if (dupontResults.equityMultiplier <= 2.5) quality += 4; else if (dupontResults.equityMultiplier <= 4) quality += 2;
    } else {
      if (bvps > 0) { const simROE = (eps / bvps) * 100; if (simROE >= 15) quality += 6; else if (simROE >= 10) quality += 4; else quality += 2; }
      else quality += 3;
      quality += 2;
    }

    // Safety (0-10): Monte Carlo conviction + valuation spread
    let safety = 0;
    if (mcResults) {
      if (mcResults.underPct >= 75) safety += 7; else if (mcResults.underPct >= 55) safety += 5; else if (mcResults.underPct >= 40) safety += 3; else safety += 1;
      const spread = (mcResults.p90 - mcResults.p10) / mcResults.median;
      if (spread < 1) safety += 3; else if (spread < 2) safety += 2; else safety += 1;
    } else {
      if (calcResults.mos > 20) safety += 6; else if (calcResults.mos > 0) safety += 4; else safety += 2;
      safety += 2;
    }

    const total = value + growth + income + quality + safety;
    const grade = total >= 85 ? "A+" : total >= 78 ? "A" : total >= 70 ? "A-" : total >= 65 ? "B+" : total >= 58 ? "B" : total >= 50 ? "B-" : total >= 42 ? "C+" : total >= 35 ? "C" : total >= 25 ? "D" : "F";
    const color = total >= 70 ? "emerald" : total >= 50 ? "blue" : total >= 35 ? "amber" : "red";

    return {
      total, grade, color,
      dimensions: [
        { label: "Value", score: value, max: 30 },
        { label: "Growth", score: growth, max: 25 },
        { label: "Income", score: income, max: 15 },
        { label: "Quality", score: quality, max: 20 },
        { label: "Safety", score: safety, max: 10 },
      ],
    };
  }, [calcInputs, calcResults, scenarioResults, dupontResults, mcResults]);

  /* ── Fair Value Convergence Map ─────────────── */
  const consensusMap = useMemo(() => {
    const price = parseFloat(calcInputs.price) || 0;
    const eps = parseFloat(calcInputs.eps) || 0;
    if (!price) return null;

    const methods = [];
    if (calcResults.graham) methods.push({ label: "Graham", value: calcResults.graham, cat: "classic" });
    if (calcResults.grahamGrowth && isFinite(calcResults.grahamGrowth) && calcResults.grahamGrowth > 0)
      methods.push({ label: "Graham G", value: calcResults.grahamGrowth, cat: "classic" });
    if (calcResults.dcf) methods.push({ label: "DCF", value: calcResults.dcf, cat: "dcf" });
    if (calcResults.ddm) methods.push({ label: "DDM", value: calcResults.ddm, cat: "dcf" });
    if (mcResults) {
      methods.push({ label: "MC Med", value: mcResults.median, cat: "mc" });
      methods.push({ label: "MC P25", value: mcResults.p25, cat: "mc", faded: true });
      methods.push({ label: "MC P75", value: mcResults.p75, cat: "mc", faded: true });
    }
    if (scenarioResults) {
      scenarioResults.forEach(s => {
        if (s.targetPrice > 0 && isFinite(s.targetPrice))
          methods.push({ label: `Yr${s.year}`, value: s.targetPrice, cat: "scenario" });
      });
    }
    if (calcResults.avg) methods.push({ label: "Avg", value: calcResults.avg, cat: "avg" });

    if (methods.length < 2) return null;

    const vals = methods.map(m => m.value);
    const lo = Math.min(...vals, price) * 0.88;
    const hi = Math.max(...vals, price) * 1.12;
    const range = hi - lo;
    if (range <= 0) return null;

    const positioned = methods.map(m => ({
      ...m,
      pct: ((m.value - lo) / range) * 100,
      above: m.value >= price,
    }));
    const pricePct = ((price - lo) / range) * 100;

    // Reverse DCF: P = EPS(1+g)/(r-g) → g = (P·r - EPS)/(P + EPS)
    const r = (parseFloat(calcInputs.discount) || 0) / 100;
    let impliedGrowth = null;
    if (eps > 0 && r > 0) {
      const g = (price * r - eps) / (price + eps);
      if (g > -0.1 && g < 0.5) impliedGrowth = g * 100;
    }

    const bullish = methods.filter(m => m.value > price).length;
    const bullPct = (bullish / methods.length) * 100;
    const sorted = [...vals].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    const medianVal = sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
    const spread = ((Math.max(...vals) - Math.min(...vals)) / medianVal) * 100;
    const conviction = spread < 30 ? "High" : spread < 60 ? "Medium" : "Low";

    return { positioned, pricePct, lo, hi, impliedGrowth, bullPct, conviction, bullish, total: methods.length };
  }, [calcInputs, calcResults, mcResults, scenarioResults]);

  /* ── Zoom helpers ──────────────────────────── */
  const zoomIn = () => setZoom(z => Math.min(+(z + 0.1).toFixed(1), 2));
  const zoomOut = () => setZoom(z => Math.max(+(z - 0.1).toFixed(1), 0.5));
  const zoomReset = () => setZoom(1);

  /* ── Tab helper ────────────────────────────── */
  const openTab = (tab) => { setActiveTab(tab); setPanelOpen(true); };

  /* ── Load notes from localStorage ──────────── */
  useEffect(() => {
    if (!notesKey) { setNotes(""); setLastSaved(null); return; }
    try {
      const saved = localStorage.getItem(`report_notes_${notesKey}`);
      if (saved) {
        setNotes(saved);
        setLastSaved(new Date());
      } else {
        setNotes("");
        setLastSaved(null);
      }
    } catch { setNotes(""); setLastSaved(null); }
    notesModified.current = false;
  }, [notesKey]);

  /* ── Auto-save notes (500ms debounce) ──────── */
  useEffect(() => {
    if (!notesKey || !notesModified.current) return;
    const timeout = setTimeout(() => {
      try {
        localStorage.setItem(`report_notes_${notesKey}`, notes);
        setLastSaved(new Date());
      } catch {}
    }, 500);
    return () => clearTimeout(timeout);
  }, [notes, notesKey]);

  /* ── Notes textarea focus ──────────────────── */
  useEffect(() => {
    if (activeTab === "notes" && panelOpen && notesRef.current) {
      const t = setTimeout(() => notesRef.current?.focus(), 300);
      return () => clearTimeout(t);
    }
  }, [activeTab, panelOpen]);

  /* ── Keyboard shortcuts ────────────────────── */
  useEffect(() => {
    const handler = (e) => {
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      switch (e.key) {
        case "1": e.preventDefault(); setActiveTab("sources"); setPanelOpen(true); break;
        case "2": e.preventDefault(); setActiveTab("notes"); setPanelOpen(true); break;
        case "3": e.preventDefault(); setActiveTab("tools"); setPanelOpen(true); break;
        case "4": e.preventDefault(); setActiveTab("calc"); setPanelOpen(true); break;
        case "q": case "Q": e.preventDefault(); navigate("/Query"); break;
        case "Escape":
          if (shortcutsOpen) setShortcutsOpen(false);
          else if (isFullscreen) setIsFullscreen(false);
          else setPanelOpen(false);
          break;
        case "+": case "=": setZoom(z => Math.min(+(z + 0.1).toFixed(1), 2)); break;
        case "-": setZoom(z => Math.max(+(z - 0.1).toFixed(1), 0.5)); break;
        case "0": setZoom(1); break;
        case "f": case "F": setIsFullscreen(f => !f); break;
        case "p": case "P": if (url) window.open(url, "_blank"); break;
        case "?": e.preventDefault(); setShortcutsOpen(s => !s); break;
        default: break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [url, shortcutsOpen, isFullscreen]);

  /* ── Notes handlers ────────────────────────── */
  const handleNotesChange = (e) => {
    setNotes(e.target.value);
    notesModified.current = true;
  };

  const insertTemplate = (text) => {
    if (notesRef.current) {
      const el = notesRef.current;
      const start = el.selectionStart;
      const prefix = notes.length > 0 && !notes.endsWith("\n") ? "\n\n" : "";
      const newText = notes.slice(0, start) + prefix + text + notes.slice(start);
      setNotes(newText);
      notesModified.current = true;
      setTimeout(() => {
        el.selectionStart = el.selectionEnd = start + prefix.length + text.length;
        el.focus();
      }, 0);
    } else {
      setNotes(prev => (prev ? prev + "\n\n" : "") + text);
      notesModified.current = true;
    }
  };

  const clearNotes = () => {
    setNotes("");
    notesModified.current = true;
    if (notesKey) {
      try { localStorage.removeItem(`report_notes_${notesKey}`); } catch {}
    }
    setLastSaved(null);
  };

  const copyNotes = () => {
    navigator.clipboard.writeText(notes).then(() => {
      toast({ title: "Notes copied", description: "Copied to clipboard" });
    }).catch(() => {});
  };

  /* ── Action handlers ───────────────────────── */
  const handlePrint = () => {
    if (!url) return;
    window.open(url, "_blank");
  };

  const handleShare = () => {
    navigator.clipboard.writeText(window.location.href).then(() => {
      toast({ title: "Link copied", description: "Report URL copied to clipboard" });
    }).catch(() => {});
  };

  /* ── Filtered sources ──────────────────────── */
  const { webSources, edinetSources, allWebCount, allEdinetCount } = useMemo(() => {
    const q = sourceFilter.trim().toLowerCase();
    let web = [], edinet = [], allWeb = 0, allEdinet = 0;
    for (const s of sources) {
      const isEdinet = s.type === "edinet";
      if (isEdinet) allEdinet++; else allWeb++;
      if (q && !((s.title || "").toLowerCase().includes(q) || (s.url || "").toLowerCase().includes(q) || (s.snippet || "").toLowerCase().includes(q))) continue;
      if (isEdinet) edinet.push(s); else web.push(s);
    }
    return { webSources: web, edinetSources: edinet, allWebCount: allWeb, allEdinetCount: allEdinet };
  }, [sources, sourceFilter]);
  const wordCount = notes.trim() ? notes.trim().split(/\s+/).length : 0;

  return (
    <div className="h-dvh flex flex-col bg-white text-[#0a0a0a] overflow-hidden">

      {/* ── Header ──────────────────────────────────────── */}
      <AnimatePresence>
        {!isFullscreen && (
          <motion.header
            initial={false}
            animate={{ height: 56, opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="shrink-0 bg-white/90 backdrop-blur-xl border-b border-black/[0.06] flex items-center px-5 gap-3 z-30 overflow-hidden"
          >
            {/* Left: Back + Company */}
            <button
              onClick={() => navigate("/", { state: { openContent: true } })}
              className="flex items-center gap-1.5 text-gray-300 hover:text-gray-500 transition-colors text-sm"
            >
              <ArrowLeft className="w-4 h-4" />
              <span className="hidden sm:inline text-[13px]">Back</span>
            </button>

            <div className="h-4 w-px bg-black/[0.04]" />

            <div className="flex items-center gap-2.5 min-w-0">
              {ticker && (
                <span className="px-2 py-0.5 rounded-md bg-[#de5f40]/10 text-[#de5f40] text-[11px] font-bold font-mono ring-1 ring-[#de5f40]/20 shrink-0">
                  {ticker}
                </span>
              )}
              <p className="text-[13px] text-gray-500 truncate font-medium">{companyName}</p>
            </div>

            <div className="flex-1" />

            {/* Center: Zoom controls */}
            <div className="hidden sm:flex items-center gap-0.5 px-1 py-0.5 rounded-xl bg-black/[0.02] ring-1 ring-black/[0.04]">
              <button onClick={zoomOut} className="w-6 h-6 rounded-lg flex items-center justify-center text-gray-300 hover:text-gray-500 hover:bg-black/[0.04] transition-all" title="Zoom out (-)">
                <ZoomOut className="w-3 h-3" />
              </button>
              <button onClick={zoomReset} className="px-2 py-0.5 rounded-lg text-[10px] font-mono text-gray-400 hover:text-gray-500 hover:bg-black/[0.04] transition-all min-w-[40px] text-center" title="Reset zoom (0)">
                {Math.round(zoom * 100)}%
              </button>
              <button onClick={zoomIn} className="w-6 h-6 rounded-lg flex items-center justify-center text-gray-300 hover:text-gray-500 hover:bg-black/[0.04] transition-all" title="Zoom in (+)">
                <ZoomIn className="w-3 h-3" />
              </button>
            </div>

            {/* Actions */}
            <div className="hidden sm:flex items-center gap-1">
              <button onClick={() => setIsFullscreen(true)} className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-300 hover:text-gray-400 hover:bg-black/[0.04] transition-all" title="Fullscreen (F)">
                <Maximize2 className="w-3.5 h-3.5" />
              </button>
              <button onClick={handlePrint} className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-300 hover:text-gray-400 hover:bg-black/[0.04] transition-all" title="Print (P)">
                <Printer className="w-3.5 h-3.5" />
              </button>
              {reportData?.pdf && (
                <a href={reportData.pdf} target="_blank" rel="noreferrer" className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-300 hover:text-gray-400 hover:bg-black/[0.04] transition-all" title="Download PDF">
                  <Download className="w-3.5 h-3.5" />
                </a>
              )}
              <button onClick={handleShare} className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-300 hover:text-gray-400 hover:bg-black/[0.04] transition-all" title="Share link">
                <Share2 className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="h-4 w-px bg-black/[0.04] hidden sm:block" />

            {/* Panel buttons */}
            <div className="flex items-center gap-1.5">
              {sources.length > 0 && (
                <button
                  onClick={() => openTab("sources")}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[11px] font-medium transition-all duration-200 ${
                    panelOpen && activeTab === "sources"
                      ? "bg-blue-500/15 text-blue-400 ring-1 ring-blue-500/25"
                      : "bg-black/[0.03] text-gray-400 hover:text-gray-500 hover:bg-black/[0.04] ring-1 ring-black/[0.06]"
                  }`}
                >
                  <BookOpen className="w-3 h-3" />
                  <span className="font-mono">{sources.length}</span>
                  <span className="hidden sm:inline">sources</span>
                </button>
              )}

              <button
                onClick={() => openTab("notes")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[11px] font-medium transition-all duration-200 ${
                  panelOpen && activeTab === "notes"
                    ? "bg-amber-500/15 text-amber-400 ring-1 ring-amber-500/25"
                    : "bg-black/[0.03] text-gray-400 hover:text-gray-500 hover:bg-black/[0.04] ring-1 ring-black/[0.06]"
                }`}
              >
                <PenLine className="w-3 h-3" />
                <span className="hidden sm:inline">Notes</span>
                {notes && <span className="w-1.5 h-1.5 rounded-full bg-amber-400/60" />}
              </button>

              {panelOpen && (
                <button
                  onClick={() => setPanelOpen(false)}
                  className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-300 hover:text-gray-400 hover:bg-black/[0.04] transition-all"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          </motion.header>
        )}
      </AnimatePresence>

      {/* Gradient accent line */}
      {!isFullscreen && <div className="h-px bg-gradient-to-r from-transparent via-black/[0.04] to-transparent shrink-0" />}

      {/* ── Fullscreen exit bar ──────────────────────────── */}
      <AnimatePresence>
        {isFullscreen && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.2 }}
            className="fixed top-3 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-4 py-2 rounded-2xl bg-black/70 backdrop-blur-xl border border-black/[0.08] shadow-2xl"
          >
            <button onClick={() => setIsFullscreen(false)} className="text-gray-400 hover:text-gray-500 transition">
              <Minimize2 className="w-3.5 h-3.5" />
            </button>
            <span className="text-[10px] text-gray-300">
              Press <kbd className="px-1.5 py-0.5 rounded-md bg-white/[0.08] text-gray-400 font-mono text-[9px] ring-1 ring-white/[0.06]">F</kbd> or <kbd className="px-1.5 py-0.5 rounded-md bg-white/[0.08] text-gray-400 font-mono text-[9px] ring-1 ring-white/[0.06]">Esc</kbd> to exit
            </span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Main layout ─────────────────────────────────── */}
      <div className="flex-1 flex overflow-hidden">

        {/* ── Report content ─────────────────────────── */}
        <main className="flex-1 overflow-hidden">
          {!url ? (
            <div className="flex items-center justify-center h-full text-gray-300 text-sm">
              No report URL provided.
            </div>
          ) : (
            <div className="h-full overflow-hidden">
              {isPdf ? (
                <div className="h-full overflow-auto">
                  <div style={zoom !== 1 ? { transform: `scale(${zoom})`, transformOrigin: "top left", width: `${100 / zoom}%`, height: `${100 / zoom}%` } : undefined}>
                    <object data={url} type="application/pdf" className="w-full h-full" style={{ background: "white", minHeight: "100vh" }}>
                      <p className="p-6 text-gray-800">
                        PDF preview unavailable. <a className="text-blue-600 underline" href={url} target="_blank" rel="noreferrer">Open in new tab</a>.
                      </p>
                    </object>
                  </div>
                </div>
              ) : (
                <div className="h-full">
                  <iframe
                    src={url}
                    title={title}
                    className="bg-white border-0"
                    style={zoom !== 1
                      ? { transform: `scale(${zoom})`, transformOrigin: "top left", width: `${100 / zoom}%`, height: `${100 / zoom}%` }
                      : { width: "100%", height: "100%" }
                    }
                  />
                </div>
              )}
            </div>
          )}
        </main>

        {/* ── Right panel ────────────────────────────── */}
        <AnimatePresence>
          {panelOpen && (
            <motion.div
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 440, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
              className="shrink-0 border-l border-black/[0.05] bg-[#f8f8fa] flex flex-col overflow-hidden h-full"
              style={{ maxWidth: "85vw" }}
            >
              <div style={{ width: "min(440px, 85vw)" }} className="flex flex-col h-full">

                {/* ── Tab bar ───────────────────────── */}
                <div className="shrink-0 px-5 pt-4 pb-0">
                  <div className="flex gap-0.5 p-[3px] rounded-[14px] bg-black/[0.03]">
                    {[
                      { id: "sources", label: "Sources", icon: BookOpen, badge: sources.length > 0 ? sources.length : null, badgeColor: "bg-blue-500/12 text-blue-500" },
                      { id: "notes", label: "Notes", icon: PenLine, dot: !!notes },
                      { id: "tools", label: "Tools", icon: Zap, badge: 18, badgeColor: "bg-purple-500/12 text-purple-500" },
                      { id: "calc", label: "Calc", icon: Calculator },
                    ].map(tab => {
                      const Icon = tab.icon;
                      const isActive = activeTab === tab.id;
                      return (
                        <button
                          key={tab.id}
                          onClick={() => setActiveTab(tab.id)}
                          className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-[9px] rounded-[11px] text-[12px] font-medium transition-all duration-300 ${
                            isActive
                              ? "bg-white text-gray-800 shadow-[0_1px_3px_rgba(0,0,0,0.06),0_0_0_1px_rgba(0,0,0,0.04)]"
                              : "text-gray-400 hover:text-gray-500"
                          }`}
                        >
                          <Icon className="w-3.5 h-3.5" />
                          {tab.label}
                          {tab.badge != null && (
                            <span className={`font-mono text-[9px] px-1.5 py-px rounded-md font-semibold ${
                              isActive ? tab.badgeColor : "bg-black/[0.04] text-gray-300"
                            }`}>
                              {tab.badge}
                            </span>
                          )}
                          {tab.dot && (
                            <span className="w-[5px] h-[5px] rounded-full bg-amber-400/60" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                  <button
                    onClick={() => navigate("/Query", { state: { company: companyName } })}
                    className="flex items-center justify-center gap-1.5 mt-2 mx-auto px-4 py-1.5 rounded-xl text-[10px] font-medium text-gray-300 hover:text-gray-600 hover:bg-black/[0.03] ring-1 ring-transparent hover:ring-black/[0.06] transition-all duration-200"
                  >
                    <Terminal className="w-3 h-3" />
                    Open Query Mode
                    <ExternalLink className="w-2.5 h-2.5 opacity-40" />
                  </button>
                </div>

                <div className="h-px bg-gradient-to-r from-transparent via-black/[0.05] to-transparent mx-5 mt-2" />

                {/* ── Tab content ────────────────────── */}
                {activeTab === "calc" ? (

                  /* ── Calc tab (Valuation Lab) ──────── */
                  <div className="flex-1 overflow-y-auto px-5 py-4 viewer-scroll space-y-5">
                    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>

                      {/* Header */}
                      <div className="text-center mb-5">
                        <div className="w-9 h-9 rounded-2xl bg-gradient-to-b from-black/[0.03] to-black/[0.06] flex items-center justify-center mx-auto ring-1 ring-black/[0.04] mb-2">
                          <Calculator className="w-4 h-4 text-gray-400" />
                        </div>
                        <p className="text-[14px] font-semibold text-gray-800 tracking-[-0.02em]">Valuation Lab</p>
                        <p className="text-[11px] text-gray-300 mt-0.5">Punch in numbers from the report — get instant fair value</p>
                      </div>

                      {/* Inputs */}
                      <div className="space-y-2.5">
                        <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-gray-300/80 px-1">Inputs</p>
                        <div className="grid grid-cols-2 gap-2">
                          {[
                            { key: "eps", label: "EPS (¥)", placeholder: "150" },
                            { key: "bvps", label: "Book Value/Share (¥)", placeholder: "800" },
                            { key: "price", label: "Current Price (¥)", placeholder: "2500" },
                            { key: "dividend", label: "Dividend/Share (¥)", placeholder: "50" },
                          ].map(f => (
                            <div key={f.key}>
                              <label className="text-[10px] text-gray-400 font-medium mb-1 block">{f.label}</label>
                              <input
                                type="number"
                                value={calcInputs[f.key]}
                                onChange={e => updateCalc(f.key, e.target.value)}
                                placeholder={f.placeholder}
                                className="w-full bg-white border border-black/[0.06] rounded-lg px-3 py-2 text-[13px] text-gray-700 font-mono placeholder-gray-200 outline-none focus:border-black/[0.15] focus:ring-1 focus:ring-black/[0.04] transition-all tabular-nums"
                              />
                            </div>
                          ))}
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          {[
                            { key: "growth", label: "Growth Rate (%)", min: 0, max: 25, step: 0.5 },
                            { key: "discount", label: "Discount Rate (%)", min: 3, max: 20, step: 0.5 },
                          ].map(f => (
                            <div key={f.key}>
                              <label className="text-[10px] text-gray-400 font-medium mb-1 flex items-center justify-between">
                                {f.label}
                                <span className="text-[11px] font-mono text-gray-600">{calcInputs[f.key]}%</span>
                              </label>
                              <input
                                type="range"
                                min={f.min}
                                max={f.max}
                                step={f.step}
                                value={calcInputs[f.key]}
                                onChange={e => updateCalc(f.key, e.target.value)}
                                className="w-full h-1.5 bg-black/[0.04] rounded-full appearance-none cursor-pointer accent-[#0a0a0a]"
                              />
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Key Ratios */}
                      {(parseFloat(calcInputs.eps) > 0 || parseFloat(calcInputs.dividend) > 0) && parseFloat(calcInputs.price) > 0 && (
                        <div className="flex flex-wrap gap-2">
                          {(() => {
                            const eps = parseFloat(calcInputs.eps) || 0;
                            const bvps = parseFloat(calcInputs.bvps) || 0;
                            const price = parseFloat(calcInputs.price);
                            const div = parseFloat(calcInputs.dividend) || 0;
                            const pe = eps > 0 ? price / eps : null;
                            const pb = bvps > 0 ? price / bvps : null;
                            const roe = eps > 0 && bvps > 0 ? (eps / bvps) * 100 : null;
                            const dy = div > 0 ? (div / price) * 100 : null;
                            const payout = eps > 0 && div > 0 ? (div / eps) * 100 : null;
                            const growthPct = parseFloat(calcInputs.growth) || 0;
                            const peg = pe !== null && pe > 0 && growthPct > 0 ? pe / growthPct : null;
                            return [
                              pe !== null && { label: "P/E", value: pe.toFixed(1) + "x", color: pe > 0 && pe < 12 ? "text-emerald-600" : pe > 25 ? "text-red-400" : undefined, tip: "Price-to-Earnings — below 12 is cheap, above 25 is expensive" },
                              pb !== null && { label: "P/B", value: pb.toFixed(2) + "x", color: pb < 1.0 ? "text-emerald-600" : pb > 3 ? "text-amber-600" : undefined, tip: "Price-to-Book — below 1.0 means trading below liquidation value" },
                              peg !== null && { label: "PEG", value: peg.toFixed(2) + "x", color: peg > 0 && peg < 1 ? "text-emerald-600" : peg > 2 ? "text-red-400" : undefined, tip: "PEG Ratio — P/E divided by growth rate. Below 1.0 = undervalued for its growth" },
                              roe !== null && { label: "ROE", value: roe.toFixed(1) + "%", color: roe >= 15 ? "text-emerald-600" : roe < 8 ? "text-amber-600" : undefined, tip: "Return on Equity — above 15% is excellent, below 8% is weak" },
                              dy !== null && { label: "Div Yield", value: dy.toFixed(1) + "%", color: dy >= 3 ? "text-emerald-600" : undefined, tip: "Annual dividend as % of share price — 2.5–4% is the sweet spot" },
                              payout !== null && { label: "Payout", value: payout.toFixed(1) + "%", color: payout > 100 ? "text-red-400" : payout > 80 ? "text-amber-600" : payout <= 50 ? "text-emerald-600" : undefined, tip: "Dividend as % of earnings — below 50% is sustainable, above 100% is unsustainable" },
                            ].filter(Boolean);
                          })().map(r => (
                            <div key={r.label} className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-white ring-1 ${r.color === "text-red-400" ? "ring-red-200/40" : "ring-black/[0.04]"} cursor-default`} title={r.tip}>
                              <span className="text-[9px] text-gray-300 font-medium uppercase tracking-wider">{r.label}</span>
                              <span className={`text-[12px] font-semibold font-mono tabular-nums ${r.color || "text-gray-700"}`}>{r.value}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {parseFloat(calcInputs.eps) > 0 && parseFloat(calcInputs.dividend) > 0 &&
                        (parseFloat(calcInputs.dividend) / parseFloat(calcInputs.eps)) > 1 && (
                        <p className="text-[9px] text-red-400 font-medium px-1 -mt-1">
                          Payout exceeds earnings — dividend may not be sustainable
                        </p>
                      )}

                      {/* Rate proximity warning */}
                      {parseFloat(calcInputs.growth) > 0 && parseFloat(calcInputs.discount) > 0 &&
                        Math.abs(parseFloat(calcInputs.discount) - parseFloat(calcInputs.growth)) < 1.5 &&
                        parseFloat(calcInputs.discount) > parseFloat(calcInputs.growth) && (
                        <p className="text-[9px] text-amber-500 font-medium px-1 -mt-1">
                          Discount rate ({calcInputs.discount}%) is very close to growth ({calcInputs.growth}%) — DCF values may be extreme
                        </p>
                      )}

                      {/* Valuation Models */}
                      {(calcResults.graham || calcResults.dcf || calcResults.grahamGrowth || calcResults.ddm) && (
                        <div className="space-y-2.5">
                          <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-gray-300/80 px-1">Fair Value Estimates</p>
                          <div className="grid grid-cols-2 gap-2">
                            {[
                              { label: "Graham Number", sublabel: "sqrt(22.5 × EPS × BVPS)", value: calcResults.graham, tip: "Ben Graham's classic intrinsic value — assumes P/E of 15 and P/B of 1.5" },
                              { label: "Graham Growth", sublabel: "EPS × (8.5 + 2g) × 4.4/Y", value: calcResults.grahamGrowth, tip: "Growth-adjusted Graham formula — scales with earnings growth rate and bond yield" },
                              { label: "DCF Perpetuity", sublabel: "EPS(1+g) / (r−g)", value: calcResults.dcf, tip: "Gordon Growth model for earnings — assumes perpetual growth at constant rate" },
                              { label: "Dividend Model", sublabel: "D(1+g) / (r−g)", value: calcResults.ddm, tip: "Dividend Discount Model — values the stock by its future dividend stream" },
                            ].map(m => {
                              if (!m.value || !isFinite(m.value) || m.value <= 0) return null;
                              const price = parseFloat(calcInputs.price) || 0;
                              const diff = price > 0 ? ((m.value - price) / price) * 100 : null;
                              const isUnder = diff !== null && diff > 0;
                              return (
                                <div key={m.label} className="bg-white rounded-xl p-3 ring-1 ring-black/[0.04] hover:ring-black/[0.08] hover:shadow-sm space-y-1 transition-all duration-200" title={m.tip}>
                                  <p className="text-[10px] text-gray-400 font-medium leading-tight">{m.label}</p>
                                  <p className="text-[9px] text-gray-300 font-mono">{m.sublabel}</p>
                                  <p className="text-[18px] font-semibold text-gray-800 tabular-nums tracking-tight">
                                    ¥{Math.round(m.value).toLocaleString()}
                                  </p>
                                  {diff !== null && (
                                    <p className={`text-[11px] font-mono font-medium ${isUnder ? "text-emerald-500" : "text-red-400"}`}>
                                      {isUnder ? "+" : ""}{diff.toFixed(1)}% vs current
                                    </p>
                                  )}
                                </div>
                              );
                            }).filter(Boolean)}
                          </div>
                        </div>
                      )}

                      {/* Margin of Safety */}
                      {calcResults.avg && parseFloat(calcInputs.price) > 0 && (
                        <div className="space-y-2">
                          <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-gray-300/80 px-1">Margin of Safety</p>
                          <div className="bg-white rounded-xl p-4 ring-1 ring-black/[0.04] hover:ring-black/[0.08] hover:shadow-sm transition-all duration-200">
                            <div className="flex items-baseline justify-between mb-2">
                              <span className="text-[11px] text-gray-400">Avg fair value</span>
                              <span className="text-[15px] font-semibold text-gray-800 tabular-nums">¥{Math.round(calcResults.avg).toLocaleString()}</span>
                            </div>
                            <div className="h-2 bg-black/[0.04] rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full transition-all duration-500 ${calcResults.mos >= 20 ? "bg-emerald-400" : Math.abs(calcResults.mos) < 0.05 ? "bg-amber-400" : calcResults.mos >= 0 ? "bg-amber-400" : "bg-red-400"}`}
                                style={{ width: `${Math.max(0, Math.min(100, 50 + calcResults.mos * 0.5))}%` }}
                              />
                            </div>
                            <div className="flex items-baseline justify-between mt-2">
                              <span className={`text-[13px] font-mono font-semibold ${calcResults.mos >= 20 ? "text-emerald-500" : Math.abs(calcResults.mos) < 0.05 ? "text-amber-500" : calcResults.mos >= 0 ? "text-amber-500" : "text-red-400"}`}>
                                {Math.abs(calcResults.mos) < 0.05 ? "Fairly valued" : calcResults.mos > 0 ? `${calcResults.mos.toFixed(1)}% undervalued` : `${Math.abs(calcResults.mos).toFixed(1)}% overvalued`}
                              </span>
                              <span className="text-[10px] text-gray-300">
                                {calcResults.mos >= 30 ? "Strong buy zone" : calcResults.mos >= 15 ? "Attractive" : Math.abs(calcResults.mos) < 0.05 ? "Fair" : calcResults.mos >= 0 ? "Fair" : calcResults.mos >= -15 ? "Stretched" : "Expensive"}
                              </span>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Earnings Yield */}
                      {calcResults.earningsYield && (
                        <div className="bg-white rounded-xl p-3 ring-1 ring-black/[0.04] hover:ring-black/[0.08] hover:shadow-sm transition-all duration-200">
                          <div className="flex items-center justify-between">
                            <div>
                              <p className="text-[10px] text-gray-400 font-medium">Earnings Yield</p>
                              <p className="text-[9px] text-gray-300">EPS / Price (inverse P/E)</p>
                            </div>
                            <p className="text-[16px] font-semibold text-gray-800 tabular-nums font-mono">{calcResults.earningsYield.toFixed(1)}%</p>
                          </div>
                          {parseFloat(calcInputs.discount) > 0 && (
                            <p className={`text-[9px] mt-1.5 font-medium ${calcResults.earningsYield > parseFloat(calcInputs.discount) ? "text-emerald-500" : "text-amber-500"}`}>
                              {calcResults.earningsYield > parseFloat(calcInputs.discount)
                                ? `Exceeds ${calcInputs.discount}% discount rate — earnings alone justify the price`
                                : `Below ${calcInputs.discount}% discount rate — needs growth to justify`}
                            </p>
                          )}
                        </div>
                      )}

                      {/* ── Investment Scorecard ────────── */}
                      {scorecard && (
                        <div className="space-y-3">
                          <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-gray-300/80 px-1">Investment Scorecard</p>
                          <div className="bg-white rounded-xl p-4 ring-1 ring-black/[0.04] hover:ring-black/[0.08] hover:shadow-sm transition-all duration-200">
                            {/* Score circle + grade */}
                            <div className="flex items-center gap-5">
                              <div className="relative w-[72px] h-[72px] shrink-0">
                                <svg viewBox="0 0 72 72" className="w-full h-full -rotate-90">
                                  <circle cx="36" cy="36" r="30" fill="none" stroke="rgba(0,0,0,0.04)" strokeWidth="6" />
                                  <circle
                                    cx="36" cy="36" r="30" fill="none"
                                    strokeWidth="6"
                                    strokeLinecap="round"
                                    strokeDasharray={`${(scorecard.total / 100) * 188.5} 188.5`}
                                    className={scorecard.color === "emerald" ? "stroke-emerald-400" : scorecard.color === "blue" ? "stroke-blue-400" : scorecard.color === "amber" ? "stroke-amber-400" : "stroke-red-400"}
                                  />
                                </svg>
                                <div className="absolute inset-0 flex items-center justify-center">
                                  <span className="text-[20px] font-bold text-gray-800 tabular-nums font-mono">{scorecard.total}</span>
                                </div>
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-baseline gap-2 mb-1.5">
                                  <span className={`text-[22px] font-bold ${scorecard.color === "emerald" ? "text-emerald-500" : scorecard.color === "blue" ? "text-blue-500" : scorecard.color === "amber" ? "text-amber-500" : "text-red-400"}`}>
                                    {scorecard.grade}
                                  </span>
                                  <span className="text-[10px] text-gray-300">/ 100</span>
                                </div>
                                <p className="text-[10px] text-gray-400 leading-relaxed">
                                  {scorecard.total >= 70 ? "Strong investment profile — multiple factors align" :
                                   scorecard.total >= 50 ? "Decent profile — some strengths, review weaknesses" :
                                   scorecard.total >= 35 ? "Mixed signals — proceed with caution" :
                                   "Weak profile — significant concerns"}
                                </p>
                              </div>
                            </div>
                            {/* Dimension bars */}
                            <div className="mt-4 space-y-2">
                              {scorecard.dimensions.map(d => {
                                const pct = (d.score / d.max) * 100;
                                const tips = { Value: "P/E + P/B multiples", Growth: "Revenue growth + scenario CAGR", Income: "Dividend yield + payout sustainability", Quality: "Earnings yield + ROE + leverage", Safety: "Monte Carlo conviction + valuation spread" };
                                return (
                                  <div key={d.label} className="flex items-center gap-2 cursor-default" title={tips[d.label]}>
                                    <span className="text-[9px] text-gray-400 font-medium w-[46px] text-right shrink-0">{d.label}</span>
                                    <div className="flex-1 h-[6px] bg-black/[0.04] rounded-full overflow-hidden">
                                      <div
                                        className={`h-full rounded-full transition-all duration-700 ${pct >= 70 ? "bg-emerald-400" : pct >= 45 ? "bg-blue-400" : pct >= 30 ? "bg-amber-400" : "bg-red-300"}`}
                                        style={{ width: `${pct}%` }}
                                      />
                                    </div>
                                    <span className="text-[9px] font-mono text-gray-400 tabular-nums w-[32px] shrink-0">{d.score}/{d.max}</span>
                                  </div>
                                );
                              })}
                            </div>
                            {/* Weakest + strongest hint */}
                            {(() => {
                              const sorted = [...scorecard.dimensions].sort((a, b) => (a.score / a.max) - (b.score / b.max));
                              const weakest = sorted[0];
                              const strongest = sorted[sorted.length - 1];
                              return (
                                <p className="text-[9px] text-gray-300 mt-2 text-center">
                                  Strongest: <span className="text-emerald-500 font-medium">{strongest.label}</span> · Weakest: <span className="text-amber-500 font-medium">{weakest.label}</span>
                                </p>
                              );
                            })()}
                          </div>
                        </div>
                      )}

                      {/* Sensitivity Grid */}
                      {parseFloat(calcInputs.eps) > 0 && (
                        <div className="space-y-2">
                          <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-gray-300/80 px-1">DCF Sensitivity (¥ fair value)</p>
                          <div className="overflow-x-auto rounded-xl ring-1 ring-black/[0.06] bg-white">
                            <table className="w-full text-[10px]">
                              <thead>
                                <tr className="bg-black/[0.02]">
                                  <th className="px-2 py-1.5 text-left text-gray-300 font-medium">WACC \ g</th>
                                  {calcResults.growthRates.map(gr => (
                                    <th key={gr} className={`px-2 py-1.5 text-center font-mono ${gr === Math.round(parseFloat(calcInputs.growth) || 8) ? "text-gray-700 font-bold" : "text-gray-300"}`}>{gr}%</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {calcResults.grid.map((row, ri) => (
                                  <tr key={ri} className="border-t border-black/[0.04]">
                                    <td className={`px-2 py-1.5 font-mono ${calcResults.discountRates[ri] === Math.round(parseFloat(calcInputs.discount) || 10) ? "text-gray-700 font-bold" : "text-gray-300"}`}>
                                      {calcResults.discountRates[ri]}%
                                    </td>
                                    {row.map((val, ci) => {
                                      const gp = calcResults.gridPrice;
                                      const isBase = calcResults.growthRates[ci] === Math.round(parseFloat(calcInputs.growth) || 8) && calcResults.discountRates[ri] === Math.round(parseFloat(calcInputs.discount) || 10);
                                      const isUnder = val && gp > 0 && val > gp * 1.2;
                                      const isOver = val && gp > 0 && val < gp * 0.8;
                                      const isMarketImplied = val && gp > 0 && !isBase && Math.abs(val - gp) / gp <= 0.1;
                                      return (
                                        <td key={ci} className={`px-2 py-1.5 text-center font-mono tabular-nums ${
                                          isBase ? "bg-black/[0.06] font-bold text-gray-800 rounded" : isMarketImplied ? "text-gray-700 font-medium underline decoration-dotted decoration-gray-300 underline-offset-2" : isUnder ? "text-emerald-500" : isOver ? "text-red-400" : val ? "text-gray-400" : "text-gray-200"
                                        }`}>
                                          {val ? `¥${val.toLocaleString()}` : "—"}
                                        </td>
                                      );
                                    })}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                          {parseFloat(calcInputs.price) > 0 && (
                            <p className="text-[9px] text-gray-300 text-center">
                              Green = &gt;20% upside &middot; Red = &gt;20% downside &middot; <span className="underline decoration-dotted decoration-gray-400 underline-offset-2">Dotted</span> = near current price &middot; Bold = base case
                            </p>
                          )}
                        </div>
                      )}


                      {/* ── Scenario Modeler ────────────────── */}
                      <div className="border-t border-black/[0.06] pt-5 mt-2">
                        <div className="text-center mb-4">
                          <div className="w-9 h-9 rounded-2xl bg-gradient-to-b from-black/[0.03] to-black/[0.06] flex items-center justify-center mx-auto ring-1 ring-black/[0.04] mb-2">
                            <TrendingUp className="w-4 h-4 text-gray-400" />
                          </div>
                          <p className="text-[13px] font-semibold text-gray-800 tracking-[-0.02em]">Scenario Modeler</p>
                          <p className="text-[10px] text-gray-300 mt-0.5">Project future stock price under different assumptions</p>
                        </div>

                        <div className="space-y-2.5">
                          <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-gray-300/80 px-1">Company Data</p>
                          <div className="grid grid-cols-2 gap-2">
                            {[
                              { key: "revenue", label: "Revenue (¥M)", placeholder: "50000" },
                              { key: "opMargin", label: "OP Margin (%)", placeholder: "12" },
                              { key: "shares", label: "Shares Outstanding (M)", placeholder: "100" },
                              { key: "taxRate", label: "Tax Rate (%)", placeholder: "30" },
                            ].map(f => (
                              <div key={f.key}>
                                <label className="text-[10px] text-gray-400 font-medium mb-1 block">{f.label}</label>
                                <input
                                  type="number"
                                  value={scenarioInputs[f.key]}
                                  onChange={e => updateScenario(f.key, e.target.value)}
                                  placeholder={f.placeholder}
                                  className="w-full bg-white border border-black/[0.06] rounded-lg px-3 py-2 text-[13px] text-gray-700 font-mono placeholder-gray-200 outline-none focus:border-black/[0.15] focus:ring-1 focus:ring-black/[0.04] transition-all tabular-nums"
                                />
                              </div>
                            ))}
                          </div>
                          <div className="space-y-2">
                            {[
                              { key: "revGrowth", label: "Revenue CAGR (%)", min: -10, max: 30, step: 1 },
                              { key: "marginDelta", label: "Annual Margin Change (pp)", min: -3, max: 3, step: 0.25 },
                              { key: "terminalPE", label: "Terminal P/E Multiple", min: 5, max: 40, step: 1 },
                            ].map(f => (
                              <div key={f.key}>
                                <label className="text-[10px] text-gray-400 font-medium mb-1 flex items-center justify-between">
                                  {f.label}
                                  <span className="text-[11px] font-mono text-gray-600">{scenarioInputs[f.key]}{f.key !== "terminalPE" ? (f.key === "marginDelta" ? "pp" : "%") : "x"}</span>
                                </label>
                                <input
                                  type="range"
                                  min={f.min}
                                  max={f.max}
                                  step={f.step}
                                  value={scenarioInputs[f.key]}
                                  onChange={e => updateScenario(f.key, e.target.value)}
                                  className="w-full h-1.5 bg-black/[0.04] rounded-full appearance-none cursor-pointer accent-[#0a0a0a]"
                                />
                              </div>
                            ))}
                          </div>
                        </div>

                        {scenarioResults && (
                          <div className="space-y-2.5 mt-4">
                            <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-gray-300/80 px-1">Projected Returns</p>
                            <div className="overflow-x-auto rounded-xl ring-1 ring-black/[0.06] bg-white">
                              <table className="w-full text-[10px]">
                                <thead>
                                  <tr className="bg-black/[0.02]">
                                    <th className="px-2 py-1.5 text-left text-gray-300 font-medium">Year</th>
                                    <th className="px-2 py-1.5 text-right text-gray-300 font-medium">Revenue</th>
                                    <th className="px-2 py-1.5 text-right text-gray-300 font-medium">Margin</th>
                                    <th className="px-2 py-1.5 text-right text-gray-300 font-medium">EPS</th>
                                    <th className="px-2 py-1.5 text-right text-gray-300 font-medium">Target</th>
                                    <th className="px-2 py-1.5 text-right text-gray-300 font-medium">CAGR</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {/* Current baseline row */}
                                  {parseFloat(scenarioInputs.revenue) > 0 && (
                                    <tr className="border-t border-black/[0.04] bg-black/[0.02]">
                                      <td className="px-2 py-1.5 font-mono text-gray-300 text-[9px]">Now</td>
                                      <td className="px-2 py-1.5 text-right font-mono text-gray-300">¥{Math.round(parseFloat(scenarioInputs.revenue)).toLocaleString()}M</td>
                                      <td className="px-2 py-1.5 text-right font-mono text-gray-300">{scenarioInputs.opMargin}%</td>
                                      <td className="px-2 py-1.5 text-right font-mono text-gray-300">
                                        {(() => {
                                          const s = parseFloat(scenarioInputs.shares) || 0;
                                          const m = (parseFloat(scenarioInputs.opMargin) || 0) / 100;
                                          const txRaw = parseFloat(scenarioInputs.taxRate);
                                          const t = Math.max(0, Math.min(0.95, (isNaN(txRaw) ? 30 : txRaw) / 100));
                                          const r = parseFloat(scenarioInputs.revenue) || 0;
                                          return s > 0 && m > 0 ? `¥${Math.round(r * m * (1 - t) / s).toLocaleString()}` : "—";
                                        })()}
                                      </td>
                                      <td className="px-2 py-1.5 text-right font-mono text-gray-300">{parseFloat(calcInputs.price) > 0 ? `¥${parseFloat(calcInputs.price).toLocaleString()}` : "—"}</td>
                                      <td className="px-2 py-1.5 text-right font-mono text-gray-200">—</td>
                                    </tr>
                                  )}
                                  {scenarioResults.map(r => (
                                    <tr key={r.year} className="border-t border-black/[0.04]">
                                      <td className="px-2 py-1.5 font-mono text-gray-500">Yr {r.year}</td>
                                      <td className="px-2 py-1.5 text-right font-mono text-gray-400">¥{Math.round(r.revenue).toLocaleString()}M</td>
                                      <td className="px-2 py-1.5 text-right font-mono text-gray-400">{r.opMargin.toFixed(1)}%</td>
                                      <td className="px-2 py-1.5 text-right font-mono text-gray-600 font-medium">¥{Math.round(r.eps).toLocaleString()}</td>
                                      <td className="px-2 py-1.5 text-right font-mono font-medium text-gray-800">¥{Math.round(r.targetPrice).toLocaleString()}</td>
                                      <td className={`px-2 py-1.5 text-right font-mono font-medium ${r.cagr === null ? "text-gray-300" : r.cagr > 15 ? "text-emerald-500" : r.cagr > 0 ? "text-amber-500" : "text-red-400"}`}>
                                        {r.cagr !== null ? `${r.cagr > 0 ? "+" : ""}${r.cagr.toFixed(1)}%` : "—"}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                            {parseFloat(calcInputs.price) > 0 && scenarioResults[1]?.cagr !== null && (
                              <div className="bg-white rounded-xl p-3 ring-1 ring-black/[0.04] hover:ring-black/[0.08] hover:shadow-sm flex items-center justify-between transition-all duration-200">
                                <div>
                                  <p className="text-[10px] text-gray-400 font-medium">3-Year Implied CAGR</p>
                                  <p className="text-[9px] text-gray-300">From ¥{parseFloat(calcInputs.price).toLocaleString()} current price</p>
                                </div>
                                <p className={`text-[18px] font-semibold tabular-nums font-mono ${scenarioResults[1].cagr > 15 ? "text-emerald-500" : scenarioResults[1].cagr > 0 ? "text-amber-500" : "text-red-400"}`}>
                                  {scenarioResults[1].cagr > 0 ? "+" : ""}{scenarioResults[1].cagr.toFixed(1)}%
                                </p>
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                      {/* ── DuPont ROE Analysis ────────────── */}
                      <div className="border-t border-black/[0.06] pt-5 mt-2">
                        <div className="text-center mb-4">
                          <div className="w-9 h-9 rounded-2xl bg-gradient-to-b from-black/[0.03] to-black/[0.06] flex items-center justify-center mx-auto ring-1 ring-black/[0.04] mb-2">
                            <Layers className="w-4 h-4 text-gray-400" />
                          </div>
                          <p className="text-[13px] font-semibold text-gray-800 tracking-[-0.02em]">DuPont ROE Decomposition</p>
                          <p className="text-[10px] text-gray-300 mt-0.5">Break down return on equity into its 3 drivers</p>
                        </div>

                        <div className="space-y-2.5">
                          <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-gray-300/80 px-1">Financials (¥M)</p>
                          <div className="grid grid-cols-2 gap-2">
                            {[
                              { key: "revenue", label: "Revenue", placeholder: "50000" },
                              { key: "netIncome", label: "Net Income", placeholder: "6000" },
                              { key: "totalAssets", label: "Total Assets", placeholder: "80000" },
                              { key: "totalEquity", label: "Total Equity", placeholder: "40000" },
                            ].map(f => (
                              <div key={f.key}>
                                <label className="text-[10px] text-gray-400 font-medium mb-1 block">{f.label}</label>
                                <input
                                  type="number"
                                  value={dupontInputs[f.key]}
                                  onChange={e => updateDupont(f.key, e.target.value)}
                                  placeholder={f.placeholder}
                                  className="w-full bg-white border border-black/[0.06] rounded-lg px-3 py-2 text-[13px] text-gray-700 font-mono placeholder-gray-200 outline-none focus:border-black/[0.15] focus:ring-1 focus:ring-black/[0.04] transition-all tabular-nums"
                                />
                              </div>
                            ))}
                          </div>
                        </div>

                        {dupontResults && (
                          <div className="mt-4 space-y-3">
                            <div className="bg-white rounded-xl p-4 ring-1 ring-black/[0.04] hover:ring-black/[0.08] hover:shadow-sm transition-all duration-200">
                              <div className="flex items-center justify-center gap-2 text-[11px] text-gray-400 mb-3">
                                <span className="font-medium">Net Margin</span>
                                <span className="text-gray-200">×</span>
                                <span className="font-medium">Asset Turnover</span>
                                <span className="text-gray-200">×</span>
                                <span className="font-medium">Equity Multiplier</span>
                                <span className="text-gray-200">=</span>
                                <span className="font-semibold text-gray-600">ROE</span>
                              </div>
                              <div className="flex items-center justify-center gap-2 text-[15px] font-mono tabular-nums">
                                <span className="text-gray-700 font-semibold">{dupontResults.netMargin.toFixed(1)}%</span>
                                <span className="text-gray-200">×</span>
                                <span className="text-gray-700 font-semibold">{dupontResults.assetTurnover.toFixed(2)}x</span>
                                <span className="text-gray-200">×</span>
                                <span className="text-gray-700 font-semibold">{dupontResults.equityMultiplier.toFixed(2)}x</span>
                                <span className="text-gray-200">=</span>
                                <span className={`font-bold ${dupontResults.roe >= 15 ? "text-emerald-500" : dupontResults.roe >= 8 ? "text-amber-500" : "text-red-400"}`}>{dupontResults.roe.toFixed(1)}%</span>
                              </div>
                            </div>
                            <div className="grid grid-cols-3 gap-2">
                              {[
                                { label: "Net Margin", sublabel: "NI ÷ Revenue", value: dupontResults.netMargin.toFixed(1) + "%", good: dupontResults.netMargin >= 10, tip: "How much of each yen of revenue becomes profit. Above 10% is strong." },
                                { label: "Asset Turn.", sublabel: "Rev ÷ Assets", value: dupontResults.assetTurnover.toFixed(2) + "x", good: dupontResults.assetTurnover >= 0.8, tip: "How efficiently assets generate revenue. Above 0.8x is efficient." },
                                { label: "Equity Mult.", sublabel: "Assets ÷ Equity", value: dupontResults.equityMultiplier.toFixed(2) + "x", good: dupontResults.equityMultiplier <= 3, tip: "Financial leverage — higher means more debt. Above 3x is risky." },
                              ].map(m => (
                                <div key={m.label} className="bg-white rounded-xl p-3 ring-1 ring-black/[0.04] text-center space-y-0.5 cursor-default" title={m.tip}>
                                  <p className="text-[9px] text-gray-300 font-medium">{m.label}</p>
                                  <p className="text-[9px] text-gray-200 font-mono">{m.sublabel}</p>
                                  <p className={`text-[14px] font-semibold font-mono tabular-nums ${m.good ? "text-gray-800" : "text-amber-500"}`}>{m.value}</p>
                                </div>
                              ))}
                            </div>
                            <div className="flex items-center justify-center gap-4 text-[10px] font-mono tabular-nums">
                              <span className="text-gray-400">ROA: <span className={`font-semibold ${dupontResults.roa >= 8 ? "text-emerald-500" : dupontResults.roa >= 4 ? "text-gray-600" : "text-amber-500"}`}>{dupontResults.roa.toFixed(1)}%</span></span>
                              <span className="text-gray-200">|</span>
                              <span className="text-gray-400">Leverage effect: <span className={`font-semibold ${dupontResults.roa !== 0 && dupontResults.roe / dupontResults.roa > 1.5 ? "text-amber-500" : "text-gray-600"}`}>{dupontResults.roa !== 0 ? (dupontResults.roe / dupontResults.roa).toFixed(1) + "x" : "—"}</span></span>
                            </div>
                            <p className="text-[9px] text-gray-300 text-center mt-1">
                              {dupontResults.roe >= 15 ? "Excellent ROE — high quality" : dupontResults.roe >= 8 ? "Acceptable ROE" : "Low ROE — investigate drivers"}
                              {" · "}
                              {dupontResults.equityMultiplier > 3 && dupontResults.netMargin < 8
                                ? "Leverage-driven — fragile if rates rise"
                                : dupontResults.netMargin >= 12 && dupontResults.equityMultiplier <= 2.5
                                ? "Margin-driven — high-quality ROE"
                                : dupontResults.assetTurnover >= 1.5
                                ? "Turnover-driven — asset-light model"
                                : "Balanced drivers"}
                            </p>
                          </div>
                        )}
                      </div>

                      {/* ── Compound Return Calculator ─────── */}
                      <div className="border-t border-black/[0.06] pt-5 mt-2">
                        <div className="text-center mb-4">
                          <div className="w-9 h-9 rounded-2xl bg-gradient-to-b from-black/[0.03] to-black/[0.06] flex items-center justify-center mx-auto ring-1 ring-black/[0.04] mb-2">
                            <Activity className="w-4 h-4 text-gray-400" />
                          </div>
                          <p className="text-[13px] font-semibold text-gray-800 tracking-[-0.02em]">Compound Return Calculator</p>
                          <p className="text-[10px] text-gray-300 mt-0.5">See how your investment grows with reinvested dividends</p>
                        </div>

                        <div className="space-y-2.5">
                          <div>
                            <label className="text-[10px] text-gray-400 font-medium mb-1 block">Investment Amount (¥)</label>
                            <input
                              type="number"
                              value={returnInputs.amount}
                              onChange={e => updateReturn("amount", e.target.value)}
                              placeholder="1000000"
                              className="w-full bg-white border border-black/[0.06] rounded-lg px-3 py-2 text-[13px] text-gray-700 font-mono placeholder-gray-200 outline-none focus:border-black/[0.15] focus:ring-1 focus:ring-black/[0.04] transition-all tabular-nums"
                            />
                          </div>
                          <div>
                            <label className="text-[10px] text-gray-400 font-medium mb-1 flex items-center justify-between">
                              Expected Annual Return (%)
                              <span className="text-[11px] font-mono text-gray-600">{returnInputs.expectedReturn}%</span>
                            </label>
                            <input
                              type="range"
                              min={1}
                              max={25}
                              step={0.5}
                              value={returnInputs.expectedReturn}
                              onChange={e => updateReturn("expectedReturn", e.target.value)}
                              className="w-full h-1.5 bg-black/[0.04] rounded-full appearance-none cursor-pointer accent-[#0a0a0a]"
                            />
                          </div>
                          {compoundResults && compoundResults.divYield > 0 && (
                            <div className="flex items-center gap-2 px-1">
                              <span className="text-[9px] text-gray-300">Capital gains: {returnInputs.expectedReturn}%</span>
                              <span className="text-gray-200">+</span>
                              <span className="text-[9px] text-emerald-400/80">Div yield: {compoundResults.divYield.toFixed(1)}%</span>
                              <span className="text-gray-200">=</span>
                              <span className="text-[9px] text-gray-500 font-semibold">Total: {compoundResults.totalReturn.toFixed(1)}%</span>
                            </div>
                          )}
                        </div>

                        {compoundResults && (
                          <div className="space-y-2.5 mt-4">
                            <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-gray-300/80 px-1">Portfolio Growth</p>
                            <div className="overflow-x-auto rounded-xl ring-1 ring-black/[0.06] bg-white">
                              <table className="w-full text-[10px]">
                                <thead>
                                  <tr className="bg-black/[0.02]">
                                    <th className="px-2 py-1.5 text-left text-gray-300 font-medium">Year</th>
                                    <th className="px-2 py-1.5 text-right text-gray-300 font-medium">Value</th>
                                    <th className="px-2 py-1.5 text-right text-gray-300 font-medium">Gain</th>
                                    <th className="px-2 py-1.5 text-right text-gray-300 font-medium">Multiple</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {compoundResults.rows.map(r => (
                                    <tr key={r.year} className="border-t border-black/[0.04]">
                                      <td className="px-2 py-1.5 font-mono text-gray-500">Yr {r.year}</td>
                                      <td className="px-2 py-1.5 text-right font-mono font-medium text-gray-800">¥{Math.round(r.value).toLocaleString()}</td>
                                      <td className="px-2 py-1.5 text-right font-mono text-emerald-500">+¥{Math.round(r.gain).toLocaleString()}</td>
                                      <td className="px-2 py-1.5 text-right font-mono text-gray-400">{r.multiple.toFixed(2)}x</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                            {/* Visual growth bars */}
                            <div className="space-y-1.5 mt-1">
                              {compoundResults.rows.map(r => {
                                const maxVal = compoundResults.rows.at(-1).value;
                                const pct = (r.value / maxVal) * 100;
                                return (
                                  <div key={r.year} className="flex items-center gap-2">
                                    <span className="text-[9px] text-gray-400 font-mono w-[28px] shrink-0 text-right">Yr{r.year}</span>
                                    <div className="flex-1 h-[6px] bg-black/[0.04] rounded-full overflow-hidden">
                                      <div className="h-full rounded-full bg-emerald-400/60 transition-all duration-500" style={{ width: `${pct}%` }} />
                                    </div>
                                    <span className="text-[9px] font-mono text-gray-500 tabular-nums w-[32px] shrink-0">{r.multiple.toFixed(1)}x</span>
                                  </div>
                                );
                              })}
                            </div>
                            {compoundResults.rows.length > 0 && (
                              <div className="bg-white rounded-xl p-3 ring-1 ring-black/[0.04] hover:ring-black/[0.08] hover:shadow-sm flex items-center justify-between transition-all duration-200 mt-2">
                                <div>
                                  <p className="text-[10px] text-gray-400 font-medium">20-Year Growth</p>
                                  <p className="text-[9px] text-gray-300">¥{parseFloat(returnInputs.amount).toLocaleString()} → ¥{Math.round(compoundResults.rows.at(-1).value).toLocaleString()}</p>
                                </div>
                                <p className="text-[18px] font-semibold text-emerald-500 tabular-nums font-mono">{compoundResults.rows.at(-1).multiple.toFixed(1)}x</p>
                              </div>
                            )}
                            <p className="text-[9px] text-gray-300 text-center mt-1">
                              Rule of 72: doubles every ~{(72 / compoundResults.totalReturn).toFixed(1)} years
                            </p>
                            {compoundResults.divYield > 0 && (
                              <div className="bg-white rounded-xl p-3 ring-1 ring-black/[0.04] mt-2">
                                <p className="text-[10px] text-gray-400 font-medium mb-1.5">Yield on Cost (if dividends grow at {returnInputs.expectedReturn}%)</p>
                                <div className="flex items-center gap-3 text-[10px] font-mono tabular-nums">
                                  <span className="text-gray-400">Now: <span className="text-gray-600 font-semibold">{compoundResults.divYield.toFixed(1)}%</span></span>
                                  <span className="text-gray-200">&rarr;</span>
                                  <span className="text-gray-400">Yr10: <span className="text-emerald-500 font-semibold">{(compoundResults.divYield * Math.pow(1 + parseFloat(returnInputs.expectedReturn) / 100, 10)).toFixed(1)}%</span></span>
                                  <span className="text-gray-200">&rarr;</span>
                                  <span className="text-gray-400">Yr20: <span className="text-emerald-500 font-semibold">{(compoundResults.divYield * Math.pow(1 + parseFloat(returnInputs.expectedReturn) / 100, 20)).toFixed(1)}%</span></span>
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                      {/* ── Monte Carlo Fair Value Simulator ── */}
                      {mcResults && (
                        <div className="border-t border-black/[0.06] pt-5 mt-2">
                          <div className="text-center mb-4">
                            <div className="w-9 h-9 rounded-2xl bg-gradient-to-b from-indigo-500/[0.06] to-violet-500/[0.12] flex items-center justify-center mx-auto ring-1 ring-indigo-500/[0.12] mb-2">
                              <BarChart3 className="w-4 h-4 text-indigo-400" />
                            </div>
                            <p className="text-[13px] font-semibold text-gray-800 tracking-[-0.02em]">Monte Carlo Simulator</p>
                            <p className="text-[10px] text-gray-300 mt-0.5">{mcResults.simCount.toLocaleString()} PERT-distributed DCF scenarios</p>
                          </div>

                          {/* Histogram */}
                          <div className="bg-white rounded-xl p-4 ring-1 ring-black/[0.04] hover:ring-black/[0.08] hover:shadow-sm transition-all duration-200">
                            <div className="flex items-end gap-[2px] h-[100px] mb-1">
                              {mcResults.histData.map((bar, i) => (
                                <div
                                  key={i}
                                  className="flex-1 rounded-t-[2px] transition-all duration-500 relative group cursor-crosshair"
                                  title={`¥${Math.round(bar.mid).toLocaleString()} — ${bar.count} scenarios (${((bar.count / mcResults.simCount) * 100).toFixed(1)}%)`}
                                  style={{
                                    height: `${Math.max(bar.height > 0 ? 3 : 0, bar.height)}%`,
                                    backgroundColor: i === mcResults.priceIdx
                                      ? "rgba(99, 102, 241, 0.7)"
                                      : bar.abovePrice
                                        ? "rgba(16, 185, 129, 0.35)"
                                        : "rgba(239, 68, 68, 0.25)",
                                  }}
                                >
                                  <div className="absolute -top-5 left-1/2 -translate-x-1/2 whitespace-nowrap text-[7px] font-mono font-bold hidden group-hover:block text-gray-500">
                                    ¥{Math.round(bar.mid).toLocaleString()}
                                  </div>
                                  {i === mcResults.priceIdx && (
                                    <div className="absolute -top-5 left-1/2 -translate-x-1/2 whitespace-nowrap text-[7px] font-mono text-indigo-500 font-bold group-hover:hidden">
                                      Price
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                            <div className="flex justify-between text-[8px] text-gray-200 font-mono mt-1">
                              <span>¥{Math.round(mcResults.lo).toLocaleString()}</span>
                              <span>¥{Math.round(mcResults.hi).toLocaleString()}</span>
                            </div>
                            <div className="flex items-center justify-between mt-1">
                              <span className="text-[8px] text-red-300">Overvalued</span>
                              <span className="text-[8px] text-emerald-400">Undervalued</span>
                            </div>
                          </div>

                          {/* Key stats */}
                          <div className="grid grid-cols-2 gap-2 mt-3">
                            <div className="bg-white rounded-xl p-3 ring-1 ring-black/[0.04] text-center">
                              <p className="text-[9px] text-gray-300 font-medium">Probability Undervalued</p>
                              <p className={`text-[20px] font-bold font-mono tabular-nums ${mcResults.underPct >= 60 ? "text-emerald-500" : mcResults.underPct >= 40 ? "text-amber-500" : "text-red-400"}`}>
                                {mcResults.underPct.toFixed(0)}%
                              </p>
                            </div>
                            <div className="bg-white rounded-xl p-3 ring-1 ring-black/[0.04] text-center">
                              <p className="text-[9px] text-gray-300 font-medium">Median Fair Value</p>
                              <p className="text-[20px] font-bold font-mono tabular-nums text-gray-800">
                                ¥{Math.round(mcResults.median).toLocaleString()}
                              </p>
                            </div>
                          </div>

                          {/* Percentile range */}
                          <div className="bg-white rounded-xl p-3 ring-1 ring-black/[0.04] mt-2">
                            <div className="flex items-center justify-between text-[9px] text-gray-300 mb-2">
                              <span>10th pctile</span>
                              <span className="text-gray-400 font-medium">Fair Value Range</span>
                              <span>90th pctile</span>
                            </div>
                            <div className="relative h-6 bg-black/[0.03] rounded-full overflow-hidden">
                              {/* 25-75 range */}
                              {(() => {
                                const range = mcResults.p90 - mcResults.p10;
                                if (range <= 0) return null;
                                const left25 = ((mcResults.p25 - mcResults.p10) / range) * 100;
                                const width50 = ((mcResults.p75 - mcResults.p25) / range) * 100;
                                const pricePos = ((parseFloat(calcInputs.price) - mcResults.p10) / range) * 100;
                                return (
                                  <>
                                    <div
                                      className="absolute top-0 h-full bg-indigo-500/15 rounded-full"
                                      style={{ left: `${left25}%`, width: `${width50}%` }}
                                    />
                                    <div
                                      className="absolute top-0 h-full w-[2px] bg-indigo-500"
                                      style={{ left: `${Math.max(0, Math.min(100, pricePos))}%` }}
                                    />
                                  </>
                                );
                              })()}
                            </div>
                            <div className="flex items-center justify-between mt-1.5 text-[10px] font-mono tabular-nums">
                              <span className="text-red-400">¥{Math.round(mcResults.p10).toLocaleString()}</span>
                              <span className="text-indigo-500 font-semibold">← ¥{parseFloat(calcInputs.price).toLocaleString()} →</span>
                              <span className="text-emerald-500">¥{Math.round(mcResults.p90).toLocaleString()}</span>
                            </div>
                          </div>

                          {/* Stats row */}
                          <div className="grid grid-cols-3 gap-1.5 mt-2">
                            {[
                              { label: "Mean", value: `¥${Math.round(mcResults.mean).toLocaleString()}` },
                              { label: "25th–75th", value: `¥${Math.round(mcResults.p25).toLocaleString()}–${Math.round(mcResults.p75).toLocaleString()}` },
                              { label: "vs Price", value: `${mcResults.median > parseFloat(calcInputs.price) ? "+" : ""}${(((mcResults.median - parseFloat(calcInputs.price)) / parseFloat(calcInputs.price)) * 100).toFixed(0)}%` },
                            ].map(s => (
                              <div key={s.label} className="bg-white rounded-lg px-2 py-2 ring-1 ring-black/[0.04] text-center">
                                <p className="text-[8px] text-gray-300 font-medium">{s.label}</p>
                                <p className="text-[10px] font-mono font-semibold text-gray-600 tabular-nums">{s.value}</p>
                              </div>
                            ))}
                          </div>

                          {/* Reshuffle */}
                          <button
                            onClick={() => setMcSeed(s => s + 1)}
                            className="w-full mt-3 flex items-center justify-center gap-2 py-2 rounded-xl bg-black/[0.02] ring-1 ring-black/[0.06] text-[11px] text-gray-400 hover:text-gray-600 hover:bg-black/[0.04] hover:ring-black/[0.1] transition-all duration-200"
                          >
                            <Shuffle className="w-3 h-3" />
                            Reshuffle simulation
                          </button>
                        </div>
                      )}

                      {/* ── Fair Value Convergence Map ──────── */}
                      {consensusMap && (
                        <div className="border-t border-black/[0.06] pt-5 mt-2">
                          <div className="text-center mb-4">
                            <div className="w-9 h-9 rounded-2xl bg-gradient-to-b from-emerald-500/[0.06] to-cyan-500/[0.12] flex items-center justify-center mx-auto ring-1 ring-emerald-500/[0.12] mb-2">
                              <Target className="w-4 h-4 text-emerald-400" />
                            </div>
                            <p className="text-[13px] font-semibold text-gray-800 tracking-[-0.02em]">Fair Value Convergence</p>
                            <p className="text-[10px] text-gray-300 mt-0.5">{consensusMap.total} methods plotted — do they agree?</p>
                          </div>

                          {/* Strip plot */}
                          <div className="bg-white rounded-xl p-4 ring-1 ring-black/[0.04] hover:ring-black/[0.08] hover:shadow-sm transition-all duration-200">
                            {/* Markers */}
                            <div className="relative h-[140px]">
                              {/* Background regions */}
                              <div className="absolute inset-0 flex">
                                <div style={{ width: `${consensusMap.pricePct}%` }} className="bg-red-500/[0.03] rounded-l-lg" />
                                <div style={{ width: `${100 - consensusMap.pricePct}%` }} className="bg-emerald-500/[0.03] rounded-r-lg" />
                              </div>
                              {/* Price line */}
                              <div
                                className="absolute top-0 bottom-0 w-[2px] bg-gray-800 z-10"
                                style={{ left: `${consensusMap.pricePct}%` }}
                              >
                                <div className="absolute -top-0.5 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-[7px] font-mono font-bold px-1.5 py-0.5 rounded-full whitespace-nowrap">
                                  ¥{parseFloat(calcInputs.price).toLocaleString()}
                                </div>
                              </div>
                              {/* Method markers — sorted by value, staggered to avoid overlap */}
                              {[...consensusMap.positioned].sort((a, b) => a.pct - b.pct).map((m, i) => {
                                const colors = { classic: "bg-amber-400", dcf: "bg-blue-400", mc: "bg-indigo-400", scenario: "bg-violet-400", avg: "bg-emerald-500" };
                                const textColors = { classic: "text-amber-600", dcf: "text-blue-600", mc: "text-indigo-600", scenario: "text-violet-600", avg: "text-emerald-600" };
                                // Alternate rows: even indices go top-half, odd go bottom-half
                                const slots = [24, 50, 76, 102];
                                const yPos = slots[i % slots.length];
                                return (
                                  <div key={m.label} className="absolute cursor-default" style={{ left: `${Math.max(2, Math.min(98, m.pct))}%`, top: `${yPos}px`, transform: "translateX(-50%)" }} title={`${m.label}: ¥${Math.round(m.value).toLocaleString()} (${m.above ? "+" : ""}${(((m.value - parseFloat(calcInputs.price)) / parseFloat(calcInputs.price)) * 100).toFixed(1)}% vs price)`}>
                                    <div className="flex flex-col items-center">
                                      <div className={`w-2.5 h-2.5 rounded-full ${colors[m.cat] || "bg-gray-400"} ring-2 ring-white shadow-sm ${m.faded ? "opacity-50" : ""}`} />
                                      <span className={`text-[7px] font-semibold mt-0.5 whitespace-nowrap ${textColors[m.cat] || "text-gray-500"} ${m.faded ? "opacity-50" : ""}`}>
                                        {m.label}
                                      </span>
                                      <span className={`text-[7px] font-mono tabular-nums ${m.above ? "text-emerald-500" : "text-red-400"} ${m.faded ? "opacity-50" : ""}`}>
                                        ¥{Math.round(m.value).toLocaleString()}
                                      </span>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                            {/* Scale */}
                            <div className="flex justify-between mt-1 text-[8px] font-mono text-gray-200">
                              <span>¥{Math.round(consensusMap.lo).toLocaleString()}</span>
                              <span>¥{Math.round(consensusMap.hi).toLocaleString()}</span>
                            </div>
                            <div className="flex items-center justify-between mt-0.5">
                              <span className="text-[8px] text-red-300">Overvalued zone</span>
                              <span className="text-[8px] text-emerald-400">Undervalued zone</span>
                            </div>
                          </div>

                          {/* Consensus stats */}
                          <div className="grid grid-cols-3 gap-2 mt-3">
                            <div className="bg-white rounded-xl p-3 ring-1 ring-black/[0.04] text-center">
                              <p className="text-[9px] text-gray-300 font-medium">Signal</p>
                              <p className={`text-[16px] font-bold font-mono tabular-nums ${consensusMap.bullPct >= 65 ? "text-emerald-500" : consensusMap.bullPct >= 40 ? "text-amber-500" : "text-red-400"}`}>
                                {consensusMap.bullish}/{consensusMap.total}
                              </p>
                              <p className="text-[8px] text-gray-300">say undervalued</p>
                            </div>
                            <div className="bg-white rounded-xl p-3 ring-1 ring-black/[0.04] text-center">
                              <p className="text-[9px] text-gray-300 font-medium">Conviction</p>
                              <p className={`text-[14px] font-bold ${consensusMap.conviction === "High" ? "text-emerald-500" : consensusMap.conviction === "Medium" ? "text-blue-500" : "text-amber-500"}`}>
                                {consensusMap.conviction}
                              </p>
                              <p className="text-[8px] text-gray-300">method agreement</p>
                            </div>
                            <div className="bg-white rounded-xl p-3 ring-1 ring-black/[0.04] text-center">
                              <p className="text-[9px] text-gray-300 font-medium">Priced-in g</p>
                              <p className="text-[16px] font-bold font-mono tabular-nums text-gray-800">
                                {consensusMap.impliedGrowth !== null ? `${consensusMap.impliedGrowth.toFixed(1)}%` : "—"}
                              </p>
                              <p className="text-[8px] text-gray-300">market expects</p>
                            </div>
                          </div>

                          {/* Implied growth insight */}
                          {consensusMap.impliedGrowth !== null && (
                            <div className="bg-white rounded-xl p-3 ring-1 ring-black/[0.04] mt-2">
                              <p className="text-[10px] text-gray-500 leading-relaxed">
                                <span className="font-semibold text-gray-700">Reverse DCF:</span>{" "}
                                At ¥{parseFloat(calcInputs.price).toLocaleString()}, the market prices in{" "}
                                {consensusMap.impliedGrowth < 0
                                  ? <><span className="font-mono font-semibold text-red-500">{consensusMap.impliedGrowth.toFixed(1)}%</span> annual earnings decline.</>
                                  : <><span className="font-mono font-semibold text-gray-800">{consensusMap.impliedGrowth.toFixed(1)}%</span> perpetual growth.</>
                                }
                                {parseFloat(calcInputs.growth) > 0 && (
                                  <> Your base case assumes <span className="font-mono font-semibold text-gray-800">{calcInputs.growth}%</span>.{" "}
                                    {consensusMap.impliedGrowth < parseFloat(calcInputs.growth) * 0.5
                                      ? <span className="text-emerald-600 font-medium">Market expectations are significantly below your estimate — strong upside if you're right.</span>
                                      : consensusMap.impliedGrowth < parseFloat(calcInputs.growth)
                                      ? <span className="text-emerald-600 font-medium">Market underestimates growth — potential upside.</span>
                                      : <span className="text-amber-600 font-medium">Market expects more growth than your estimate — risk of disappointment.</span>
                                    }
                                  </>
                                )}
                              </p>
                            </div>
                          )}

                          {/* Legend */}
                          <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2 justify-center">
                            {[
                              { color: "bg-amber-400", label: "Classic" },
                              { color: "bg-blue-400", label: "DCF/DDM" },
                              { color: "bg-indigo-400", label: "Monte Carlo" },
                              { color: "bg-violet-400", label: "Scenario" },
                              { color: "bg-emerald-500", label: "Average" },
                            ].map(l => (
                              <div key={l.label} className="flex items-center gap-1">
                                <div className={`w-1.5 h-1.5 rounded-full ${l.color}`} />
                                <span className="text-[8px] text-gray-300">{l.label}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Empty state */}
                      {!calcResults.graham && !calcResults.dcf && !scenarioResults && !dupontResults && !compoundResults && !mcResults && !consensusMap && (
                        <div className="text-center py-8">
                          <div className="w-10 h-10 rounded-2xl bg-gradient-to-b from-black/[0.02] to-black/[0.05] flex items-center justify-center mx-auto ring-1 ring-black/[0.04] mb-3">
                            <DollarSign className="w-5 h-5 text-gray-200" />
                          </div>
                          <p className="text-[12px] text-gray-400 font-medium">Enter numbers to see valuations</p>
                          <p className="text-[10px] text-gray-300 mt-1.5 max-w-[240px] mx-auto leading-relaxed">
                            Look for these in the report:
                          </p>
                          <div className="flex flex-col gap-1 mt-2 max-w-[200px] mx-auto text-left">
                            <p className="text-[9px] text-gray-300"><span className="text-gray-400 font-medium">EPS</span> — Income Statement or Highlights</p>
                            <p className="text-[9px] text-gray-300"><span className="text-gray-400 font-medium">Book Value</span> — Balance Sheet</p>
                            <p className="text-[9px] text-gray-300"><span className="text-gray-400 font-medium">Price</span> — Current share price</p>
                            <p className="text-[9px] text-gray-300"><span className="text-gray-400 font-medium">Dividend</span> — Annual per-share payout</p>
                          </div>
                        </div>
                      )}

                    </motion.div>
                  </div>

                ) : activeTab === "sources" ? (

                  /* ── Sources tab ──────────────────── */
                  <div className="flex-1 flex flex-col overflow-hidden">
                    <div className="shrink-0 px-4 py-3 space-y-3">
                      <div className="flex items-center gap-3 text-[11px]">
                        <span className="flex items-center gap-1.5 text-gray-400">
                          <Globe className="w-3 h-3 text-blue-400/60" />
                          <span className="font-mono text-blue-400/80">{allWebCount}</span>
                          <span>Web</span>
                        </span>
                        <span className="text-gray-200">&middot;</span>
                        <span className="flex items-center gap-1.5 text-gray-400">
                          <Database className="w-3 h-3 text-amber-400/60" />
                          <span className="font-mono text-amber-400/80">{allEdinetCount}</span>
                          <span>EDINET</span>
                        </span>
                      </div>

                      {sources.length > 5 && (
                        <div className="relative">
                          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-300" />
                          <input
                            type="text"
                            value={sourceFilter}
                            onChange={(e) => setSourceFilter(e.target.value)}
                            placeholder="Filter sources..."
                            className="w-full bg-black/[0.02] border border-black/[0.06] rounded-xl pl-9 pr-3 py-2 text-[12px] text-gray-600 placeholder-gray-400 outline-none focus:border-black/[0.12] transition-colors"
                          />
                        </div>
                      )}
                    </div>

                    <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-4 viewer-scroll">
                      {edinetSources.length > 0 && (
                        <div>
                          <div className="flex items-center gap-2 mb-2 px-1">
                            <FileText className="w-3.5 h-3.5 text-amber-400/60" />
                            <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-300">EDINET Filings</span>
                            <span className="text-[10px] text-gray-300 font-mono ml-auto">{edinetSources.length}</span>
                          </div>
                          <div className="space-y-1.5">
                            {edinetSources.map((s, i) => (
                              <SourceCard key={s.id || `e-${i}`} source={s} index={i} />
                            ))}
                          </div>
                        </div>
                      )}

                      {webSources.length > 0 && (
                        <div>
                          <div className="flex items-center gap-2 mb-2 px-1">
                            <Globe className="w-3.5 h-3.5 text-blue-400/60" />
                            <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-300">Web Sources</span>
                            <span className="text-[10px] text-gray-300 font-mono ml-auto">{webSources.length}</span>
                          </div>
                          <div className="space-y-1.5">
                            {webSources.map((s, i) => (
                              <SourceCard key={s.id || `w-${i}`} source={s} index={i} />
                            ))}
                          </div>
                        </div>
                      )}

                      {sources.length === 0 && (
                        <div className="flex flex-col items-center justify-center py-16 text-center">
                          <BookOpen className="w-8 h-8 text-gray-200 mb-3" />
                          <p className="text-[13px] text-gray-300">No sources available</p>
                          <p className="text-[11px] text-gray-300 mt-1">Sources will appear here when viewing reports</p>
                        </div>
                      )}

                      {sourceFilter && webSources.length === 0 && edinetSources.length === 0 && sources.length > 0 && (
                        <div className="text-center py-8">
                          <p className="text-[12px] text-gray-300">No sources match &ldquo;{sourceFilter}&rdquo;</p>
                        </div>
                      )}
                    </div>
                  </div>

                ) : activeTab === "notes" ? (

                  /* ── Notes tab ────────────────────── */
                  <div className="flex-1 flex flex-col overflow-hidden">
                    {/* Templates */}
                    <div className="shrink-0 px-4 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        {NOTE_TEMPLATES.map(t => (
                          <button
                            key={t.label}
                            onClick={() => insertTemplate(t.text)}
                            className="px-2.5 py-1 rounded-lg bg-black/[0.02] ring-1 ring-black/[0.06] text-[10px] text-gray-400 hover:text-gray-500 hover:bg-black/[0.04] hover:ring-black/[0.1] transition-all"
                          >
                            {t.label}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Textarea */}
                    <div className="flex-1 px-4 pb-2">
                      <textarea
                        ref={notesRef}
                        value={notes}
                        onChange={handleNotesChange}
                        placeholder="Your investment notes...&#10;&#10;Use the templates above to get started, or just type freely."
                        className="w-full h-full bg-black/[0.02] border border-black/[0.06] rounded-xl p-4 text-[13px] text-gray-600 placeholder-gray-400 outline-none focus:border-black/[0.12] resize-none font-mono leading-relaxed tracking-[-0.01em] transition-colors viewer-scroll"
                      />
                    </div>

                    {/* Notes footer */}
                    <div className="shrink-0 px-4 pb-4 flex items-center gap-3 text-[10px] text-gray-300">
                      {lastSaved && (
                        <span className="flex items-center gap-1 text-emerald-400/50">
                          <Check className="w-2.5 h-2.5" />
                          Saved
                        </span>
                      )}
                      {wordCount > 0 && (
                        <span className="font-mono">{wordCount} words</span>
                      )}
                      <div className="flex-1" />
                      {notes && (
                        <>
                          <button
                            onClick={copyNotes}
                            className="p-1 rounded hover:text-gray-400 hover:bg-black/[0.03] transition-all"
                            title="Copy notes"
                          >
                            <Copy className="w-3 h-3" />
                          </button>
                          <button
                            onClick={clearNotes}
                            className="p-1 rounded hover:text-red-400/60 hover:bg-red-500/5 transition-all"
                            title="Clear notes"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </>
                      )}
                    </div>
                  </div>

                ) : activeTab === "tools" ? (

                  /* ── Tools tab ─────────────────────── */
                  <div className="flex-1 overflow-y-auto px-5 py-4 viewer-scroll">
                    <motion.div
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
                      className="space-y-5 pt-1"
                    >
                      <div className="text-center space-y-2">
                        <div className="w-9 h-9 rounded-2xl bg-gradient-to-b from-black/[0.03] to-black/[0.06] flex items-center justify-center mx-auto ring-1 ring-black/[0.04]">
                          <Zap className="w-4 h-4 text-gray-400" />
                        </div>
                        <div>
                          <p className="text-[14px] font-semibold text-gray-800 tracking-[-0.02em]">
                            Research Tools
                          </p>
                          <p className="text-[11px] text-gray-300 mt-1 leading-relaxed">
                            {sources.length > 0
                              ? `${sources.length} sources · Institutional-grade analysis`
                              : "Institutional-grade analysis · Opens in Query"
                            }
                          </p>
                        </div>
                      </div>

                      <div className="space-y-5">
                        {TOOL_SECTIONS.map((section, si) => (
                          <motion.div
                            key={section.title}
                            initial={{ opacity: 0, y: 6 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: 0.06 + si * 0.1, duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
                          >
                            <div className="flex items-center gap-2.5 px-3 mb-2">
                              <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-gray-300/80">{section.title}</span>
                              <div className="flex-1 h-px bg-gradient-to-r from-black/[0.04] to-transparent" />
                              <span className="text-[9px] font-mono text-gray-200">{section.tools.length}</span>
                            </div>
                            <div className="space-y-1">
                              {section.tools.map((s, i) => {
                                const Icon = s.icon;
                                return (
                                  <motion.button
                                    key={s.label}
                                    onClick={() => navigate("/Query", { state: { prompt: s.prompt, company: companyName, sources } })}
                                    initial={{ opacity: 0, x: -8 }}
                                    animate={{ opacity: 1, x: 0 }}
                                    transition={{ delay: 0.1 + si * 0.1 + i * 0.04, duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                                    whileTap={{ scale: 0.98 }}
                                    className="w-full flex items-start gap-3 px-3 py-3 rounded-xl hover:bg-black/[0.02] active:bg-black/[0.04] transition-all duration-200 text-left group"
                                  >
                                    <div className={`w-8 h-8 rounded-[10px] ${s.bg} flex items-center justify-center shrink-0 mt-0.5 ring-1 ring-black/[0.02] group-hover:ring-black/[0.06] transition-all`}>
                                      <Icon className={`w-4 h-4 ${s.color} opacity-50 group-hover:opacity-90 transition-opacity`} />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                      <div className="text-[12.5px] font-medium text-gray-600 group-hover:text-gray-800 transition-colors tracking-[-0.01em] leading-tight">
                                        {s.label}
                                      </div>
                                      <div className="text-[10.5px] text-gray-300 group-hover:text-gray-400 transition-colors mt-0.5 leading-snug">
                                        {s.desc}
                                      </div>
                                    </div>
                                    <ExternalLink className="w-3 h-3 text-gray-200 group-hover:text-gray-400 shrink-0 transition-all duration-300 opacity-0 group-hover:opacity-100 mt-1.5" />
                                  </motion.button>
                                );
                              })}
                            </div>
                          </motion.div>
                        ))}
                      </div>
                    </motion.div>
                  </div>

                ) : (

                  /* ── Empty fallback ───────────────────── */
                  <div className="flex-1 flex items-center justify-center text-gray-300 text-sm">
                    Select a tab
                  </div>

                )}
              </div>

              {/* Custom scrollbar + cursor blink */}
              <style>{`
                .viewer-scroll::-webkit-scrollbar { width: 3px; }
                .viewer-scroll::-webkit-scrollbar-track { background: transparent; }
                .viewer-scroll::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.06); border-radius: 3px; }
                .viewer-scroll::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.12); }
                @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
              `}</style>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── Status bar ──────────────────────────────────── */}
      {!isFullscreen && (
        <div className="shrink-0 h-7 bg-[#f8f8fa] border-t border-black/[0.04] flex items-center px-5 gap-4 text-[10px] text-gray-300 font-mono">
          {reportData?.finishedAt && (
            <span className="flex items-center gap-1.5">
              <Clock className="w-2.5 h-2.5" />
              {new Date(reportData.finishedAt).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          {sources.length > 0 && (
            <span>{sources.length} sources ({allEdinetCount} EDINET, {allWebCount} Web)</span>
          )}
          <div className="flex-1" />
          {zoom !== 1 && <span>{Math.round(zoom * 100)}%</span>}
          <button onClick={() => setShortcutsOpen(true)} className="flex items-center gap-1 hover:text-gray-400 transition">
            <Keyboard className="w-2.5 h-2.5" />
            <span>?</span>
          </button>
        </div>
      )}

      {/* ── Keyboard shortcuts modal ────────────────────── */}
      <AnimatePresence>
        {shortcutsOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm"
            onClick={() => setShortcutsOpen(false)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              transition={{ duration: 0.2 }}
              className="bg-white rounded-2xl border border-black/[0.08] p-6 max-w-xs w-full shadow-2xl"
              onClick={e => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-5">
                <div className="flex items-center gap-2">
                  <Keyboard className="w-4 h-4 text-gray-400" />
                  <h3 className="text-[14px] font-semibold text-gray-700">Keyboard Shortcuts</h3>
                </div>
                <button onClick={() => setShortcutsOpen(false)} className="text-gray-300 hover:text-gray-500 transition">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="space-y-2.5">
                {SHORTCUTS.map(s => (
                  <div key={s.desc} className="flex items-center justify-between">
                    <span className="text-[12px] text-gray-400">{s.desc}</span>
                    <div className="flex gap-1">
                      {s.keys.map(k => (
                        <kbd key={k} className="px-2 py-0.5 rounded-md bg-black/[0.04] text-gray-500 text-[11px] font-mono ring-1 ring-black/[0.08] min-w-[26px] text-center">
                          {k}
                        </kbd>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-5 pt-3 border-t border-black/[0.06]">
                <p className="text-[10px] text-gray-300 text-center">Shortcuts are disabled when typing in inputs</p>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>



    </div>
  );
}
