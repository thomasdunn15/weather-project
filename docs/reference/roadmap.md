# Project Roadmap: Weather Markets Prediction System

## The big picture

The thesis: GEFS produces probabilistic forecasts (31 ensemble members per run). The naive way to extract probabilities ("count fraction of members above threshold") is biased. Statistical post-processing can correct those biases. ML post-processing can improve further. Kalshi's market prices reflect retail traders who are using neither. The gap between properly post-processed probabilities and market-implied probabilities is the edge.

Each phase of the project moves closer to capturing that gap reliably.

## Month 1: Data infrastructure and the naive baseline

### Week 1: Plumbing (current phase)

Three ingestion pipelines: GEFS forecasts, NWS observations, Kalshi prices. By end of week, all three flowing into Postgres for KNYC. No modeling yet — just plumbing.

### Week 2: Daily aggregation, baseline probabilities, evaluation infrastructure

Compute "the daily high" from raw forecast data, because Kalshi contracts resolve on daily highs but GEFS gives 3-hourly forecasts.

For each (run, member, target_date) combination, the daily high is the maximum of the t2m values across the local-day window. Predicting the high for April 30 in NYC means taking the max of all t2m values for valid_times falling within April 30 00:00 EDT to April 30 23:59 EDT (which is April 30 04:00 UTC to May 1 03:59 UTC). Computing this requires careful timezone handling.

Once ensemble daily highs are computed (31 numbers per target_date per run), compute the *naive ensemble probability* of any threshold being exceeded:

> P(high > 72°F) ≈ (number of members with daily_high > 72) / 31

This is the week-1-of-modeling baseline. For each Kalshi contract, compute this probability and compare to the market price.

Also build evaluation infrastructure: Brier score, log score, CRPS, calibration plots, reliability diagrams. These tell you how good your probabilities actually are. Use them constantly for the rest of the project. Backtest the naive baseline on historical data and document where it's biased — this becomes the motivation for more sophisticated methods.

### Week 3: Statistical post-processing (EMOS)

The naive baseline has known problems. Ensembles are typically *underdispersive* — the spread between members is narrower than the actual forecast uncertainty, so the naive method assigns probabilities that are too extreme (predicts 95% when the truth is 80%). Models also have systematic biases that vary by season, lead time, and temperature regime.

EMOS (Ensemble Model Output Statistics) addresses this with a beautiful, simple idea: fit a Gaussian distribution where the mean and variance are linear functions of the ensemble's mean and spread. Specifically:

> daily_high ~ Normal(μ, σ²)
>
> μ = a + b · ensemble_mean
> σ² = c + d · ensemble_spread²

Fit a, b, c, d on historical data (forecast-observation pairs). For any new forecast, compute the predicted distribution and integrate to get the probability of exceeding any threshold. The result is a calibrated, sharp probability that beats the naive baseline.

