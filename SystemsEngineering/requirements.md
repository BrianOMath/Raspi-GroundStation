# B-Raspi Ground Station — Requirements Specification

**Document status:** Issue 1
**System version:** B-Raspi V1.2 (turnstile antenna, mast-mounted LNA)
**Related documents:** `verification_matrix.md` (verification evidence), `technical_report.md` (design and validation), `../SysML/B-Raspi_v1_2.gaphor` (architecture model)

---

## 1. Purpose and scope

This document specifies the requirements for the B-Raspi satellite ground station (SatNOGS network station 4621, Dublin, Ireland). Requirements are derived from the mission statement and objectives in §2 and are verified in the accompanying verification matrix.

**Note on method.** The station was built before this specification was written; the requirements were derived retrospectively from the system's intended function and then verified against it. This is stated explicitly rather than presented as a requirements-first development, and it does not affect the validity of the verification evidence.

### 1.1 System boundary

**Within the system:** the antenna, RF front end, receiver, processing computer and its software pipeline, local data storage, and the local review interface.

**Outside the system:** the SatNOGS network (treated as an external interface), the satellites themselves, the site's mains power and network infrastructure, and the act of scheduling an observation — which is currently performed manually via the SatNOGS website by the station owner or by other network users.

### 1.2 Terminology

"Shall" denotes a binding requirement. Elevation refers to the satellite's maximum elevation above the local horizon during a pass, as reported by the SatNOGS network. "Decoded imagery" means at least one MSU-MR channel image successfully produced from a pass recording.

## 2. Mission statement and objectives

**Mission statement**

> The satellite ground station (Callsign: B-Raspi) shall autonomously receive, decode, and publish Meteor M2-x LRPT weather-satellite imagery from Dublin, Ireland, while producing the measurement data needed to validate its own RF link-budget model.

**Mission objectives**

| ID | Objective |
|---|---|
| **MO-1** | Reliably produce decoded imagery from Meteor M2-3 / M2-4 passes above an elevation threshold of 20° above the horizon. |
| **MO-2** | Operate unattended, capturing through to publication with no operator action per pass once a pass is scheduled. |
| **MO-3** | Record per-pass signal-quality measurements sufficient to compare measured performance against the link-budget prediction. |
| **MO-4** | Contribute observations to the SatNOGS network as a publicly verifiable record and as a contribution to the open-source satellite ground station network. |

## 3. Requirements

### 3.1 Functional (F)

| ID | Requirement | Traces to |
|---|---|---|
| **REQ-F-01** | The system shall demodulate and decode Meteor M2-x LRPT transmissions at 137.9 MHz (M2-4) and 137.1 MHz (M2-3). | MO-1 |
| **REQ-F-02** | The system shall detect the completion of each IQ recording and initiate processing without operator action. | MO-2 |
| **REQ-F-03** | The system shall record received signal-to-noise ratio at intervals of ≤ 1 second for the full duration of every processed pass. | MO-3 |
| **REQ-F-04** | The system shall associate each signal-quality sample with the satellite's elevation and azimuth at the corresponding time. | MO-3 |
| **REQ-F-05** | The system shall upload decoded imagery to the corresponding SatNOGS network observation. | MO-4 |
| **REQ-F-06** | The system shall store per-pass signal-quality records as structured, machine-readable files containing time, elevation, azimuth, and SNR for each sample. | MO-3 |
| **REQ-F-07** | The system shall provide a local interface for reviewing decoded imagery and signal-quality data for passes within the retention window, without requiring access to the SatNOGS network. | MO-3 |
| **REQ-F-08** | The system shall append each pass's signal-quality records to a persistent cumulative dataset. | MO-3 |

### 3.2 Performance (P)

