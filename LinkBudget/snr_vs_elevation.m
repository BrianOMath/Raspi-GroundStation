% References
% Calculation of free-space attenuation -  ITU-R P.525-5 - https://www.itu.int/dms_pubrec/itu-r/rec/p/R-REC-P.525-5-202411-I!!PDF-E.pdf

clear all; clc;

fprintf('=================================================================\n');
fprintf('  SNR vs Elevation — Meteor M2-3/M2-4 -> B-Raspi Ground Station\n');
fprintf('=================================================================\n\n');

% -------------------------------------------------------------------------
%  1. Get Parameters
% -------------------------------------------------------------------------
run('groundstation_params.m')  %Pull Parameters for groundstation

% -------------------------------------------------------------------------
%  1b. DERIVED VALUES  (computed here from the primitives in the params file)
%      NOTE (Option A): these derivations are also present in
%      meteor_link_budget.m. If the system model changes, update BOTH scripts.
% -------------------------------------------------------------------------
% Boltzmann in dB (guard against it already being set in params)
if ~exist('k_B_dB', 'var'); k_B_dB = 10*log10(k_B); end
% Frequency in Hz (guard: params may already define f_Hz)
if ~exist('f_Hz', 'var'); f_Hz = f_MHz * 1e6; end

% Satellite EIRP
P_tx_dBW = 10*log10(P_tx_W);
EIRP_dBW = P_tx_dBW + G_tx_dBi - L_tx_dB;

% Total additional propagation losses
L_total_dB = L_atm_dB + L_rain_dB + L_pol_dB + L_misc_dB;

% Cascaded noise figure (Friis) — coax before LNA (LNA indoors at SDR):
%   F = L + (F_lna-1)*L + (F_sdr-1)*L/G_lna
NF_lna_lin = 10^(NF_lna_dB/10);
NF_sdr_lin = 10^(NF_sdr_dB/10);
G_lna_lin  = 10^(G_lna_dB/10);
L_coax_lin = 10^(L_coax_dB/10);
NF_cascade_lin = L_coax_lin + ...
                 (NF_lna_lin - 1) * L_coax_lin + ...
                 (NF_sdr_lin - 1) * L_coax_lin / G_lna_lin;
NF_cascade_dB  = 10*log10(NF_cascade_lin);

% System noise temperature
T_ant_K   = T_sky_K;
T_sys_K   = T_ant_K + T_std_K * (NF_cascade_lin - 1);
T_sys_dBK = 10*log10(T_sys_K);

% Required C/N0 for decode
C_N0_req_dBHz = Eb_N0_req_dB + impl_loss_dB + 10*log10(data_rate_bps);

fprintf('Derived: EIRP = %.2f dBW, NF_cascade = %.2f dB, T_sys = %.1f K, C/N0_req = %.2f dBHz\n\n', ...
        EIRP_dBW, NF_cascade_dB, T_sys_K, C_N0_req_dBHz);

% -------------------------------------------------------------------------
%  2. ORBITAL / GEOMETRY PARAMETERS
% -------------------------------------------------------------------------

% Slant range as function of elevation angle
% Elevation from 2 to 90 dgr in 1 degree steps
el_deg_vec = 2:1:90;   % Elevation angles to evaluate

% Slant range formula: d = -R*sin(el) + sqrt((R+h)^2 - R^2*cos^2(el))
R_km   = R_earth_km; % Earth radius (km)
h_km   = alt_km; % Altitude of satellite above Earth surface (km)
el_rad = deg2rad(el_deg_vec);
d_km   = -R_km .* sin(el_rad) + sqrt((R_km + h_km)^2 - R_km^2 .* cos(el_rad).^2);
d_m    = d_km * 1e3;

% Index helper: with el_deg_vec = 2:1:90, elevation E is at index (E-1).
% (Kept explicit so the reference markers below don't silently break if the
%  start elevation is ever changed.)
i5  = find(el_deg_vec == 5);
i30 = find(el_deg_vec == 30);
i90 = find(el_deg_vec == 90);

% Plotting slant
figure(1);
plot(el_deg_vec, d_km, 'b-', 'LineWidth', 2);
xlabel('Elevation Angle (degrees)');
ylabel('Slant Range (km)');
title('Slant Range vs Elevation Angle — Meteor M2-3/M2-4');
grid on;
xlim([2 90]);
ylim([0 3500]);

