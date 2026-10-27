# Cloudera Infrastructure Sizing Studio

A runnable step-by-step web application using the **uploaded Cloudera Capacity/Cluster Planning reference workbook**.

## Run on Windows / Linux / Mac

1. Install Python 3.10 or newer.
2. Open a terminal in this folder.
3. Run:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The browser UI opens at http://localhost:8501.

## What is included

- Six-step workflow: client profile → volumes/workload → hardware/rules → Data Services → input review/confirmation → results
- Separate Base and Data Services formulas mapped to the supplied calculators
- Multi-environment selection with independent Base/Data Services input profiles and separate cluster results for each selected environment
- TB/GB and GB/day/TB/day input selectors normalized to canonical TB and GB/day using the workbook's 1024 conversion
- Editable rules, worker profiles and Data Services per-unit resource parameters
- Storage/CPU/RAM node sizing, limiting-factor analysis, five-year storage and worker-count forecast
- Non-destructive what-if sensitivity analysis comparing baseline, data-only, peak-compute-only and combined increases; included in JSON and printable HTML reports
- Architecture warnings, review checklist, preliminary bill of materials
- Downloads: printable HTML, JSON results, CSV node inventory
- Per-data-class forecasting with individual growth, compression, cold-data share, retention, audit/log growth and average file size; estimated object counts are included in the calculation details
- Optional workload-derived CPU/RAM demand from editable per-TB and per-query factors, alongside direct peak-demand inputs
- Optional Kafka dedicated-pool estimate for retained replicated storage and throughput/partition-limited workers, using user-supplied per-node capacities
- Optional Kudu replicated-storage worker estimate and a manual required-service/node-role inventory for NiFi, HBase, management, Ranger/Atlas, external databases, and other dedicated services
- Per-environment workload scaling, Disaster Recovery operating-mode/profile inputs, separate-environment node roll-up, and an optional indicative Base CCU/data-entitlement comparison
- Optional manual Data Services AI GPU-node inventory in addition to CPU/RAM/block/cache sizing
- Project save/reopen through a portable JSON project file; AI-extracted values now target one explicitly selected environment
- Rules baseline and source are shown in the UI and included in reports. The workbook's sample inputs use 3x compression and 40% cold data.
- Results include a configurable positive sensitivity (5–100%) to test the effect of increases in Base raw data/ingest and peak CPU/RAM demand. Each scenario recalculates the deterministic sizing engine without changing the confirmed baseline. Data Services workloads and hardware remain fixed in these comparisons.
- Source workbook bundled for tracing hardcoded assumptions and planning references

## Input units and interpretation

- Initial raw data: TB or GB. Daily net-new ingest: GB/day or TB/day. Both are converted using the workbook convention of 1024 GB per TB.
- Annual ingest growth and cold data share: percentages. Design horizon: years. Compression, replication and EC overhead: multipliers (`x`).
- Peak workload CPU: total vCores at peak concurrency. Peak workload memory: total GB RAM at peak concurrency. These are workload totals, not per-job or per-server values, and drive CPU- and memory-based Base worker counts.
- Base worker hardware: nominal TB per disk, disks per worker, vCores per worker and GB RAM per worker. Reservation percentages reduce CPU/RAM available to workloads; disk utilization caps the raw disk capacity used for sizing.
- Data Services workload rows use quantity plus per-unit vCores, GB RAM, GB block storage and GB cache. The resulting aggregate demand is compared against each DS worker's capacity after configured overhead, reserve and headroom.
- Data Services can also account for customer-entered Control Plane resource overhead per connected environment. CDE concurrent jobs per worker and ExternalFS capacity are reported separately; neither ExternalFS capacity nor GPU-specific demand is used to infer worker count.
- Installed/required disk reported in TB is nominal raw capacity, not usable filesystem capacity. Verify actual usable capacity and vendor-specific behavior before procurement.

### Reading what-if scenarios

The sensitivity percentage applies separately to:

