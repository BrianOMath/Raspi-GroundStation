% =========================================================================
%  Link Budget Analysis — Meteor M2-3 / M2-4 Ground Station
%  SysML Model: B-Raspi V1.0
%  Author : Brian
%  Date   : 2026-03-14
%
%  System Architecture (from SysML model B-Raspi_v1_0.gaphor):
%    AntennaSubsystem  : V-Dipole, Mount
%    RFFrontEnd        : LNA → CoaxCable → Bias-T
%    ReceiverSubsystem : RTL-SDR V3, USB Interface
%    ProcessingSubsystem: Raspberry Pi 4, SatNOGS Client Lite
%
%  Link: Meteor M2-3 / M2-4 → Ground Station (Dublin, IE)
%  Downlink signal: LRPT @ 137.1 / 137.9 MHz, QPSK, ~72 kbps
% =========================================================================

clear all; clc;

fprintf('=================================================================\n');
fprintf('  LINK BUDGET — Meteor M2-3/M2-4 → B-Raspi Ground Station\n');
fprintf('=================================================================\n\n');

% -------------------------------------------------------------------------
%  1. CONSTANTS
% -------------------------------------------------------------------------
c       = 3e8;          % Speed of light (m/s)
k_B     = 1.38e-23;     % Boltzmann constant (J/K)
k_B_dB  = 10*log10(k_B); % dBW/K/Hz  = -228.6 dBW/K/Hz

% -------------------------------------------------------------------------
%  2. SATELLITE TRANSMITTER  (Meteor M2-3 / M2-4)
% -------------------------------------------------------------------------
fprintf('--- SATELLITE (Meteor M2-3 / M2-4) ---\n');

f_MHz        = 137.1;            % Downlink frequency (MHz) — M2-3: 137.1, M2-4: 137.9
f_Hz         = f_MHz * 1e6;
lambda       = c / f_Hz;         % Wavelength (m)

P_tx_W       = 5.0;              % Transmit power (W) — estimated from published specs
P_tx_dBW     = 10*log10(P_tx_W);
G_tx_dBi     = 3.0;              % Tx antenna gain (dBi) — turnstile / quadrifilar helix approx
L_tx_dB      = 1.0;              % Tx line/misc losses (dB)

EIRP_dBW     = P_tx_dBW + G_tx_dBi - L_tx_dB;

fprintf('  Frequency            : %.1f MHz\n', f_MHz);
fprintf('  Tx Power             : %.1f W  (%.2f dBW)\n', P_tx_W, P_tx_dBW);
fprintf('  Tx Antenna Gain      : %.1f dBi\n', G_tx_dBi);
fprintf('  Tx Line Losses       : %.1f dB\n', L_tx_dB);
fprintf('  EIRP                 : %.2f dBW\n\n', EIRP_dBW);

% -------------------------------------------------------------------------
%  3. ORBITAL / GEOMETRY PARAMETERS
% -------------------------------------------------------------------------
fprintf('--- ORBITAL GEOMETRY ---\n');

alt_km     = 820;                 % Meteor orbital altitude (km) — sun-synchronous
R_earth_km = 6371;                % Earth radius (km)

% Slant range as function of elevation angle
% Min elevation = 5 deg
el_deg_vec = [5, 10, 20, 30, 45, 90];   % Elevation angles to evaluate

% Slant range formula: d = -R*sin(el) + sqrt((R+h)^2 - R^2*cos^2(el))
R_km   = R_earth_km;
h_km   = alt_km;
el_rad = deg2rad(el_deg_vec);
d_km   = -R_km .* sin(el_rad) + sqrt((R_km + h_km)^2 - R_km^2 .* cos(el_rad).^2);
d_m    = d_km * 1e3;

fprintf('  Orbital altitude     : %d km\n', alt_km);
fprintf('  Min elevation : 5 deg\n\n');

% -------------------------------------------------------------------------
%  4. FREE-SPACE PATH LOSS (FSPL)
% -------------------------------------------------------------------------
% FSPL(dB) = 20*log10(d) + 20*log10(f) + 20*log10(4*pi/c)
FSPL_dB = 20*log10(d_m) + 20*log10(f_Hz) + 20*log10(4*pi/c);

