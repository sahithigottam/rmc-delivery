# PhD Research Direction: Ready-Mix Concrete Delivery

## Proposed framing

**Uncertainty-aware prediction and decision support for ready-mix concrete
delivery using live traffic and operational data.**

The delivery application is a research platform. Its features alone are not
a PhD contribution. Novelty must be established through a literature review,
rigorous experiments, and comparison with existing methods.

## Central research question

Can a model combining live traffic, weather, and delivery operations predict
deadline violations more accurately, and with better-calibrated uncertainty,
than Google ETA plus fixed safety rules?

Possible supporting questions:

- Can predictions generalize to unseen routes, plants, seasons, and regions?
- How does performance change when transferring between New Zealand and India?
- Do uncertainty-aware plant-selection policies reduce late deliveries without
  unnecessarily rejecting feasible deliveries?
- Can grounded LLM explanations improve dispatcher understanding without
  introducing factual errors or contradicting safety constraints?

These are candidate questions, not established novel contributions.

## Current implementation and limitations

The backend combines Google Maps routing/traffic, Open-Meteo weather, statistical
formulas, and concrete-delivery rules. It is not currently a trained
machine-learning model or a scientifically validated delivery-risk model.

### Numerical analysis

The current predictor:

- Uses Google travel time and traffic delay.
- Applies time-of-day, day-of-week, weather, and baseline correction factors.
- Uses configured mix windows of GP: 90 minutes, HE: 60 minutes, RE: 120 minutes,
  subject to implemented weather adjustments.
- Calculates remaining life as adjusted mix window minus a fixed five-minute
  loading allowance minus adjusted travel time.
- Assigns critical risk below zero remaining minutes, high below 15 minutes,
  moderate below 30 minutes, and low at 30 minutes or above.
- Blends a duration-based probability with a route-profile success rate.

These windows, factors, thresholds, and probabilities require domain validation.
They should not be presented as measured concrete quality or guaranteed delivery
success.

The predictor accepts a historical route profile, but the current plant-analysis
flow does not supply one. It therefore uses a hard-coded fallback profile with
zero observed trips. Collecting more trips does not currently cause automatic
learning or recalibration. Auckland/NZ-oriented assumptions are not validated
for Warangal or other Indian locations.

### LLM role

LLMs generate optional narratives, not the core ETA, remaining life, risk, or
backend plant ranking. The plant-analysis endpoint ranks valid results by
remaining life and optionally produces an overall comparison.

Ollama is the default configured provider and expects a local service at port
11434. That does not establish that Ollama is running on Render. Hosted Gemini
or OpenRouter may be used if configured; otherwise templates provide fallback
text.

Individual and comparison templates now share risk-specific dispatch advice:
critical risk says not to dispatch, high risk advises mitigation, moderate risk
requires caution, and low risk permits dispatch. Unknown risk requires review.
This fixes template consistency; it does not validate the predictions or enforce
safety constraints on LLM-generated narratives.

## Data currently collected

| Data category | Current capability | Research gap |
|---|---|---|
| Plant and route | Plant, origin/destination, coordinates, original route, distance, duration | Explicit test/simulation exclusion and provenance |
| GPS trajectory | Accepted positions with capture/receipt times; rejected-fix audits | Accuracy measurements and systematic quality checks |
| Trip lifecycle | Start, pause, resume, cancellation, completion events | Verified arrival and actual pouring timestamps |
| Traffic and reroutes | Check/reroute events and current ETA | Evaluation-ready prediction-to-outcome linkage |
| Concrete load | Fields for batch time, mix, grade, volume, retarder, expected pour duration | Actual pour start/end and measured concrete acceptability |
| Prediction snapshot | Frontend-supplied snapshot when provided at dispatch, plus catalogue snapshot | Guaranteed backend-generated, versioned prediction records |
| Weather | Weather fetched during analysis | Dedicated historical feature records with forecast issue times |
| Outcome | Succeeded/failed and completion-review information | Independently verified labels and failure reasons |
| Identity | User IDs for actions | Dedicated assigned-driver identity |

Completion can be operator-reported or timer-derived. A completion timestamp is
not automatically ground truth for arrival, unloading completion, or concrete
acceptability. Stored data availability also depends on durable deployment
storage and backups.

## Required research dataset

For each delivery, capture:

