% groundstation_params.m
% Shared system parameters for B-Raspi ground station models
% Version: 1.2 — Turnstile antenna

%  CONSTANTS
c       = 3e8;          % Speed of light (m/s)
k_B     = 1.38e-23;     % Boltzmann constant (J/K)
k_B_dB  = 10*log10(k_B); % dBW/K/Hz  = -228.6 dBW/K/Hz

f_MHz = 137.1;
f_Hz = f_MHz * 1e6;
EIRP_dBW = 8.99;
G_rx_dBi = 2.15;
NF_cascade_dB = 1.08;      % updated — LNA at feedpoint
T_sys_K = 225;             % updated — turnstile configuration
L_atm_dB = 0.5;
L_misc_dB = 1.0;
% Note: L_pol_dB removed — turnstile gives circular polarisation match
alt_km = 820;        % Altitude of satellite above Earth surface (km)
R_earth_km = 6371;  % Earth radius (km)

% Signal and receiver parameters
BW_Hz         = 150e3;        % Noise bandwidth — LRPT receiver
L_coax_dB     = 0.5;          % Coax cable loss
L_pol_dB      = 0.0;          % Turnstile — circular polarisation match, no loss
L_total_dB    = L_atm_dB + L_misc_dB + L_pol_dB;

k_B_dB        = -228.601;     % Boltzmann constant in dBW/K/Hz
T_sys_dBK     = 10*log10(T_sys_K);

% Required C/N0 threshold for LRPT decode
data_rate_bps      = 72e3;
Eb_N0_req_dB       = 5.5;
impl_loss_dB       = 2.0;
C_N0_req_dBHz      = Eb_N0_req_dB + impl_loss_dB + 10*log10(data_rate_bps);