% Add reference markers at key elevations
hold on;
plot(5,  d_km(i5),  'ro', 'MarkerSize', 8);
plot(30, d_km(i30), 'gs', 'MarkerSize', 8);
plot(90, d_km(i90), 'k^', 'MarkerSize', 8);
legend('Slant Range', '5 deg', '30 deg', '90 deg', 'Location', 'NorthEast');
hold off;
fprintf('Slant Range at 5 deg elevation  = %.1f km\n', d_km(i5));
fprintf('Slant Range at 30 deg elevation = %.1f km\n', d_km(i30));
fprintf('Slant Range at 90 deg elevation = %.1f km\n', d_km(i90));

% -------------------------------------------------------------------------
%  3. FREE-SPACE PATH LOSS (FSPL)
% -------------------------------------------------------------------------
% FSPL(dB) = 20*log10(d) + 20*log10(f) + 20*log10(4*pi/c)
FSPL_dB = 20*log10(d_m) + 20*log10(f_Hz) + 20*log10(4*pi/c);

% Plotting FSPL
figure(2);
plot(el_deg_vec, FSPL_dB, 'r-', 'LineWidth', 2);
xlabel('Elevation Angle (degrees)');
ylabel('Free-Space Path Loss (dB)');
title('FSPL vs Elevation Angle — Meteor M2-3/M2-4');
grid on;
xlim([2 90]);

% Add reference markers
hold on;
plot(5,  FSPL_dB(i5),  'ro', 'MarkerSize', 8);
plot(30, FSPL_dB(i30), 'gs', 'MarkerSize', 8);
plot(90, FSPL_dB(i90), 'k^', 'MarkerSize', 8);
legend('FSPL', '5 deg', '30 deg', '90 deg', 'Location', 'NorthEast');
hold off;

fprintf('FSPL at 5 deg elevation  = %.2f dB\n', FSPL_dB(i5));
fprintf('FSPL at 30 deg elevation = %.2f dB\n', FSPL_dB(i30));
fprintf('FSPL at 90 deg elevation = %.2f dB\n', FSPL_dB(i90));

% -------------------------------------------------------------------------
%  4. Received Power and SNR Calculation
% -------------------------------------------------------------------------
% Received Power = EIRP - FSPL - L_total + G_rx - L_coax
% C/N0 = Pr - k_B - T_sys
% Margin = C/N0 - C/N0_required

% Received power at each elevation angle
Pr_dBW = EIRP_dBW - FSPL_dB - L_total_dB + G_rx_dBi - L_coax_dB;

% Carrier to noise density
CN0_dBHz = Pr_dBW - k_B_dB - T_sys_dBK;

% Link margin above decoding threshold
margin_dB = CN0_dBHz - C_N0_req_dBHz;

fprintf('\nReceived Power at 5 deg  = %.2f dBW\n', Pr_dBW(i5));
fprintf('Received Power at 30 deg = %.2f dBW\n', Pr_dBW(i30));
fprintf('Received Power at 90 deg = %.2f dBW\n', Pr_dBW(i90));
fprintf('C/N0 at 5 deg            = %.2f dBHz\n', CN0_dBHz(i5));
fprintf('C/N0 at 30 deg           = %.2f dBHz\n', CN0_dBHz(i30));
fprintf('C/N0 at 90 deg           = %.2f dBHz\n', CN0_dBHz(i90));
fprintf('Link margin at 5 deg     = %.2f dB\n',   margin_dB(i5));
fprintf('Link margin at 90 deg    = %.2f dB\n',   margin_dB(i90));
fprintf('Required C/N0            = %.2f dBHz\n', C_N0_req_dBHz);

figure(3);
plot(el_deg_vec, margin_dB, 'b-', 'LineWidth', 2);
hold on;
yline(3,  'g--', 'LineWidth', 1.5, 'Label', 'Good (3 dB)');
yline(0,  'r--', 'LineWidth', 1.5, 'Label', 'Decode threshold');
xlabel('Elevation Angle (degrees)');
ylabel('Link Margin (dB)');
title('Link Margin vs Elevation — Meteor M2-3/M2-4, Turnstile');
grid on;
xlim([2 90]);
hold off;
