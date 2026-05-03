% groundstation_params.m
% Shared system parameters for B-Raspi ground station models
% Version: 1.2 — Turnstile antenna

f_MHz = 137.1;
f_Hz = f_MHz * 1e6;
EIRP_dBW = 8.99;
G_rx_dBi = 2.15;
NF_cascade_dB = 1.08;      % updated — LNA at feedpoint
T_sys_K = 225;             % updated — turnstile configuration
L_atm_dB = 0.5;
L_misc_dB = 1.0;
% Note: L_pol_dB removed — turnstile gives circular polarisation match
alt_km = 820;