1. **Data-only:** initial raw data and daily ingest increase; forecast horizon, growth and protection assumptions stay fixed.
2. **Peak-compute-only:** total peak vCores and GB RAM increase; data assumptions stay fixed.
3. **Combined:** both data and peak compute increase.

The results show required and installed raw disk, Base worker count and its limiting sizing driver. Data Services counts are held at baseline and shown for context; scenarios are estimates, not forecasts or statistical confidence intervals.

## Agentic architecture / integration roadmap

`UI → requirement extraction/validation agent → versioned rule catalogue → deterministic sizing engine (engine.py) → architecture reviewer → report generator`

The shipping application is a **functional rule-driven application with an agent-ready architecture**, not an autonomous LLM orchestration service. It does not call an LLM, because no API credential or validated source/version selection was supplied. Add an LLM adapter *only* for questionnaire extraction, missing-information prompts and explanation; calculations remain deterministic.

## Known limits

- Peak concurrent workload inputs are total vCores and total GB RAM required at peak concurrency; they drive CPU- and memory-based worker counts. Estimate them from workload/concurrency analysis because the workbook does not derive them from data volume. If unknown, leave them at 0 to see a warning and do not treat the resulting worker count as complete.
- Per-class retention keeps the initial raw footprint and the most recent configured years of forecast ingest plus audit/log growth. Confirm that this retention interpretation matches the customer's policy before relying on it.
- Per-class object counts use `retained raw TB × 1,048,576 MB/TB ÷ average file size MB`; this is a metadata planning proxy, not an HDFS/Ozone namespace or inode forecast.
- Per-class CPU/RAM factors and Kafka per-node rates/capacities are explicit customer assumptions. Kafka is modeled with a linear retained-storage formula and throughput/partition constraints; broker replication overhead, controller placement, failure domains, and version-specific limits still need specialist review.
- The optional licensing comparison uses Base worker CCU from the entered worker profile and design raw TB after the entered exclusions. It is not a license quote or a determination of the applicable Cloudera entitlement.
- Dedicated NiFi, Kudu, HBase, management, external databases, monitoring, network/rack topology, and detailed DR replication/failover sizing are **not** comprehensively modeled. DR environments are separate profiles with an adjustable workload scale, not an automatic replicated architecture.
- The Kudu worker estimate is disk-only. The manual dedicated-service inventory records required roles and planned node hardware/counts; it does not derive those counts from workload benchmarks.
- Master node hardware and licensing are not fully specified in the calculated bill of materials.
- DS CPU/RAM figures in parts of the workbook are explicit planning assumptions. Confirm product version, compatibility and vendor guidance.
- The imported workbook is a reference, not dynamically executed by the application; formulas have been ported to the Python engine.
- Daily ingest conversion follows the workbook formula (GB/day divided by 1024 to produce TB). Forecast values are displayed to two decimal places, while calculations retain full precision.
- Selected environments are modeled as separate clusters; their node counts are not combined into a shared-cluster estimate.
- No business-specific upper caps were approved for workload/data inputs. The engine rejects non-finite and overflowing calculations; add explicit caps only after architecture/business approval.
- Saved JSON project files are portable local files, not a shared project database. Protect them as customer data and use organizational access controls when sharing.

## Optional production extensions

Connect an LLM with structured outputs for requirements mapping, a catalog database for versioned Cloudera rules, authentication, approval workflows, persistent scenarios and benchmarking/telemetry-based sizing. Validate with Cloudera documentation and hardware vendor teams before procurement.

## Optional AI agent setup

AI-assisted client requirement extraction and independent architecture review are included. The core sizing engine works without AI.

Set `OPENAI_API_KEY` in your shell before launching Streamlit (do not commit or paste keys into the UI). Optionally set `OPENAI_MODEL` (default is `gpt-4.1-mini`). The agent extracts explicitly mentioned numeric requirements into a reviewable preview; the user must click Apply. The AI review describes sizing gaps and cannot change computed nodes. A network connection to the configured API endpoint is required.

**Note:** The default model/API route may need updating for your organization. This release does not provide persistent multi-user authentication, scenario database or live product-version verification. Those are production-hardening tasks.