% -------------------------------------------------------------------------
%  5. ATMOSPHERIC & ADDITIONAL LOSSES
% -------------------------------------------------------------------------
L_atm_dB  = 0.5;   % Atmospheric absorption (dB) — VHF low, 0.3–0.7 typical
L_rain_dB = 0.1;   % Rain/weather loss (dB) — negligible at 137 MHz
L_pol_dB  = 3.0;   % Polarisation mismatch: V-dipole (linear) vs sat (RHCP) — worst case 3 dB
L_misc_dB = 1.0;   % Pointing/misc losses

L_total_dB = L_atm_dB + L_rain_dB + L_pol_dB + L_misc_dB;

fprintf('--- PROPAGATION LOSSES ---\n');
fprintf('  Atmospheric          : %.1f dB\n', L_atm_dB);
fprintf('  Rain/Weather         : %.1f dB\n', L_rain_dB);
fprintf('  Polarisation mismatch: %.1f dB  (linear vs RHCP)\n', L_pol_dB);
fprintf('  Misc / pointing      : %.1f dB\n', L_misc_dB);
fprintf('  Total additional     : %.1f dB\n\n', L_total_dB);

% -------------------------------------------------------------------------
%  6. GROUND STATION RECEIVE CHAIN  (from SysML: AntennaSubsystem → RFFrontEnd → ReceiverSubsystem)
% -------------------------------------------------------------------------
fprintf('--- GROUND STATION RECEIVE CHAIN (SysML: B-Raspi V1.0) ---\n');

% -- AntennaSubsystem: V-Dipole --
G_rx_dBi   = 2.15;    % V-dipole gain (dBi) — isotropic dipole ~2.15 dBi broadside
                       % Elevated 2 deg arms reduce gain at horizon; practical ~0 dBi at 2 deg el.

% -- RFFrontEnd: Coax Cable --
L_coax_dB  = 0.5;     % Coax cable loss (dB) — short run at 137 MHz, ~0.5 dB

% -- RFFrontEnd: LNA (generic RTL-SDR Blog LNA) --
G_lna_dB   = 20.0;    % LNA gain (dB)
NF_lna_dB  = 1.0;     % LNA noise figure (dB) — RTL-SDR Blog LNA4ALL / SPF5189Z typical

% -- ReceiverSubsystem: RTL-SDR V3 --
NF_sdr_dB  = 6.5;     % RTL-SDR V3 noise figure (dB) — typical at 137 MHz

% Cascaded noise figure using Friis formula:
% NF_cascade = NF1 + (NF2-1)/G1 + ...  (all linear)
NF_lna_lin = 10^(NF_lna_dB/10);
NF_sdr_lin = 10^(NF_sdr_dB/10);
G_lna_lin  = 10^(G_lna_dB/10);
L_coax_lin = 10^(L_coax_dB/10);

% Chain after antenna: coax loss → LNA → coax(bias-t, negligible) → SDR
% Coax before LNA acts as attenuator, its NF = its loss (L_coax_lin)
NF_cascade_lin = L_coax_lin + ...
                 (NF_lna_lin - 1) / (1/L_coax_lin) + ...
                 (NF_sdr_lin - 1) / (G_lna_lin / L_coax_lin);
NF_cascade_dB  = 10*log10(NF_cascade_lin);

% System noise temperature
T_sky_K    = 150;    % Sky noise temperature at 137 MHz (K) — galactic background dominant
T_ant_K    = T_sky_K;
T_std_K    = 290;    % Standard reference temperature (K)
T_sys_K    = T_ant_K + T_std_K * (NF_cascade_lin - 1);
T_sys_dBK  = 10*log10(T_sys_K);

% G/T figure of merit
G_T_dB     = G_rx_dBi - T_sys_dBK;