| ID | Requirement | Traces to |
|---|---|---|
| **REQ-P-01** | ≥ 80% of passes with maximum elevation ≥ 20° shall yield decoded imagery. | MO-1 |
| **REQ-P-01b** | ≥ 90% of passes with maximum elevation ≥ 30° shall yield decoded imagery. | MO-1 |
| **REQ-P-02** | The receive chain shall achieve a cascaded noise figure ≤ 1.5 dB. | MO-1 |
| **REQ-P-03** | The RF link shall close with positive margin at all elevations ≥ 5°, verified by link-budget analysis. | MO-1 |

### 3.3 Operational (O)

| ID | Requirement | Traces to |
|---|---|---|
| **REQ-O-01** | The system shall retain per-pass signal-quality records indefinitely, while bulk observation products shall be retained for a minimum of 3 days. | MO-3 |
| **REQ-O-02** | The system shall be capable of scheduling and recording observations down to 5° elevation. | MO-1, MO-4 |

### 3.4 Interface (I)

| ID | Requirement | Traces to |
|---|---|---|
| **REQ-I-01** | The system shall obtain orbital elements (TLEs) for each observation from the SatNOGS network API. | MO-2, MO-3 |
| **REQ-I-02** | The station shall be registered on the SatNOGS network with public scheduling enabled, remaining accessible for observation scheduling by other network users. | MO-4 |

## 4. Traceability

Every requirement traces to at least one mission objective, and every objective is covered by at least one requirement:

| Objective | Requirements |
|---|---|
| MO-1 (decoded imagery ≥ 20°) | F-01, P-01, P-01b, P-02, P-03, O-02 |
| MO-2 (unattended operation) | F-02, I-01 |
| MO-3 (signal-quality measurement) | F-03, F-04, F-06, F-07, F-08, O-01, I-01 |
| MO-4 (network contribution) | F-05, O-02, I-02 |

Requirements trace downward to the architecture blocks in the SysML model: the RF chain requirements (P-02, P-03) to `AntennaSubsystem` and `RFFrontEnd`; the processing and analysis requirements (F-02 to F-04, F-06 to F-08) to the software architecture under `ProcessingSubsystem`; the retention requirement (O-01) to the cleanup service; and the network interface requirements (F-05, I-01, I-02) to the SatNOGS client and network boundary.

## 5. Deliberate exclusions and design notes

**Automatic recovery from network loss is not levied as a requirement.** The station occasionally requires a manual reset following WiFi outages at its installation location. Rather than specify a recovery requirement the system does not reliably meet, the capability is excluded from scope and the limitation is recorded as an accepted limitation in the verification matrix. Root cause is marginal WiFi coverage; mitigations (wired Ethernet, connectivity watchdog) have been identified but are not currently implemented.

**No availability requirement is levied** on REQ-I-02, for the same reason: station uptime is bounded by site network reliability, which lies outside the system boundary.

**Solution independence.** Requirements state what the system must do, not how. Implementation choices — SatDump for decoding, Welch PSD estimation for SNR, SGP4/Skyfield for orbital propagation, Flask for the local interface — are design decisions satisfying these requirements and are described in the technical report, not specified here.

**Scheduling is outside the system boundary** (§1.1). MO-2 is scoped to unattended operation *once a pass is scheduled*; programmatic scheduling via the SatNOGS API is identified as future work.

## 6. Revision history

| Issue | Change | Rationale |
|---|---|---|
| 1 | Initial specification, 15 requirements. | Retrospective capture of the as-built system. |
| 1 | REQ-P-01b added (16 requirements total). | Decode-rate measurement over 12–24 July 2026 showed the station's practical decode threshold lies near 30° rather than the 20° assumed when REQ-P-01 was written. REQ-P-01 is retained and recorded as failed; REQ-P-01b is added to capture demonstrated capability above 30°, with the threshold and success rate derived from measurement. See `verification_matrix.md` §Measurement record. |

*Note on REQ-O-02 / REQ-I-02:* an earlier draft combined the 5° scheduling capability and the network registration requirement in a single statement. These were separated so that each requirement carries a single verifiable claim.