- Batch time, actual plant departure, site arrival, pouring start, and pouring end.
- Prediction issue time, forecast horizon, model/rule version, predicted ETA,
  probability, interval, and complete feature provenance.
- Google traffic estimates available at prediction time, planned route, GPS
  trajectory, reroutes, and location-quality indicators.
- Mix/admixture details, ambient temperature, load volume, and site waiting time.
- Verified outcome, failure/rejection reason, and quality measurements approved
  by concrete-domain experts.
- Test/simulation status and relevant business/region identifiers.

Distinguish arrival within a deadline from concrete acceptability. A timer alone
cannot establish concrete quality. Define the prediction target and labels with
domain experts before collecting or training against them.

Use actual timestamps rather than expected durations for operational ground
truth. Record missingness and provenance instead of silently filling gaps.
Exclude simulated trips and test plants from real-world validation.

## Experimental baselines and candidate methods

Start with:

1. Google ETA alone.
2. Google ETA plus a fixed safety buffer.
3. The current statistical/rule-based predictor.
4. A residual-error model, such as gradient boosting, predicting the difference
   between Google ETA and actual duration.
5. Quantile regression or conformal prediction for uncertainty intervals.

Use trajectory/deep-learning methods only if the dataset supports them and they
outperform simpler methods. Complexity is not itself a research contribution.

Conformal coverage claims depend on assumptions and calibration design; assess
their limitations under temporal and geographic distribution shifts.

## Evaluation design

| Output | Evaluation |
|---|---|
| Travel time | MAE, median absolute error, tail errors |
| ETA intervals | Empirical coverage and interval width |
| Deadline violation probability | Brier score, calibration plots, precision/recall |
| Plant-selection policy | Late-delivery rate, travel cost, unnecessary rejections |
| Generalization | Unseen routes, plants, seasons, regions |

Use chronological train/validation/test splits. Keep all records from one
delivery together; random GPS-row splits would leak information.

Prevent future traffic, realized weather, completion information, or later
reroutes from entering features for earlier predictions. Historical profile
construction must also use only data available at prediction time.

Report sample sizes, uncertainty in evaluation results, missing-data handling,
and performance across relevant subgroups. Use ablations to establish which
inputs actually improve predictions.

Evaluate selection policies offline or in shadow mode first. Logged outcomes
exist only for chosen plants/routes, so retrospective data alone cannot prove
what would have happened for unchosen alternatives.

## LLM research component

Use a hosted LLM to explain validated numerical results, not invent probabilities
or override dispatch constraints.

Compare it with templates on:

- Factual consistency with supplied predictions.
- Safety-constraint compliance.
- Dispatcher understanding and decision quality.
- Latency, cost, and reliability.

Enforce deterministic safety decisions outside the model and retain a consistent
fallback. Do not transmit driver identities, precise trajectories, private
addresses, or other sensitive data to external providers without appropriate
authorization and governance.

## Ethics and governance

GPS trajectories and driver identifiers are sensitive operational/personnel data.
Define access controls, consent or other appropriate legal basis, retention,
de-identification, and research ethics approval as required.

Separate research extracts from production data. De-identification must consider
that trajectories can reveal identities even when names are removed.

## Recommended sequence

1. Preserve template recommendation consistency and label uncalibrated estimates clearly.
2. Define domain-approved targets, timestamps, outcome labels, and data governance.
3. Persist reliable backend-generated prediction-versus-actual records.
4. Build an accuracy/calibration report for the existing baselines.
5. Collect sufficient real deliveries and investigate uncertainty-aware models.
6. Evaluate temporal/geographic generalization and decision policies.
7. Study grounded LLM explanations as a separate, measurable contribution.

The immediate priority is reliable data and evaluation, not a larger LLM.
No model-training pipeline, automated historical-profile update, or validated
accuracy/calibration study is currently implemented.

## Implementation references

- [Predictor](../app/rmc/predictor.py)
- [Plant analysis](../app/api/v1/endpoints/plants.py)
- [Prediction orchestration](../app/services/prediction.py)
- [LLM and template narratives](../app/services/llm_analyzer.py)
- [Trip records and events](../app/db/models.py)
- [Trip lifecycle and dispatch snapshots](../app/services/trip.py)
- [Weather integration](../app/services/weather.py)

This document records the project discussion, not a completed literature review
or evidence of novelty. Recheck implementation descriptions as the code evolves.