fprintf('  [AntennaSubsystem]   V-Dipole Gain : %.2f dBi\n', G_rx_dBi);
fprintf('  [RFFrontEnd]         Coax Loss     : %.1f dB\n', L_coax_dB);
fprintf('  [RFFrontEnd]         LNA Gain      : %.1f dB\n', G_lna_dB);
fprintf('  [RFFrontEnd]         LNA NF        : %.1f dB\n', NF_lna_dB);
fprintf('  [ReceiverSubsystem]  RTL-SDR V3 NF : %.1f dB\n', NF_sdr_dB);
fprintf('  Cascaded System NF   : %.2f dB\n', NF_cascade_dB);
fprintf('  Sky Noise Temp (T_ant): %d K\n', T_sky_K);
fprintf('  System Noise Temp    : %.1f K\n', T_sys_K);
fprintf('  G/T                  : %.2f dB/K\n\n', G_T_dB);

% -------------------------------------------------------------------------
%  7. LINK BUDGET  (calculated per elevation angle)
% -------------------------------------------------------------------------
fprintf('--- LINK BUDGET vs ELEVATION ANGLE ---\n');

% Signal parameters (Meteor M2-3/M2-4 LRPT)
data_rate_bps = 72e3;          % LRPT downlink data rate (bps)
BW_Hz         = 150e3;         % Receiver noise bandwidth (Hz) — RTL-SDR tuned BW for LRPT
Eb_N0_req_dB  = 5.5;           % Required Eb/N0 for QPSK at BER 1e-5 (theoretical ~5.5 dB)
impl_loss_dB  = 2.0;           % Implementation / decoder loss (dB)
Eb_N0_req_total_dB = Eb_N0_req_dB + impl_loss_dB;

% Convert Eb/N0 to C/N0 requirement:
% C/N0 = Eb/N0 + 10*log10(data_rate)
C_N0_req_dBHz = Eb_N0_req_total_dB + 10*log10(data_rate_bps);

% C/N (in bandwidth BW):
% C/N = C/N0 - 10*log10(BW)
C_N_req_dB    = C_N0_req_dBHz - 10*log10(BW_Hz);

fprintf('\n  Signal: LRPT QPSK @ %.0f kbps,  BW = %.0f kHz\n', ...
        data_rate_bps/1e3, BW_Hz/1e3);
fprintf('  Required Eb/N0 (QPSK BER 1e-5)  : %.1f dB\n', Eb_N0_req_dB);
fprintf('  Implementation loss              : %.1f dB\n', impl_loss_dB);
fprintf('  Required C/N0                    : %.2f dBHz\n', C_N0_req_dBHz);
fprintf('  Required C/N (in %.0f kHz BW)    : %.2f dB\n\n', BW_Hz/1e3, C_N_req_dB);

fprintf('  %-8s %-10s %-10s %-12s %-12s %-10s %-10s\n', ...
        'El (deg)', 'Range(km)', 'FSPL(dB)', 'Pr_rx(dBW)', 'C/N0(dBHz)', 'C/N(dB)', 'Margin(dB)');
fprintf('  %s\n', repmat('-', 1, 76));

for i = 1:length(el_deg_vec)
    el    = el_deg_vec(i);
    d     = d_km(i);
    fspl  = FSPL_dB(i);

    % Received power
    Pr_dBW = EIRP_dBW - fspl - L_total_dB + G_rx_dBi - L_coax_dB;

    % C/N0 (dBHz)
    % C/N0 = Pr - k_B - T_sys  (all in dB)
    CN0_dBHz = Pr_dBW - k_B_dB - T_sys_dBK;

    % C/N in noise bandwidth
    CN_dB = CN0_dBHz - 10*log10(BW_Hz);

    % Link margin
    margin_dB = CN0_dBHz - C_N0_req_dBHz;

    fprintf('  %-8.0f %-10.1f %-10.2f %-12.2f %-12.2f %-10.2f %-10.2f\n', ...
            el, d, fspl, Pr_dBW, CN0_dBHz, CN_dB, margin_dB);
end

% -------------------------------------------------------------------------
%  8. NOISE FLOOR  (RTL-SDR V3 practical sensitivity)
% -------------------------------------------------------------------------
fprintf('\n--- RECEIVER NOISE FLOOR ---\n');
N_floor_dBW = k_B_dB + T_sys_dBK + 10*log10(BW_Hz);
N_floor_dBm = N_floor_dBW + 30;
fprintf('  Noise bandwidth      : %.0f kHz\n', BW_Hz/1e3);
fprintf('  System noise floor   : %.2f dBW  (%.2f dBm)\n', N_floor_dBW, N_floor_dBm);