Add features: day of year (seasonality), persistence (yesterday's actual temp), recent forecast errors. Each feature is another linear term in the regression.

Implement Kelly bet sizing: given probability and market price, what fraction of bankroll should be bet? This is the bridge between probabilities and trading decisions.

### Week 4: Validation and decision

Out-of-sample testing on data the training never saw. Stress test on losing trades. Realistic cost modeling (Kalshi's spread eats much of the apparent edge). Decide whether to start trading small ($5-20 per position) on the strongest signals.

End of month 1: a baseline post-processing model with documented calibration, paper trading running, and a real decision about going live.

## Months 2-6: Where machine learning actually enters

This is where it gets interesting. EMOS is a good start but it's a linear model with hand-engineered features. ML lets you replace the linearity assumption and potentially the feature engineering.

### Month 2: Multi-model ensemble — adding ECMWF

ECMWF (European Centre for Medium-Range Weather Forecasts) is generally regarded as the most accurate operational weather model in the world. ECMWF's open-data ensemble is freely available, similar structure to GEFS.

Add it to the ingestion pipeline (separate `model_id = 'ecmwf'` rows in the forecasts table) and treat its members as additional inputs to the post-processing model. The EMOS regression now has more inputs: GEFS ensemble mean, GEFS spread, ECMWF ensemble mean, ECMWF spread, and the model can learn how to weight them. Combining models almost always beats any single model.

### Month 3: Distributional regression with neural networks

This is the first real ML beyond LLM wrappers. The idea: instead of fitting a parametric Gaussian with linear coefficients, train a neural network that takes raw forecast features as input and outputs the parameters of a probability distribution.

Concretely, the network's input layer takes things like:
- Each ensemble member's predicted daily high (62 features: 31 GEFS + 31 ECMWF)
- Day of year, encoded as sin/cos for cyclicity
- Recent observations (last 3, 7, 14 days)
- Recent forecast errors

The output layer produces two numbers: μ and σ for a Gaussian over the daily high. Or more flexibly, parameters of a richer distribution like a mixture of Gaussians, a Student's t, or a normalizing flow.

The network is trained by minimizing the negative log likelihood (equivalent to log score, a proper scoring rule). This is called "distributional regression" or "DRN" (Distributional Regression Networks).

Implement in PyTorch. The architecture is simple: 2-3 fully connected layers with ReLU activations, maybe 64-256 units per layer. Training takes minutes on CPU. The math you need is just gradient descent and the Gaussian PDF — easier than most ML applications.

This typically beats EMOS by 5-15% on log score, sometimes more on long lead times.

### Month 4: Foundation model integration

The recent revolution in weather forecasting is neural network models that match or beat traditional numerical models. The big three:

- **GraphCast** (Google DeepMind, 2023): graph neural network operating on spherical mesh. Outperforms traditional models on most benchmarks at lead times beyond ~3 days.
- **Pangu-Weather** (Huawei, 2022): transformer-based, very fast inference.
- **FourCastNet** (NVIDIA): adaptive Fourier neural operator.

Their weights are public. Run inference yourself, or use cloud-hosted versions. The output is a deterministic forecast (not ensemble), but you can perturb the inputs slightly (analog-style perturbations from historical analyses) to generate a pseudo-ensemble.

Add these as additional inputs to the distributional regression network. So now the model has GEFS members, ECMWF members, GraphCast forecast, Pangu forecast, FourCastNet forecast, all as features. The post-processing learns to weight them based on which ones perform best in which regimes.

This sounds elaborate but is conceptually simple: more high-quality inputs → better post-processing.

### Month 5: Calibration and conformal prediction

Even with a good distributional regression model, probabilities might not be perfectly calibrated. Conformal prediction is a framework that gives provably calibrated prediction intervals under fairly weak assumptions.

The basic idea: hold out a calibration set. Compute prediction intervals from the model on this set. Adjust the intervals so they actually cover the realized observations at the desired rate (say, 95% of intervals contain the realized high). This adjustment is provably correct in finite samples.

Conformalized quantile regression is the specific technique most useful here. Not needed until the model is otherwise solid, but when needed, it's a clean way to ensure trading-relevant probabilities are reliable.

### Month 6: Multi-task learning and expansion

Up to this point, modeling has been KNYC only. But there's data for many cities (or could be ingested). Multi-task learning trains one model that jointly forecasts for many cities, sharing learned representations. Often beats per-city models because the shared structure (general post-processing patterns) transfers.

By end of month 6: a real ML pipeline that beats simple linear post-processing, validated on multiple cities, with calibration guarantees. Probably ~15-30% better than EMOS on log score, which translates to dramatically better edge against retail markets.

## Months 6-12: Scale, sophistication, and other contracts

### Months 7-9: Other weather contracts

Temperature is solved. Apply the same framework to:

- **Daily lows.** Same model architecture, different target.
- **Average temperature** (monthly contracts).
- **Precipitation.** Harder because precipitation is highly skewed (lots of zeros, occasional big values). Switch from Gaussian distributional regression to something like a mixture model with a "rain or no rain" component plus a continuous component for amount.
- **Hurricane formation/landfall.** Seasonal, niche, but big mispricings exist.

Each new contract type teaches something new about the modeling.

### Months 9-12: Scale, tooling, and decisions

By now there's a working trading system. The question becomes: how big can it scale?

Some things to build:
- Better order execution (don't just market-order, post limit orders strategically)
- Risk management (max position size, max daily loss, correlation between trades)
- Monitoring dashboards (real-time P&L, model calibration drift)
- Backfill automation (when adding a new model or feature, rerun historical backtests)

The decision at the end of year 1: is this a hobby that pays for itself, a serious side business, or the seed of something bigger? Track record by then will inform the answer.

## Where ML inference specifically happens

To make the ML side concrete, here's where models actually run in the pipeline:

**Training (offline, periodic):** Once a week, retrain the post-processing model on the latest historical data. This takes minutes to hours. Save the trained model weights to disk. Training data is the accumulated forecast/observation pairs from the database.

**Inference (online, each forecast):** When a new GEFS run finishes ingesting, the code:
1. Loads the trained model weights from disk
2. For each (target_date, lead_time) of interest, constructs the feature vector (ensemble members, day of year, recent observations, etc.)
3. Runs the feature vector through the model to get the predicted distribution
4. For each Kalshi contract, integrates the distribution to get the probability of the bracket resolving yes
5. Compares to market prices, logs the comparison, and (eventually) places trades where edge exceeds costs

The inference is the key operational moment. Each time it runs, it produces tradeable probabilities for live contracts.

**Monitoring (continuous):** Track the model's live performance. Are its predictions calibrated against realized outcomes? Is performance drifting from what backtests suggested? Drift triggers retraining or investigation.

This pattern — train offline, infer online, monitor continuously — is the standard ML operations pattern in production systems. By month 6, all three pieces are running.

## What the skills compound into

The valuable thing isn't the trading P&L, although that's nice. It's the skills:

**Data engineering:** ingestion pipelines, time-series databases, idempotent processing, monitoring. Everything learned here transfers directly to quantitative trading roles.

**Probabilistic forecasting and calibration:** these techniques apply far beyond weather. Any quant problem involves predicting probabilities. EMOS, distributional regression, conformal prediction are all useful in finance, insurance, ad tech, etc.

**ML beyond text generation:** real distributional regression, training neural networks, fitting probabilistic models. The kind of ML that matters for serious quantitative work, not the LLM-wrapper kind that's commoditizing.

**Trading systems:** Kelly sizing, backtesting, execution, risk management. Knowing how a real trading system works from the inside.

**Domain expertise:** weather forecasting is a real, technical domain. By month 6, more about ensemble post-processing than 99% of people in finance. That kind of niche expertise is rare and valuable.

In a quant interview 6-12 months from now, "tell me about a project that demonstrates your statistical thinking" has a genuinely impressive answer.

## What this looks like in daily routine

When employed as a quant and doing this on the side, the rhythm becomes:

- Early morning: check the previous day's resolutions, see how the model's probabilities scored against actuals, look at any losses
- Evening: 30-60 minutes on whatever this week's improvement is (new feature, new model, fixing a bug)
- Weekend: 3-4 hours on bigger work (training new models, backfilling, exploration)
- Cron jobs handle the actual ingestion and trading; nothing manual runs daily

It's a marathon, not a sprint. The compounding from year 1 is what matters.
