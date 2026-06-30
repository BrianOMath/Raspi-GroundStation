% =========================================================================
%  groundstation_params.m
%  Shared system parameters for the B-Raspi ground station models.
%
%  This file declares PRIMITIVE inputs and physical constants only.
%  It performs NO computation and defines NO derived quantities — those
%  are computed by the scripts that source this file (e.g. the cascaded
%  noise figure, system noise temperature, EIRP, required C/N0, etc.).
%
%  Intended to be universal: sourced by meteor_link_budget.m and any other
%  B-Raspi analysis script, so it may contain more values than any single
%  script uses.
%
%  Version : 1.4 — Turnstile antenna, LNA indoors at SDR (~5 m coax before LNA)
%  System  : B-Raspi V1.0 (SysML model B-Raspi_v1_0.gaphor)
% =========================================================================

% -------------------------------------------------------------------------
%  PHYSICAL CONSTANTS
% -------------------------------------------------------------------------
c       = 3e8;            % Speed of light (m/s)
k_B     = 1.38e-23;       % Boltzmann constant (J/K)

% -------------------------------------------------------------------------
%  SATELLITE TRANSMITTER  (Meteor M2-3 / M2-4 LRPT)
% -------------------------------------------------------------------------
f_MHz     = 137.9;        % Downlink frequency (MHz) — M2-3: 137.1, M2-4: 137.9
P_tx_W    = 5.0;          % Transmit power (W) — estimated from published specs
G_tx_dBi  = 3.0;          % Tx antenna gain (dBi) — sat QFH/turnstile approx
L_tx_dB   = 1.0;          % Tx line/misc losses (dB)

% -------------------------------------------------------------------------
%  ORBITAL / GEOMETRY
% -------------------------------------------------------------------------
alt_km     = 820;         % Meteor orbital altitude (km) — sun-synchronous
R_earth_km = 6371;        % Earth radius (km)

% -------------------------------------------------------------------------
%  PROPAGATION LOSSES
% -------------------------------------------------------------------------
L_atm_dB  = 0.5;          % Atmospheric absorption (dB) — VHF low, 0.3-0.7 typical
L_rain_dB = 0.1;          % Rain/weather loss (dB) — negligible at 137 MHz
L_pol_dB  = 1.0;          % Polarisation mismatch (dB) — turnstile (CP) vs sat RHCP.
                          %   ~3 dB for a linear V-dipole; ~1 dB residual for a
                          %   real turnstile with imperfect axial ratio.
L_misc_dB = 1.0;          % Pointing/misc losses (dB)

% -------------------------------------------------------------------------
%  GROUND STATION RECEIVE CHAIN
%  Physical config: Turnstile -> ~5 m coax -> LNA (indoors at SDR) -> RTL-SDR V3
% -------------------------------------------------------------------------
% -- AntennaSubsystem: Turnstile --
G_rx_dBi   = 1.0;         % Turnstile gain (dBi) — NOMINAL estimate, no measured
                          %   pattern yet. Lower peak than a dipole but far more
                          %   uniform hemispherical coverage. To be refined by
                          %   fitting against measured SNR-vs-elevation data.

% -- RFFrontEnd: Coax (sits BEFORE the LNA, since the LNA is indoors at the SDR) --
L_coax_dB  = 0.5;         % Coax loss (dB) — ~5 m run at 137 MHz

% -- RFFrontEnd: LNA (SPF5189Z / RTL-SDR Blog wideband) --
G_lna_dB   = 20.0;        % LNA gain (dB)
NF_lna_dB  = 1.0;         % LNA noise figure (dB)

% -- ReceiverSubsystem: RTL-SDR V3 --
NF_sdr_dB  = 6.5;         % RTL-SDR V3 noise figure (dB) at 137 MHz

% -------------------------------------------------------------------------
%  NOISE TEMPERATURES
% -------------------------------------------------------------------------
T_sky_K   = 150;          % Sky/galactic noise at 137 MHz (K) — dominant at VHF
T_std_K   = 290;          % Standard reference temperature (K)

% -------------------------------------------------------------------------
%  SIGNAL / RECEIVER  (Meteor LRPT)
% -------------------------------------------------------------------------
data_rate_bps = 72e3;     % LRPT downlink data rate (bps)
BW_Hz         = 150e3;    % Receiver noise bandwidth (Hz)
Eb_N0_req_dB  = 5.5;      % Required Eb/N0 for QPSK @ BER 1e-5 (theoretical)
impl_loss_dB  = 2.0;      % Implementation / decoder loss (dB)