% -------------------------------------------------------------------------
%  9. SUMMARY TABLE  (key parameters)
% -------------------------------------------------------------------------
fprintf('\n=================================================================\n');
fprintf('  LINK BUDGET SUMMARY\n');
fprintf('=================================================================\n');
fprintf('  Satellite EIRP                 : %+.2f dBW\n', EIRP_dBW);
fprintf('  Free-space path loss @ 5 deg el: %.2f dB\n', FSPL_dB(2));
fprintf('  Free-space path loss @ 90 deg el: %.2f dB\n', FSPL_dB(end));
fprintf('  Additional losses              : %.1f dB\n', L_total_dB);
fprintf('  Rx Antenna Gain (V-Dipole)     : %.2f dBi\n', G_rx_dBi);
fprintf('  Cascaded System NF             : %.2f dB\n', NF_cascade_dB);
fprintf('  System G/T                     : %.2f dB/K\n', G_T_dB);
fprintf('  Required C/N0                  : %.2f dBHz\n', C_N0_req_dBHz);

% Worst case (min practical elevation ~5 deg)
el_5_idx = 2;  % index for 5 deg
Pr_worst_dBW = EIRP_dBW - FSPL_dB(el_5_idx) - L_total_dB + G_rx_dBi - L_coax_dB;
CN0_worst    = Pr_worst_dBW - k_B_dB - T_sys_dBK;
margin_worst = CN0_worst - C_N0_req_dBHz;

fprintf('\n  --- Worst Case (5 deg elevation) ---\n');
fprintf('  Received Power                 : %.2f dBW\n', Pr_worst_dBW);
fprintf('  C/N0                           : %.2f dBHz\n', CN0_worst);
fprintf('  Link Margin                    : %+.2f dB\n', margin_worst);

if margin_worst >= 3
    fprintf('  Status: LINK CLOSED (margin >= 3 dB)\n');
elseif margin_worst >= 0
    fprintf('  Status: MARGINAL LINK (0-3 dB margin — decode possible but unreliable)\n');
else
    fprintf('  Status: LINK INSUFFICIENT (negative margin — decoding unlikely)\n');
end

% -------------------------------------------------------------------------
%  10. OPTIONAL: PLOT — Link Margin vs Elevation
% -------------------------------------------------------------------------
el_plot = 2:1:90;
el_rad_plot = deg2rad(el_plot);
d_plot = -R_km .* sin(el_rad_plot) + sqrt((R_km + h_km)^2 - R_km^2 .* cos(el_rad_plot).^2);
d_m_plot = d_plot * 1e3;

FSPL_plot = 20*log10(d_m_plot) + 20*log10(f_Hz) + 20*log10(4*pi/c);
Pr_plot   = EIRP_dBW - FSPL_plot - L_total_dB + G_rx_dBi - L_coax_dB;
CN0_plot  = Pr_plot - k_B_dB - T_sys_dBK;
margin_plot = CN0_plot - C_N0_req_dBHz;

figure(1);
plot(el_plot, margin_plot, 'b-', 'LineWidth', 2);
hold on;
yline(3,  'g--', 'LineWidth', 1.5, 'Label', '3 dB (good)');
yline(0,  'r--', 'LineWidth', 1.5, 'Label', 'Closure threshold');
xlabel('Elevation Angle (degrees)');
ylabel('Link Margin (dB)');
title(sprintf('Link Margin vs Elevation — Meteor M2-3/M2-4 @ %.1f MHz\n(B-Raspi V1.0: V-Dipole + LNA + RTL-SDR V3)', f_MHz));
grid on;
legend('Link Margin', 'Good (3 dB)', 'Min (0 dB)', 'Location', 'SouthEast');
xlim([2 90]);

figure(2);
plot(el_plot, Pr_plot + 30, 'r-', 'LineWidth', 2);  % convert to dBm
xlabel('Elevation Angle (degrees)');
ylabel('Received Power (dBm)');
title('Received Signal Power vs Elevation Angle');
grid on;
xlim([2 90]);

fprintf('\n  Plots generated: Figure 1 = Link Margin, Figure 2 = Rx Power\n');
fprintf('=================================================================\n');
